import unittest

from tte.estimate import P85_FACTOR, RULE_P50, confidence, estimate, percentile


class PercentileTest(unittest.TestCase):
    def test_interpolates(self):
        self.assertEqual(percentile([10, 20, 30, 40, 50], 0.5), 30)
        self.assertAlmostEqual(percentile([10, 20, 30, 40, 50], 0.85), 44)

    def test_single_value(self):
        self.assertEqual(percentile([7], 0.85), 7)


class EstimateTest(unittest.TestCase):
    def test_rule_when_no_history(self):
        est = estimate("heavy", [], [])
        self.assertEqual(est["p50_seconds"], RULE_P50["heavy"])
        self.assertEqual(est["p85_seconds"], round(RULE_P50["heavy"] * P85_FACTOR))
        self.assertEqual(est["basis"], {"method": "rule", "samples": 0})
        self.assertEqual(est["confidence"], "low")

    def test_kind_history_first(self):
        est = estimate("medium", [100, 200, 300, 400, 500], [1000] * 10)
        self.assertEqual(est["p50_seconds"], 300)
        self.assertEqual(est["basis"]["scope"], "kind")
        self.assertEqual(est["basis"]["samples"], 5)

    def test_falls_back_to_complexity(self):
        est = estimate("medium", [100, 200], [100, 200, 300, 400, 500, 600])
        self.assertEqual(est["basis"]["scope"], "complexity")
        self.assertEqual(est["basis"]["samples"], 6)

    def test_rule_when_both_too_few(self):
        est = estimate("light", [1, 2], [1, 2, 3, 4])
        self.assertEqual(est["basis"]["method"], "rule")

    def test_confidence_levels(self):
        self.assertEqual(confidence(4), "low")
        self.assertEqual(confidence(5), "medium")
        self.assertEqual(confidence(20), "high")


if __name__ == "__main__":
    unittest.main()
