import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics import c3, c4, d3_values, queue_series, t_ref_ns  # noqa: E402
from stats import holm  # noqa: E402


class HolmTest(unittest.TestCase):
    def test_hand_example(self):
        # p = [0,01; 0,04; 0,03; 0,005], m = 4. Ordenados: 0,005 · 0,01 · 0,03 · 0,04
        #   0,005 × 4 = 0,02
        #   0,01  × 3 = 0,03
        #   0,03  × 2 = 0,06
        #   0,04  × 1 = 0,04 → monotonicidade: max(0,06; 0,04) = 0,06
        adjusted = holm([0.01, 0.04, 0.03, 0.005])
        for got, expected in zip(adjusted, [0.03, 0.06, 0.06, 0.02]):
            self.assertAlmostEqual(got, expected)

    def test_caps_at_one_and_keeps_ties(self):
        self.assertEqual(holm([0.5, 0.5, 0.9]), [1.0, 1.0, 1.0])
        self.assertEqual(holm([]), [])


# Eventos no formato da consulta de metrics.load_run: (event_id, seq, created, acked, attempts, bytes)
def evs(*pairs):
    return [(f"e{i}", i + 1, c, a, 1, 10) for i, (c, a) in enumerate(pairs)]


class MetricHelpersTest(unittest.TestCase):
    def test_queue_series_max(self):
        series = queue_series(evs((0, 5), (1, 6), (2, 3), (10, 11)))
        self.assertEqual(max(s for _, s in series), 3)
        self.assertEqual(series[-1][1], 0)

    def test_queue_series_ack_before_create_on_tie(self):
        series = queue_series(evs((0, 5), (5, 6)))
        self.assertEqual(max(s for _, s in series), 1)

    def test_c3(self):
        self.assertEqual(c3([("a", 1, 0, ""), ("b", 2, 0, ""), ("c", 3, 0, "")]), 0)
        self.assertEqual(c3([("a", 2, 0, ""), ("b", 3, 0, "")]), 1)
        self.assertEqual(c3([("a", 1, 0, ""), ("b", 3, 0, ""), ("c", 2, 0, "")]), 2)

    def test_c4(self):
        self.assertEqual(c4({"a": "1", "b": "2"}, {"a": "1", "b": "2"}), 0)
        self.assertEqual(c4({"a": "1", "b": "2"}, {"a": "x", "c": "3"}), 3)

    def test_d3_and_t_ref(self):
        run = {
            "events": evs((0, 50), (1, 60)),
            "requests": [{"outcome": "timeout", "finished_at_ns": 25},
                         {"outcome": "ok", "finished_at_ns": 32},
                         {"outcome": "ok", "finished_at_ns": 60}],
            "network": [{"label": "initial", "t_applied_ns": -1},
                        {"label": "restore", "t_applied_ns": 30},
                        {"label": "final", "t_applied_ns": 70}],
        }
        self.assertEqual(d3_values(run), [2 / 1e9])
        self.assertEqual(t_ref_ns(run), 30)

    def test_d3_skips_restoration_with_empty_queue(self):
        run = {"events": evs((0, 5)), "requests": [{"outcome": "ok", "finished_at_ns": 5}],
               "network": [{"label": "online", "t_applied_ns": 10}]}
        self.assertEqual(d3_values(run), [])


if __name__ == "__main__":
    unittest.main()
