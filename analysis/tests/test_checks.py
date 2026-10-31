import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from checks import expected_commands, s9_duplicates_after_drop  # noqa: E402

IFACES = {"tcc-client": "eth0", "tcc-server": "eth0"}


class ExpectedCommandsTest(unittest.TestCase):
    def test_constant_without_netem(self):
        self.assertEqual(expected_commands({"type": "constant", "online": None}, "loss 100%", IFACES),
                         {"tc qdisc del dev eth0 root"})

    def test_cycles_with_online_netem(self):
        sc = {"type": "cycles", "online": "delay 60ms 12ms distribution normal loss 5%"}
        self.assertEqual(expected_commands(sc, "loss 100%", IFACES), {
            "tc qdisc del dev eth0 root",
            "tc qdisc replace dev eth0 root netem delay 60ms 12ms distribution normal loss 5%",
            "tc qdisc replace dev eth0 root netem loss 100%",
        })

    def test_initial_outage(self):
        self.assertEqual(expected_commands({"type": "initial_outage", "online": None}, "loss 100%", IFACES),
                         {"tc qdisc del dev eth0 root", "tc qdisc replace dev eth0 root netem loss 100%"})


class S9DuplicatesTest(unittest.TestCase):
    def write_log(self, records):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        server = Path(tmp.name) / "server"
        server.mkdir()
        (server / "server_requests.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return Path(tmp.name)

    def test_applied_in_dropped_then_duplicate(self):
        run = self.write_log([
            {"dropped": True, "events": [{"event_id": "a", "status": "APPLIED"},
                                         {"event_id": "b", "status": "APPLIED"}]},
            {"dropped": False, "events": [{"event_id": "a", "status": "DUPLICATE"},
                                          {"event_id": "b", "status": "DUPLICATE"},
                                          {"event_id": "c", "status": "APPLIED"}]},
        ])
        self.assertEqual(s9_duplicates_after_drop(run), (1, 2, []))

    def test_missing_duplicate_is_reported(self):
        run = self.write_log([
            {"dropped": False, "events": [{"event_id": "a", "status": "DUPLICATE"}]},
            {"dropped": True, "events": [{"event_id": "a", "status": "APPLIED"}]},
        ])
        self.assertEqual(s9_duplicates_after_drop(run), (1, 1, ["a"]))


if __name__ == "__main__":
    unittest.main()
