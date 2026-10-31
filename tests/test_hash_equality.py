import unittest
from pathlib import Path

import harness  # noqa: F401  (ajusta sys.path)
from sync_client import state_hash as client_hash
from sync_server import state_hash as server_hash


class HashEqualityTest(unittest.TestCase):
    def test_same_entity_same_hash(self):
        cases = [
            ("e1", {"title": "a" * 64, "description": "b" * 64, "value": 123456}, 0),
            ("e2", {"value": 1, "title": "x"}, 1),
            ("e3", {}, True),
            ("é", {"title": "ção"}, False),
        ]
        for eid, data, deleted in cases:
            self.assertEqual(client_hash.entity_hash(eid, data, deleted),
                             server_hash.entity_hash(eid, data, deleted))

    def test_modules_have_identical_code(self):
        root = Path(__file__).resolve().parents[1]

        def code(path):
            text = path.read_text(encoding="utf-8")
            return text[text.index('"""', 3) + 3:]  # ignora a docstring, que cita o outro arquivo

        self.assertEqual(code(root / "client/sync_client/state_hash.py"),
                         code(root / "server/sync_server/state_hash.py"))


if __name__ == "__main__":
    unittest.main()
