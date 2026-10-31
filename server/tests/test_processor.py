import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync_server.processor import (  # noqa: E402
    APPLIED, DUPLICATE, EFFECT_IGNORED, EFFECT_OK, NOT_PROCESSED, REJECTED_GAP,
    BatchProcessor, InvalidBatch, parse_body,
)
from sync_server.state_hash import entity_hash  # noqa: E402
from sync_server.storage import ServerStorage  # noqa: E402

CLIENT = "c1"


def ev(seq, op="CREATE", entity="e1", payload=None, event_id=None):
    if payload is None:
        payload = {"title": "t", "description": "d", "value": 1} if op == "CREATE" else {}
    return {"event_id": event_id or f"ev-{seq}", "seq": seq, "entity_id": entity,
            "operation": op, "payload": payload, "created_at_ns": 0}


class ProcessorTestCase(unittest.TestCase):
    def setUp(self):
        self.storage = ServerStorage(":memory:")
        self.anomalies = []
        self.proc = BatchProcessor(self.storage, on_event=self.anomalies.append)

    def tearDown(self):
        self.storage.close()

    def process(self, events):
        return self.proc.process(CLIENT, events, received_at_ns=1)

    def statuses(self, results):
        return [r["status"] for r in results]


class IdempotencyTest(ProcessorTestCase):
    def test_same_batch_twice_is_all_duplicate_and_state_unchanged(self):
        batch = [ev(1, "CREATE", "e1"), ev(2, "UPDATE", "e1", {"value": 7}),
                 ev(3, "CREATE", "e2"), ev(4, "DELETE", "e2")]
        results, last = self.process(batch)
        self.assertEqual(self.statuses(results), [APPLIED] * 4)
        self.assertEqual(last, 4)
        hashes_before = self.storage.entity_hashes()
        applied_before = self.storage.conn.execute("SELECT COUNT(*) FROM applied_events").fetchone()[0]

        results, last = self.process(batch)
        self.assertEqual(self.statuses(results), [DUPLICATE] * 4)
        self.assertEqual(last, 4)
        self.assertEqual(self.storage.entity_hashes(), hashes_before)
        applied_after = self.storage.conn.execute("SELECT COUNT(*) FROM applied_events").fetchone()[0]
        self.assertEqual(applied_after, applied_before)

    def test_partial_overlap_applies_only_new_events(self):
        self.process([ev(1), ev(2, "UPDATE", payload={"value": 2})])
        results, last = self.process([ev(1), ev(2, "UPDATE", payload={"value": 2}),
                                      ev(3, "UPDATE", payload={"value": 3})])
        self.assertEqual(self.statuses(results), [DUPLICATE, DUPLICATE, APPLIED])
        self.assertEqual(last, 3)
        self.assertEqual(self.storage.entity("e1")["data"]["value"], 3)


class GapTest(ProcessorTestCase):
    def test_gap_rejects_and_marks_rest_not_processed(self):
        self.process([ev(1)])
        results, last = self.process([ev(3, "UPDATE", payload={"value": 3}),
                                      ev(4, "UPDATE", payload={"value": 4}),
                                      ev(5, "UPDATE", payload={"value": 5})])
        self.assertEqual(self.statuses(results), [REJECTED_GAP, NOT_PROCESSED, NOT_PROCESSED])
        self.assertEqual(last, 1)
        self.assertEqual(self.storage.entity("e1")["data"]["value"], 1)
        self.assertEqual(self.storage.last_applied_seq(CLIENT), 1)

    def test_gap_in_the_middle_of_batch(self):
        results, last = self.process([ev(1), ev(2, "UPDATE", payload={"value": 2}),
                                      ev(4, "UPDATE", payload={"value": 4})])
        self.assertEqual(self.statuses(results), [APPLIED, APPLIED, REJECTED_GAP])
        self.assertEqual(last, 2)

    def test_batch_is_processed_in_seq_order(self):
        results, last = self.process([ev(2, "UPDATE", payload={"value": 2}), ev(1)])
        self.assertEqual([r["seq"] for r in results], [1, 2])
        self.assertEqual(self.statuses(results), [APPLIED, APPLIED])
        self.assertEqual(last, 2)

    def test_seq_anomaly_is_logged_and_not_applied(self):
        self.process([ev(1), ev(2, "UPDATE", payload={"value": 2})])
        results, last = self.process([ev(2, "UPDATE", payload={"value": 99}, event_id="other"),
                                      ev(3, "UPDATE", payload={"value": 3})])
        self.assertEqual(self.statuses(results), [REJECTED_GAP, NOT_PROCESSED])
        self.assertEqual(last, 2)
        self.assertEqual(self.storage.entity("e1")["data"]["value"], 2)
        self.assertEqual(len(self.anomalies), 1)
        self.assertEqual(self.anomalies[0]["type"], "SEQ_ANOMALY")


class ConflictRuleTest(ProcessorTestCase):
    def effect(self, event_id):
        return self.storage.conn.execute(
            "SELECT effect FROM applied_events WHERE event_id = ?", (event_id,)).fetchone()[0]

    def test_update_on_deleted_entity_is_ignored_but_seq_advances(self):
        self.process([ev(1), ev(2, "DELETE")])
        results, last = self.process([ev(3, "UPDATE", payload={"value": 9})])
        self.assertEqual(self.statuses(results), [APPLIED])
        self.assertEqual(last, 3)
        self.assertEqual(self.effect("ev-3"), EFFECT_IGNORED)
        entity = self.storage.entity("e1")
        self.assertEqual(entity["deleted"], 1)
        self.assertEqual(entity["data"]["value"], 1)

    def test_update_and_delete_on_missing_entity_are_ignored(self):
        results, last = self.process([ev(1, "UPDATE", "nope", {"value": 1}), ev(2, "DELETE", "nope")])
        self.assertEqual(self.statuses(results), [APPLIED, APPLIED])
        self.assertEqual(last, 2)
        self.assertEqual(self.effect("ev-1"), EFFECT_IGNORED)
        self.assertEqual(self.effect("ev-2"), EFFECT_IGNORED)
        self.assertIsNone(self.storage.entity("nope"))

    def test_create_on_existing_entity_is_full_update(self):
        self.process([ev(1)])
        self.process([ev(2, "CREATE", payload={"title": "T2", "description": "D2", "value": 2})])
        self.assertEqual(self.effect("ev-2"), EFFECT_OK)
        self.assertEqual(self.storage.entity("e1")["data"],
                         {"title": "T2", "description": "D2", "value": 2})

    def test_update_merges_delta(self):
        self.process([ev(1), ev(2, "UPDATE", payload={"title": "novo"})])
        self.assertEqual(self.storage.entity("e1")["data"],
                         {"title": "novo", "description": "d", "value": 1})


class HashTest(ProcessorTestCase):
    def test_hash_matches_reference_function(self):
        self.process([ev(1), ev(2, "UPDATE", payload={"value": 5})])
        expected = entity_hash("e1", {"title": "t", "description": "d", "value": 5}, 0)
        self.assertEqual(self.storage.entity_hashes(), {"e1": expected})

    def test_hash_is_independent_of_key_order(self):
        a = entity_hash("e", {"a": 1, "b": 2}, 0)
        b = entity_hash("e", {"b": 2, "a": 1}, False)
        self.assertEqual(a, b)
        self.assertNotEqual(a, entity_hash("e", {"a": 1, "b": 2}, 1))


class ParseBodyTest(unittest.TestCase):
    def test_rejects_invalid(self):
        for body in (b"not json", b"[]", b'{"client_id": "c"}',
                     b'{"client_id": "c", "events": [{"event_id": "x", "seq": "1"}]}'):
            with self.assertRaises(InvalidBatch):
                parse_body(body)

    def test_accepts_valid(self):
        client_id, events = parse_body(
            b'{"client_id":"c","events":[{"event_id":"x","seq":1,"entity_id":"e",'
            b'"operation":"DELETE","payload":{}}]}')
        self.assertEqual(client_id, "c")
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
