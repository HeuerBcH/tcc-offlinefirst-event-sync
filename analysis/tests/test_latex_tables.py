import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from latex_tables import cell, fmt_num  # noqa: E402


class LatexTablesTest(unittest.TestCase):
    def test_pt_br_number_format(self):
        self.assertEqual(fmt_num(1649.4, 0), "1.649")
        self.assertEqual(fmt_num(21.66, 1), "21,7")
        self.assertEqual(fmt_num(math.nan, 1), "--")

    def test_cell_mean_min_max(self):
        self.assertEqual(cell([20.1, 22.5, 22.5]), "21,7 (20,1--22,5)")
        self.assertEqual(cell([1000.0, 1000.0, 1000.0], integer=True), "1.000")
        self.assertEqual(cell([7.0, 7.0, 8.0], integer=True), "7,3 (7--8)")
        self.assertEqual(cell([math.nan, math.nan]), "--")


if __name__ == "__main__":
    unittest.main()
