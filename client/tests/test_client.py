import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync_client.config import ClientConfig  # noqa: E402
from sync_client.generator import (  # noqa: E402
    CREATE, DELETE, UPDATE, generate_operations, operation_counts,
)
from sync_client.store import EventStore  # noqa: E402
from sync_client.synchronizer import backoff_ceiling, backoff_delay  # noqa: E402
from sync_client.transport import Transport  # noqa: E402


class SimulatedCrash(Exception):
    pass


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tmp.name) / "c.sqlite", "c1", queue_limit=10000)
        self.ops = generate_operations(5, seed=1)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def counts(self):
        c = self.store.conn
        return (c.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                c.execute("SELECT value FROM meta WHERE key='next_seq'").fetchone()[0])

    def test_crash_mid_transaction_leaves_nothing(self):
        for stage in ("after_entity", "after_event"):
            def crash(s, stage=stage):
                if s == stage:
                    raise SimulatedCrash(stage)
            self.store.fault_hook = crash
            with self.assertRaises(SimulatedCrash):
                self.store.record(self.ops[0])
            self.assertEqual(self.counts(), (0, 0, "1"), stage)

    def test_successful_write_updates_state_event_and_seq(self):
        self.assertEqual(self.store.record(self.ops[0]), 1)
        self.assertEqual(self.counts(), (1, 1, "2"))
        row = self.store.conn.execute(
            "SELECT status, attempts, payload, payload_bytes FROM events").fetchone()
        self.assertEqual(row[0], "PENDING")
        self.assertEqual(row[1], 0)
        self.assertEqual(row[3], len(row[2].encode("utf-8")))

    def test_queue_full_rejects_before_transaction(self):
        self.store.queue_limit = 2
        self.assertEqual(self.store.record(self.ops[0]), 1)
        self.assertEqual(self.store.record(self.ops[1]), 2)
        self.assertIsNone(self.store.record(self.ops[2]))
        self.assertEqual(self.store.event_count(), 2)

    def test_batch_lifecycle(self):
        for op in self.ops:
            self.store.record(op)
        batch = self.store.take_batch(3)
        self.assertEqual([e["seq"] for e in batch], [1, 2, 3])
        ids = [e["event_id"] for e in batch]
        self.store.apply_results(ids, {ids[0]: "APPLIED", ids[1]: "DUPLICATE", ids[2]: "REJECTED_GAP"})
        rows = dict(self.store.conn.execute("SELECT seq, status FROM events").fetchall())
        self.assertEqual(rows, {1: "ACKED", 2: "ACKED", 3: "PENDING", 4: "PENDING", 5: "PENDING"})
        batch = self.store.take_batch(50)
        self.assertEqual([e["seq"] for e in batch], [3, 4, 5])
        self.store.release([e["event_id"] for e in batch])
        attempts = dict(self.store.conn.execute("SELECT seq, attempts FROM events").fetchall())
        self.assertEqual(attempts, {1: 1, 2: 1, 3: 2, 4: 1, 5: 1})
        self.assertEqual(self.store.unacked_count(), 3)


class GeneratorTest(unittest.TestCase):
    def test_same_seed_same_sequence(self):
        self.assertEqual(generate_operations(1000, seed=42), generate_operations(1000, seed=42))

    def test_different_seed_different_sequence(self):
        self.assertNotEqual(generate_operations(50, seed=1), generate_operations(50, seed=2))

    def test_rules(self):
        ops = generate_operations(1000, seed=7)
        alive = set()
        for op in ops:
            if op.operation == CREATE:
                self.assertNotIn(op.entity_id, alive)
                self.assertEqual(set(op.payload), {"title", "description", "value"})
                self.assertEqual(len(op.payload["title"]), 64)
                self.assertEqual(len(op.payload["description"]), 64)
                self.assertIsInstance(op.payload["value"], int)
                alive.add(op.entity_id)
            elif op.operation == UPDATE:
                self.assertIn(op.entity_id, alive)
                self.assertEqual(len(op.payload), 1)
            else:
                self.assertIn(op.entity_id, alive)
                self.assertEqual(op.payload, {})
                alive.remove(op.entity_id)
        counts = operation_counts(ops)
        self.assertEqual(sum(counts["actual"].values()), 1000)
        self.assertGreaterEqual(counts["converted_to_create"], 1)  # a 1ª operação é sempre CREATE
        self.assertEqual(ops[0].operation, CREATE)

    def test_mix_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            generate_operations(10, 1, mix=(0.5, 0.5, 0.5))


class BackoffTest(unittest.TestCase):
    def test_ceiling(self):
        self.assertEqual(backoff_ceiling(1, 0.5, 30), 0.5)
        self.assertEqual(backoff_ceiling(2, 0.5, 30), 1.0)
        self.assertEqual(backoff_ceiling(7, 0.5, 30), 30)  # 0,5 × 64 = 32 → 30
        self.assertEqual(backoff_ceiling(50, 0.5, 30), 30)

    def test_delays_within_bounds(self):
        rng = Random(123)
        for k in range(1, 40):
            ceiling = min(30, 0.5 * 2 ** (k - 1))
            for _ in range(200):
                d = backoff_delay(rng, k, 0.5, 30)
                self.assertGreaterEqual(d, 0)
                self.assertLessEqual(d, ceiling)

    def test_deterministic_with_seed(self):
        a = [backoff_delay(Random(9), k, 0.5, 30) for k in range(1, 10)]
        b = [backoff_delay(Random(9), k, 0.5, 30) for k in range(1, 10)]
        self.assertEqual(a, b)


class RawServer:
    """Servidor TCP mínimo: lê uma requisição HTTP completa e responde com bytes fixos."""

    def __init__(self, response):
        self.response = response
        self.received = b""
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve)
        self.thread.start()

    def _serve(self):
        conn, _ = self.sock.accept()
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(65536)
            head, _, rest = data.partition(b"\r\n\r\n")
            length = next(int(line.split(b":")[1]) for line in head.split(b"\r\n")
                          if line.lower().startswith(b"content-length"))
            while len(rest) < length:
                rest += conn.recv(65536)
            self.received = data[:len(head) + 4] + rest
            conn.sendall(self.response)
        self.sock.close()


class ByteCountTest(unittest.TestCase):
    def test_counts_match_bytes_on_the_wire(self):
        body = b'{"results":[{"event_id":"x","status":"APPLIED"}],"last_applied_seq":1}'
        response = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        server = RawServer(response)
        transport = Transport("127.0.0.1", server.port, timeout_s=5)
        result = transport.post_json("/sync/events", {"client_id": "c", "events": [{"a": "é" * 10}]})
        server.thread.join(5)
        transport.close()
        self.assertEqual(result.outcome, "ok")
        self.assertEqual(result.bytes_sent, len(server.received))
        self.assertEqual(result.bytes_recv, len(response))
        self.assertTrue(server.received.startswith(b"POST /sync/events HTTP/1.1\r\n"))

    def test_connection_refused_is_conn_error(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        result = Transport("127.0.0.1", port, timeout_s=8).post_json("/sync/events", {})
        self.assertEqual(result.outcome, "conn_error")

    def test_timeout(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)  # aceita a conexão no backlog e nunca responde
        try:
            result = Transport("127.0.0.1", s.getsockname()[1], timeout_s=0.5).post_json("/x", {})
            self.assertEqual(result.outcome, "timeout")
        finally:
            s.close()


class ConfigTest(unittest.TestCase):
    def test_defaults_match_fixed_parameters(self):
        c = ClientConfig.from_args([], env={})
        self.assertEqual((c.n_events, c.rate_per_s, c.batch_size, c.request_timeout_s,
                          c.backoff_base_s, c.backoff_max_s), (1000, 10.0, 50, 10.0, 0.5, 30.0))

    def test_env_and_args(self):
        c = ClientConfig.from_args(["--n-events", "100"], env={"SYNC_SEED": "77"})
        self.assertEqual((c.n_events, c.seed), (100, 77))
        json.dumps(c.to_dict())


if __name__ == "__main__":
    unittest.main()
