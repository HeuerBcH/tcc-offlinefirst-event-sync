"""Ponta a ponta local, sem Docker nem netem (plano, seção 8)."""
import json
import unittest
from collections import Counter

from harness import LocalRun, read_jsonl


def check_run(test, run, n):
    """Verificações de R1, R2, C1, C3 e C4 diretamente sobre os arquivos da execução."""
    with run.client_db() as cdb, run.server_db() as sdb:
        created = cdb.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        acked = cdb.execute("SELECT COUNT(*) FROM events WHERE status='ACKED'").fetchone()[0]
        applied = sdb.execute("SELECT COUNT(DISTINCT event_id) FROM applied_events").fetchone()[0]
        seqs = [r[0] for r in sdb.execute("SELECT seq FROM applied_events ORDER BY applied_at_ns, rowid")]
        ignored = sdb.execute(
            "SELECT COUNT(*) FROM applied_events WHERE effect='APPLIED_IGNORED_CONFLICT'").fetchone()[0]
    test.assertEqual(created, n)
    test.assertEqual(acked, n)
    test.assertEqual(applied / created * 100, 100.0)          # R1
    test.assertEqual(created - applied, 0)                     # R2
    applied_in = Counter(e["event_id"] for r in read_jsonl(run.server_dir / "server_requests.jsonl")
                         for e in r["events"] if e["status"] == "APPLIED")
    test.assertEqual(sum(1 for c in applied_in.values() if c > 1), 0)  # C1
    c3 = (1 if seqs[0] != 1 else 0) + sum(1 for a, b in zip(seqs, seqs[1:]) if b != a + 1)
    test.assertEqual(c3, 0)                                    # C3
    client_hashes = json.loads((run.client_dir / "client_state_hashes.json").read_text())
    c4 = len(set(client_hashes) ^ set(run.server_hashes)) + sum(
        1 for k in set(client_hashes) & set(run.server_hashes) if client_hashes[k] != run.server_hashes[k])
    test.assertEqual(c4, 0)                                    # C4
    test.assertEqual(ignored, 0)
    return read_jsonl(run.client_dir / "requests.jsonl")


class EndToEndLocalTest(unittest.TestCase):
    def test_n100_without_netem(self):
        run = LocalRun(n_events=100, seed=11, jitter_seed=12).run()
        try:
            self.assertEqual(run.exit_code, 0)
            requests = check_run(self, run, 100)
            self.assertTrue(all(r["outcome"] == "ok" for r in requests))
            self.assertTrue(all(r["batch_size"] <= 50 for r in requests))
            done = json.loads((run.client_dir / "client_done.json").read_text())
            gen = json.loads((run.client_dir / "generation_done.json").read_text())
            # 100 operações a 10/s: a última sai em t0 + 9,9 s.
            self.assertAlmostEqual((gen["last_created_at_ns"] - gen["t0_ns"]) / 1e9, 9.9, delta=0.3)
            self.assertGreaterEqual(done["t_queue_empty_ns"], gen["last_created_at_ns"])
        finally:
            run.cleanup()


class DropResponseLocalTest(unittest.TestCase):
    def test_dropped_responses_are_retried_as_duplicates(self):
        run = LocalRun(n_events=100, rate_per_s=50, drop_response_rate=0.3, server_seed=5,
                       seed=21, jitter_seed=22).run()
        try:
            self.assertEqual(run.exit_code, 0)
            requests = check_run(self, run, 100)
            outcomes = Counter(r["outcome"] for r in requests)
            self.assertGreater(outcomes["remote_disconnected"], 0)
            self.assertEqual(set(outcomes) - {"ok", "remote_disconnected"}, set())
            server_log = read_jsonl(run.server_dir / "server_requests.jsonl")
            self.assertGreater(sum(1 for r in server_log if r["dropped"]), 0)
            duplicates = sum(1 for r in server_log for e in r["events"] if e["status"] == "DUPLICATE")
            self.assertGreater(duplicates, 0)  # C2 > 0
        finally:
            run.cleanup()


if __name__ == "__main__":
    unittest.main()
