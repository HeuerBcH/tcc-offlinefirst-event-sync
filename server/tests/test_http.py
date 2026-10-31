import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync_server.config import ServerConfig  # noqa: E402
from sync_server.handler import build_server  # noqa: E402


def batch(seqs):
    return {"client_id": "c1", "events": [
        {"event_id": f"ev-{s}", "seq": s, "entity_id": "e1",
         "operation": "CREATE" if s == 1 else "UPDATE",
         "payload": {"title": "t", "description": "d", "value": s} if s == 1 else {"value": s},
         "created_at_ns": 0} for s in seqs]}


class ServerHarness:
    def __init__(self, drop_response_rate=0.0, seed=0):
        self.tmp = tempfile.TemporaryDirectory()
        config = ServerConfig(host="127.0.0.1", port=0, data_dir=self.tmp.name,
                              drop_response_rate=drop_response_rate, server_seed=seed)
        self.httpd = build_server(config)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05})
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.httpd.app.close()
        self.tmp.cleanup()

    def read_requests_log(self):
        path = Path(self.tmp.name) / "server_requests.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.server = ServerHarness()

    def tearDown(self):
        self.server.stop()

    def test_health_and_keepalive(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(resp.read()), {"status": "ok"})
        sock_before = conn.sock
        body = json.dumps(batch([1, 2])).encode()
        conn.request("POST", "/sync/events", body, {"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read())
        self.assertIs(conn.sock, sock_before, "conexão deveria ser reaproveitada (keep-alive)")
        self.assertEqual([r["status"] for r in data["results"]], ["APPLIED", "APPLIED"])
        self.assertEqual(data["last_applied_seq"], 2)
        conn.request("GET", "/state/hashes")
        hashes = json.loads(conn.getresponse().read())
        self.assertEqual(list(hashes["hashes"]), ["e1"])
        conn.close()
        log = self.server.read_requests_log()
        self.assertEqual(len(log), 1)
        self.assertFalse(log[0]["dropped"])
        self.assertIsNotNone(log[0]["responded_at_ns"])
        self.assertEqual([e["seq"] for e in log[0]["events"]], [1, 2])

    def test_bad_request(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.request("POST", "/sync/events", b"xx", {"Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()


class DropResponseTest(unittest.TestCase):
    def test_dropped_response_closes_connection_after_commit(self):
        server = ServerHarness(drop_response_rate=1.0)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
            conn.request("POST", "/sync/events", json.dumps(batch([1])).encode(),
                         {"Content-Type": "application/json"})
            with self.assertRaises(http.client.RemoteDisconnected):
                conn.getresponse()
            conn.close()
            log = server.read_requests_log()
            self.assertTrue(log[0]["dropped"])
            self.assertIsNone(log[0]["responded_at_ns"])
            self.assertEqual(server.httpd.app.storage.last_applied_seq("c1"), 1)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
