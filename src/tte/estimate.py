"""예측 계산. 저장소에 의존하지 않는 순수 함수만 둔다."""

import math

# 기록이 부족할 때 쓰는 복잡도별 P50(초). 임시값이며 실제 사용 기록으로 고친다.
RULE_P50 = {"light": 180, "medium": 600, "heavy": 1500}
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


def estimate(complexity, same_kind, same_complexity):
    """같은 (kind, complexity) 기록 → 같은 complexity 기록 → 규칙 순으로 대체한다."""
    for scope, values in (("kind", same_kind), ("complexity", same_complexity)):
        if len(values) >= MIN_SAMPLES:
            return {
                "p50_seconds": round(percentile(values, 0.5)),
                "p85_seconds": round(percentile(values, 0.85)),
                "basis": {"method": "history", "scope": scope, "samples": len(values)},
                "confidence": confidence(len(values)),
            }
    p50 = RULE_P50[complexity]
    return {
        "p50_seconds": p50,
        "p85_seconds": round(p50 * P85_FACTOR),
        "basis": {"method": "rule", "samples": 0},
        "confidence": "low",
    }
