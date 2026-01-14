import os
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

# Google Trends cross-validation
try:
    from eva_worker.google_trends import GoogleTrendsValidator
    TRENDS_AVAILABLE = True
except ImportError:
    TRENDS_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def map_delta_pct_to_accel(delta_pct: float) -> float:
    # Conservative mapping of share-of-voice delta (%) to 0..1
    if delta_pct is None:
        return 0.0
    if delta_pct <= 0:
        return 0.20
    if delta_pct >= 2.0:
        return 0.95
    return clamp(0.20 + (delta_pct / 2.0) * 0.75)


def is_watchlist_warm(accel: float, intent: float, spread: float) -> tuple[bool, str]:
    """
    Conservative 'warming up' detector.
    We only emit a WATCHLIST event when at least one dimension is meaningfully strong.
    """
    if spread >= 0.60:
        return True, "WARM_SPREAD_GE_0.60"
    if accel >= 0.85:
        return True, "WARM_ACCEL_GE_0.85"
    if intent >= 0.45:
        return True, "WARM_INTENT_GE_0.45"
    return False, ""


def map_action_intent_to_intent(action_intent_rate: float) -> float:
    r = 0.0 if action_intent_rate is None else float(action_intent_rate)
    if r <= 0.00:
        return 0.20
    if r >= 0.50:
        return 0.95
    if r <= 0.20:
        return clamp(0.20 + (r / 0.20) * 0.45)  # 0.20 -> 0.65
    return clamp(0.65 + ((r - 0.20) / 0.30) * 0.30)  # 0.50 -> 0.95


def map_suppression(meme_risk: float) -> float:
    risk = clamp(0.0 if meme_risk is None else float(meme_risk))
    return clamp(1.0 - risk)


def baseline_score_from_msg_count(msg_count: int) -> float:
    n = 0 if msg_count is None else int(msg_count)
    if n <= 1:
        return 0.20
    if n >= 20:
        return 0.95
    return clamp(0.20 + (n / 20.0) * 0.75)


def eva_v1_final(accel, intent, spread, baseline, suppression) -> dict:
    # Adaptive thresholds for Phase 0 (early-stage data)
    # Production thresholds will be raised after 30+ days and 20+ subreddits
    INTENT_THRESHOLD = float(os.getenv("EVA_GATE_INTENT", "0.50"))  # Lowered from 0.65
    SUPPRESSION_THRESHOLD = float(os.getenv("EVA_GATE_SUPPRESSION", "0.40"))  # Lowered from 0.50
    SPREAD_THRESHOLD = float(os.getenv("EVA_GATE_SPREAD", "0.25"))  # Lowered from 0.50 for early data

    # Hard gates (discipline)
    if intent < INTENT_THRESHOLD:
        return {"band": "SUPPRESSED", "reason": f"GATE_INTENT_LT_{INTENT_THRESHOLD}", "final": 0.0}
    if suppression < SUPPRESSION_THRESHOLD:
        return {"band": "SUPPRESSED", "reason": f"GATE_SUPPRESSION_LT_{SUPPRESSION_THRESHOLD}", "final": 0.0}
    if spread < SPREAD_THRESHOLD:
        return {"band": "SUPPRESSED", "reason": f"GATE_SPREAD_LT_{SPREAD_THRESHOLD}", "final": 0.0}

    final = (
        intent * 0.30 +
        accel * 0.20 +
        spread * 0.20 +
        baseline * 0.15 +
        suppression * 0.15
    )

    # Adaptive band thresholds for Phase 0
    HIGH_THRESHOLD = float(os.getenv("EVA_BAND_HIGH", "0.60"))  # Lowered from 0.80
    WATCHLIST_THRESHOLD = float(os.getenv("EVA_BAND_WATCHLIST", "0.50"))  # Lowered from 0.65

    band = "HIGH" if final >= HIGH_THRESHOLD else ("WATCHLIST" if final >= WATCHLIST_THRESHOLD else "SUPPRESSED")
    return {"band": band, "reason": None, "final": float(round(final, 4))}


def main():
    db_url = os.environ.get("DATABASE_URL") or "postgres://eva:eva_password_change_me@db:5432/eva_finance"

    conn = psycopg2.connect(db_url)
    conn.autocommit = True

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Score recent candidates (Phase 0: include last 7 days for validation)
        cur.execute("""
            SELECT *
            FROM public.v_eva_candidate_brand_signals_v1
            WHERE day >= current_date - INTERVAL '7 days'
        """)
        rows = cur.fetchall()

    if not rows:
        print("No candidates for today in v_eva_candidate_brand_signals_v1.")
        return

    with conn.cursor() as cur:
        for r in rows:
            day = r["day"]
            tag = r["tag"]
            brand = r["brand"]

            # Skip candidates with NULL or empty brand/tag (not actionable for recommendations)
            if brand is None or brand == '' or tag is None or tag == '':
                continue

            delta_pct = float(r["delta_pct"])
            msg_count = int(r["msg_count"])
            source_count = int(r["source_count"])
            platform_count = int(r["platform_count"])

            accel = map_delta_pct_to_accel(delta_pct)
            intent = map_action_intent_to_intent(r["action_intent_rate"])

            # ✅ Upgraded spread logic (still conservative)
            spread_raw = max(
                (source_count - 1) / 3.0,
                (platform_count - 1) / 3.0
            )
            spread = clamp(spread_raw)

            suppression = map_suppression(r["meme_risk"])
            baseline = baseline_score_from_msg_count(msg_count)

            result = eva_v1_final(accel, intent, spread, baseline, suppression)
            band = result["band"]
            gate_reason = result["reason"]
            final = result["final"]

            # Google Trends cross-validation (only for high-confidence signals)
            base_confidence = final  # Store original before adjustment
            trends_validated = False
            trends_data = None

            TRENDS_ENABLED = os.getenv("GOOGLE_TRENDS_ENABLED", "true").lower() == "true"
            TRENDS_MIN_CONFIDENCE = float(os.getenv("GOOGLE_TRENDS_MIN_CONFIDENCE", "0.60"))

            if TRENDS_AVAILABLE and TRENDS_ENABLED and band == "HIGH" and final >= TRENDS_MIN_CONFIDENCE:
                try:
                    logger.info(f"[TRENDS-VALIDATION] Checking Google Trends for {brand} (confidence={final:.4f})")

                    # Initialize validator (cached for efficiency)
                    if not hasattr(main, '_trends_validator'):
                        cache_hours = int(os.getenv("GOOGLE_TRENDS_CACHE_HOURS", "24"))
                        main._trends_validator = GoogleTrendsValidator(cache_ttl_hours=cache_hours)

                    validator = main._trends_validator
                    trends_result = validator.validate_brand_signal(brand)

                    trends_validated = trends_result['validates_signal']
                    confidence_boost = trends_result['confidence_boost']

                    # Apply boost/penalty to final confidence
                    final = clamp(final + confidence_boost)

                    # Store validation in database
                    cur.execute("""
                        INSERT INTO google_trends_validation (
                            brand, checked_at, search_interest, trend_direction,
                            validates_signal, confidence_boost, query_term, timeframe,
                            raw_data, error_message
                        )
                        VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    """, (
                        brand,
                        trends_result['search_interest'],
                        trends_result['trend_direction'],
                        trends_result['validates_signal'],
                        confidence_boost,
                        trends_result['query_term'],
                        trends_result['timeframe'],
                        json.dumps(trends_result['raw_data']) if trends_result['raw_data'] else None,
                        trends_result['error_message']
                    ))

                    trends_data = {
                        'validates_signal': trends_validated,
                        'search_interest': float(trends_result['search_interest']),
                        'trend_direction': trends_result['trend_direction'],
                        'confidence_boost': float(confidence_boost),
                        'base_confidence': float(base_confidence),
                        'adjusted_confidence': float(final)
                    }

                    logger.info(
                        f"[TRENDS-VALIDATION] ✓ {brand}: validates={trends_validated}, "
                        f"direction={trends_result['trend_direction']}, "
                        f"boost={confidence_boost:+.4f}, "
                        f"final={base_confidence:.4f} → {final:.4f}"
                    )

                    # Re-evaluate band after adjustment
                    if final >= 0.80:
                        band = "HIGH"
                    elif final >= 0.65:
                        band = "WATCHLIST"
                    else:
                        band = "SUPPRESSED"
                        gate_reason = "TRENDS_PENALTY_BELOW_THRESHOLD"

                except Exception as e:
                    logger.error(f"[TRENDS-VALIDATION] ✗ Failed for {brand}: {e}")
                    # Continue with original confidence on error (conservative)

            # Emit WATCHLIST breadcrumbs for "warming up" signals
            warm, warm_reason = is_watchlist_warm(accel, intent, spread)
            if band != "HIGH" and warm:
                cur.execute("""
                    INSERT INTO public.signal_events (event_type, tag, brand, day, severity, payload)
                    VALUES ('WATCHLIST_WARM', %s, %s, %s, 'warning',
                            jsonb_build_object(
                                'reason', %s,
                                'band', %s,
                                'gate_failed_reason', %s,
                                'final_confidence', %s,
                                'scores', jsonb_build_object(
                                    'acceleration', %s,
                                    'intent', %s,
                                    'spread', %s
                                ),
                                'scoring_version', 'v1'
                            ))
                    ON CONFLICT DO NOTHING;
                """, (
                    tag, brand, day,
                    warm_reason, band, gate_reason, final,
                    accel, intent, spread
                ))

            details = {
                "inputs": {
                    "delta_pct": delta_pct,
                    "msg_count": msg_count,
                    "source_count": source_count,
                    "platform_count": platform_count,
                    "action_intent_rate": float(r["action_intent_rate"]),
                    "eval_intent_rate": float(r["eval_intent_rate"]),
                    "meme_risk": float(r["meme_risk"]),
                    "spread_raw": float(spread_raw),
                },
                "scores": {
                    "acceleration": accel,
                    "intent": intent,
                    "spread": spread,
                    "baseline": baseline,
                    "suppression": suppression,
                },
                "google_trends": trends_data  # Include trends validation data
            }

            cur.execute("""
                INSERT INTO public.eva_confidence_v1 (
                    day, tag, brand,
                    acceleration_score, intent_score, spread_score, baseline_score, suppression_score,
                    final_confidence, band, gate_failed_reason, scoring_version, details
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'v1',%s::jsonb)
                ON CONFLICT (day, tag, brand, scoring_version)
                DO UPDATE SET
                    acceleration_score = EXCLUDED.acceleration_score,
                    intent_score = EXCLUDED.intent_score,
                    spread_score = EXCLUDED.spread_score,
                    baseline_score = EXCLUDED.baseline_score,
                    suppression_score = EXCLUDED.suppression_score,
                    final_confidence = EXCLUDED.final_confidence,
                    band = EXCLUDED.band,
                    gate_failed_reason = EXCLUDED.gate_failed_reason,
                    details = EXCLUDED.details,
                    computed_at = now();
            """, (
                day, tag, brand,
                accel, intent, spread, baseline, suppression,
                final, band, gate_reason, json.dumps(details)
            ))

            # Emit only when HIGH (low frequency)
            if band == "HIGH":
                cur.execute("""
                    INSERT INTO public.signal_events (event_type, tag, brand, day, severity, payload)
                    VALUES ('RECOMMENDATION_ELIGIBLE', %s, %s, %s, 'critical',
                            jsonb_build_object('final_confidence', %s, 'scoring_version', 'v1'))
                    ON CONFLICT DO NOTHING;
                """, (tag, brand, day, final))

    print(f"Scored {len(rows)} candidate(s) into eva_confidence_v1.")


if __name__ == "__main__":
    main()
