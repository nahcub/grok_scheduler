import unittest

from tte.estimate import (P85_FACTOR, P85_MIN_FACTOR, SHRINK_K, confidence, estimate,
                          percentile, size_bucket)


class PercentileTest(unittest.TestCase):
    def test_interpolates(self):
        self.assertEqual(percentile([10, 20, 30, 40, 50], 0.5), 30)
        self.assertAlmostEqual(percentile([10, 20, 30, 40, 50], 0.85), 44)

    def test_single_value(self):
        self.assertEqual(percentile([7], 0.85), 7)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            percentile([], 0.5)


class EstimateTest(unittest.TestCase):
    def test_guess_when_no_history(self):
        est = estimate(90, [], [])
        self.assertEqual(est["p50_seconds"], 90)
        self.assertEqual(est["p85_seconds"], round(90 * P85_FACTOR))
        self.assertEqual(est["basis"], {"method": "guess", "samples": 0})
        self.assertEqual(est["confidence"], "low")

    def test_guess_when_all_too_few(self):
        self.assertEqual(estimate(100, [2.0] * 4, [2.0] * 4)["basis"]["method"], "guess")

    def test_uniform_history_scales_guess(self):
        # 그록봇이 늘 2배 길게 말했다면 추정의 절반을 낸다.
        est = estimate(600, [0.5] * 5, [0.5] * 10, [0.5] * 10)
        self.assertEqual(est["p50_seconds"], 300)
        self.assertEqual(est["basis"]["method"], "calibrated")
        self.assertEqual(est["basis"]["scope"], "blend")
        self.assertEqual(est["basis"]["ratio"], 0.5)
        self.assertEqual(est["confidence"], "medium")

    def test_small_kind_is_blended_not_dropped(self):
        # browser 3건(비율 0.15), 전체 30건(비율 0.08)
        all_ratios = [0.08] * 27 + [0.15] * 3
        few = estimate(1000, [0.15] * 3, all_ratios)
        r_few = few["p50_seconds"] / 1000
        self.assertGreater(r_few, 0.08)
        self.assertLess(r_few, 0.15)
        self.assertEqual(few["basis"]["kind_samples"], 3)
        self.assertEqual(few["basis"]["all_samples"], 30)
        self.assertEqual(few["basis"]["kind_weight"], round(3 / (3 + SHRINK_K), 2))
        # 같은 kind 표본이 늘면 0.15에 가까워진다.
        many = estimate(1000, [0.15] * 30, [0.08] * 27 + [0.15] * 30)
        r_many = many["p50_seconds"] / 1000
        self.assertGreater(r_many, r_few)
        self.assertLess(abs(r_many - 0.15), abs(r_few - 0.15))

    def test_no_kind_history_uses_all(self):
        est = estimate(1000, [], [0.1] * 10)
        self.assertEqual(est["p50_seconds"], 100)
        self.assertEqual(est["basis"]["kind_weight"], 0)

    def test_size_bucket_shifts_estimate(self):
        # 큰 작업 구간은 비율이 더 크다(짧게 추정하는 경향).
        all_ratios = [0.1] * 20 + [0.3] * 10
        plain = estimate(600, [], all_ratios, [])
        large = estimate(600, [], all_ratios, [0.3] * 10, bucket="long")
        self.assertGreater(large["p50_seconds"], plain["p50_seconds"])
        self.assertEqual(large["basis"]["size_bucket"], "long")
        self.assertEqual(large["basis"]["size_samples"], 10)

    def test_size_buckets(self):
        self.assertEqual(size_bucket(30)[0], "short")
        self.assertEqual(size_bucket(120)[0], "mid")
        self.assertEqual(size_bucket(479)[0], "mid")
        self.assertEqual(size_bucket(480)[0], "long")

    def test_p85_floor_when_spread_is_narrow(self):
        est = estimate(1000, [], [0.1] * 10)
        self.assertEqual(est["p85_seconds"], round(100 * P85_MIN_FACTOR["small"]))

    def test_multi_scope_has_more_margin(self):
        small = estimate(1000, [], [0.1] * 10)
        multi = estimate(1000, [], [0.1] * 10, scope="multi")
        self.assertEqual(multi["p50_seconds"], small["p50_seconds"])
        self.assertEqual(multi["p85_seconds"], round(100 * P85_MIN_FACTOR["multi"]))
        self.assertGreater(estimate(100, [], [], scope="multi")["p85_seconds"],
                           estimate(100, [], [])["p85_seconds"])

    def test_never_zero(self):
        est = estimate(10, [0.0] * 5, [0.0] * 5)
        self.assertEqual(est["p50_seconds"], 1)
        self.assertGreaterEqual(est["p85_seconds"], 1)

    def test_confidence_levels(self):
        self.assertEqual(confidence(4), "low")
        self.assertEqual(confidence(5), "medium")
        self.assertEqual(confidence(20), "high")


if __name__ == "__main__":
    unittest.main()
