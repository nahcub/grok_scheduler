import unittest

from tte.estimate import P85_FACTOR, confidence, estimate, percentile


class PercentileTest(unittest.TestCase):
    def test_interpolates(self):
        self.assertEqual(percentile([10, 20, 30, 40, 50], 0.5), 30)
        self.assertAlmostEqual(percentile([10, 20, 30, 40, 50], 0.85), 44)

    def test_single_value(self):
        self.assertEqual(percentile([7], 0.85), 7)


class EstimateTest(unittest.TestCase):
    def test_guess_when_no_history(self):
        est = estimate(90, [], [])
        self.assertEqual(est["p50_seconds"], 90)
        self.assertEqual(est["p85_seconds"], round(90 * P85_FACTOR))
        self.assertEqual(est["basis"], {"method": "guess", "samples": 0})
        self.assertEqual(est["confidence"], "low")

    def test_calibrates_with_kind_ratios(self):
        # 그록봇이 늘 2배 길게 말했다면 추정의 절반을 낸다.
        est = estimate(600, [0.5] * 5, [1.0] * 10)
        self.assertEqual(est["p50_seconds"], 300)
        self.assertEqual(est["basis"], {"method": "calibrated", "scope": "kind",
                                        "samples": 5, "ratio": 0.5})
        self.assertEqual(est["confidence"], "medium")

    def test_p85_from_ratio_spread(self):
        est = estimate(100, [0.5, 1.0, 1.5, 2.0, 2.5], [])
        self.assertEqual(est["p50_seconds"], 150)
        self.assertEqual(est["p85_seconds"], 220)

    def test_falls_back_to_all_ratios(self):
        est = estimate(100, [2.0, 2.0], [1.5] * 6)
        self.assertEqual(est["p50_seconds"], 150)
        self.assertEqual(est["basis"]["scope"], "all")

    def test_guess_when_both_too_few(self):
        est = estimate(100, [2.0], [2.0] * 4)
        self.assertEqual(est["basis"]["method"], "guess")

    def test_never_zero(self):
        est = estimate(10, [0.0] * 5, [])
        self.assertEqual(est["p50_seconds"], 1)

    def test_confidence_levels(self):
        self.assertEqual(confidence(4), "low")
        self.assertEqual(confidence(5), "medium")
        self.assertEqual(confidence(20), "high")


if __name__ == "__main__":
    unittest.main()
