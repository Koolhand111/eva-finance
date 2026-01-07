import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor


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
    # Hard gates (discipline)
    if intent < 0.65:
        return {"band": "SUPPRESSED", "reason": "GATE_INTENT_LT_0.65", "final": 0.0}
    if suppression < 0.50:
        return {"band": "SUPPRESSED", "reason": "GATE_SUPPRESSION_LT_0.50", "final": 0.0}
    if spread < 0.50:
        return {"band": "SUPPRESSED", "reason": "GATE_SPREAD_LT_0.50", "final": 0.0}

    final = (
        intent * 0.30 +
        accel * 0.20 +
        spread * 0.20 +
        baseline * 0.15 +
        suppression * 0.15
    )

    band = "HIGH" if final >= 0.80 else ("WATCHLIST" if final >= 0.65 else "SUPPRESSED")
    return {"band": band, "reason": None, "final": float(round(final, 4))}


def main():
    db_url = os.environ.get("DATABASE_URL") or "postgres://eva:eva_password_change_me@db:5432/eva_finance"

    conn = psycopg2.connect(db_url)
    conn.autocommit = True

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Score "today" candidates (matches your view output day=current_date)
        cur.execute("""
            SELECT *
            FROM public.v_eva_candidate_brand_signals_v1
            WHERE day = current_date
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
