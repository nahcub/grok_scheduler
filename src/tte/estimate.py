"""예측 계산. 저장소에 의존하지 않는 순수 함수만 둔다.

그록봇이 직접 추정한 시간(guess)에서 출발한다. 기록이 쌓이면 "실제 ÷ 추정" 비율로
그록봇이 늘 길게 또는 짧게 말하는 버릇을 보정한다.
"""

import math

P85_FACTOR = 1.5
MIN_SAMPLES = 5


def percentile(values, q):
    """선형 보간 백분위. q는 0~1."""
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


def estimate(guess, same_kind_ratios, all_ratios):
    """같은 kind의 비율 → 전체 비율 → 그록봇 추정 그대로 순으로 대체한다."""
    for scope, ratios in (("kind", same_kind_ratios), ("all", all_ratios)):
        if len(ratios) >= MIN_SAMPLES:
            r50, r85 = percentile(ratios, 0.5), percentile(ratios, 0.85)
            return {
                "p50_seconds": max(1, round(guess * r50)),
                "p85_seconds": max(1, round(guess * r85)),
                "basis": {"method": "calibrated", "scope": scope,
                          "samples": len(ratios), "ratio": round(r50, 2)},
                "confidence": confidence(len(ratios)),
            }
    return {
        "p50_seconds": guess,
        "p85_seconds": round(guess * P85_FACTOR),
        "basis": {"method": "guess", "samples": 0},
        "confidence": "low",
    }
