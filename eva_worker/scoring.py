import math
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class ScoreWeights:
    # core
    magnitude_alpha: float = 1.0     # log scaling strength
    freshness_boost: float = 0.60    # how much "today" can amplify
    persistence_min_days: int = 2
    persistence_max_days: int = 5
    persistence_floor: float = 0.60  # minimum persistence factor
    persistence_ceil: float = 1.15   # max persistence factor


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def compute_persistence_factor(days_present: int, w: ScoreWeights) -> float:
    # maps days_present into [floor..ceil]
    d = clamp(days_present, w.persistence_min_days, w.persistence_max_days)
    t = (d - w.persistence_min_days) / max(1, (w.persistence_max_days - w.persistence_min_days))
    return w.persistence_floor + t * (w.persistence_ceil - w.persistence_floor)

 def score_brand_signal(flow_24h: float, flow_today: float, days_present: int) -> Dict[str, Any]:
    return score_from_flow(flow_24h=flow_24h, flow_today=flow_today, days_present=days_present)
   


def score_from_flow(
    flow_24h: float,
    flow_today: float,
    days_present: int,
    w: ScoreWeights = ScoreWeights(),
) -> Dict[str, Any]:
    """
    Returns { score, components } where score is signed (+/-).
    """

    # 1) magnitude (signed, log-scaled)
    mag = math.log1p(abs(flow_24h)) * w.magnitude_alpha
    base = sign(flow_24h) * mag

    # 2) freshness (boost based on how much of 24h is "today")
    denom = max(abs(flow_24h), 1e-6)
    freshness_ratio = (flow_today / denom) if denom else 0.0
    freshness_factor = 1.0 + clamp(freshness_ratio, -1.0, 1.0) * w.freshness_boost

    # 3) persistence (punish 1-day wonders)
    persistence_factor = compute_persistence_factor(days_present, w)

    final = base * freshness_factor * persistence_factor


    return {
        "score": float(final),
        "components": {
            "flow_24h": float(flow_24h),
            "flow_today": float(flow_today),
            "days_present": int(days_present),
            "magnitude": float(mag),
            "freshness_ratio": float(freshness_ratio),
            "freshness_factor": float(freshness_factor),
            "persistence_factor": float(persistence_factor),
            "base": float(base),
        }
    }