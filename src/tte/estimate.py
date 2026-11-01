"""예측 계산. 저장소에 의존하지 않는 순수 함수만 둔다.

그록봇이 직접 추정한 시간(guess)에서 출발한다. 기록이 쌓이면 "실제 ÷ 추정" 비율로
그록봇이 늘 길게 또는 짧게 말하는 버릇을 보정한다.

보정 비율은 전체 기록의 비율을 기본으로 두고, 같은 kind와 같은 추정 크기 구간의
비율을 표본 수만큼 섞는다(축소 추정). 표본이 적은 kind도 그 성향을 조금은 반영하고,
표본이 많아질수록 그 kind 자신의 비율에 가까워진다.
"""

import math

P85_FACTOR = 1.5
MIN_SAMPLES = 5
# 축소 강도. 표본이 SHRINK_K개면 그 집단 비율과 전체 비율을 반반 섞는다.
SHRINK_K = 5
# 비율 분포가 좁아도 P85가 P50보다 이만큼은 크게 한다. multi는 여러 층을 함께 바꾸는 작업.
P85_MIN_FACTOR = {"small": 1.3, "multi": 1.6}
# 추정 크기 구간(초). 작은 작업과 큰 작업은 "실제 ÷ 추정" 비율이 다르다.
SIZE_BUCKETS = (("short", 0, 120), ("mid", 120, 480), ("long", 480, math.inf))


def percentile(values, q):
    """선형 보간 백분위. q는 0~1."""
    if not values:
        raise ValueError("percentile of empty list")
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def confidence(samples):
    if samples < MIN_SAMPLES:
        return "low"
    if samples < 20:
        return "medium"
    return "high"


def size_bucket(guess):
    """(이름, 하한, 상한). 상한은 포함하지 않는다."""
    for bucket in SIZE_BUCKETS:
        if bucket[1] <= guess < bucket[2]:
            return bucket
    return SIZE_BUCKETS[-1]


def shrink_weight(n):
    return n / (n + SHRINK_K)


def blend(values, q, prior):
    """values의 q 백분위를 표본 수에 따라 prior 쪽으로 당긴다."""
    if not values:
        return prior
    w = shrink_weight(len(values))
    return w * percentile(values, q) + (1 - w) * prior


def estimate(guess, kind_ratios, all_ratios, size_ratios=(), scope="small", bucket="mid"):
    """kind_ratios ⊂ all_ratios, size_ratios ⊂ all_ratios (같은 추정 크기 구간)."""
    floor = P85_MIN_FACTOR[scope]
    if len(all_ratios) < MIN_SAMPLES:
        return {
            "p50_seconds": guess,
            "p85_seconds": round(guess * max(P85_FACTOR, floor)),
            "basis": {"method": "guess", "samples": 0},
            "confidence": "low",
        }
    rates = {}
    for q in (0.5, 0.85):
        base = percentile(all_ratios, q)
        kind_rate = blend(kind_ratios, q, base)
        size_rate = blend(size_ratios, q, base)
        # kind 보정과 크기 보정을 각각 전체 대비 배수로 보고 곱한다.
        rates[q] = kind_rate * size_rate / base if base > 0 else kind_rate
    p50 = max(1, round(guess * rates[0.5]))
    p85 = max(1, round(guess * rates[0.85]), round(p50 * floor))
    return {
        "p50_seconds": p50,
        "p85_seconds": p85,
        "basis": {
            "method": "calibrated",
            "scope": "blend",
            "samples": len(all_ratios),
            "ratio": round(rates[0.5], 2),
            "kind_samples": len(kind_ratios),
            "all_samples": len(all_ratios),
            "kind_weight": round(shrink_weight(len(kind_ratios)), 2),
            "size_bucket": bucket,
            "size_samples": len(size_ratios),
            "size_weight": round(shrink_weight(len(size_ratios)), 2),
        },
        "confidence": confidence(len(all_ratios)),
    }
