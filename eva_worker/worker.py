import os
import time
import json
import logging
import psycopg2
from openai import OpenAI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Import notification polling
try:
    from eva_worker.notify import poll_and_notify
except ImportError:
    logger.warning("Could not import poll_and_notify - notification polling disabled")
    poll_and_notify = None

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgres://eva:eva_password_change_me@db:5432/eva_finance",
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

MODEL_NAME = os.getenv("EVA_MODEL", "gpt-4o-mini")
PROCESSOR_LLM = f"llm:{MODEL_NAME}:v1"
PROCESSOR_FALLBACK = "fallback:v1"

# Notification polling interval (seconds)
NOTIFICATION_POLL_INTERVAL = int(os.getenv("NOTIFICATION_POLL_INTERVAL", "60"))

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def emit_trigger_events():
    """
    Emit signal events based on trigger views.
    Uses a UNIQUE index on signal_events to prevent duplicates.
    """
    conn = get_conn()
    cur = conn.cursor()

    # ---- Trigger A: Tag Elevated (fires as soon as behavior_states has ELEVATED tags) ----
    cur.execute("""
        SELECT tag, day, confidence
        FROM v_trigger_tag_elevated
        ORDER BY day DESC;
    """)
    elevated = cur.fetchall()

    for tag, day, confidence in elevated:
        cur.execute("""
            INSERT INTO signal_events (event_type, tag, day, severity, payload)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT DO NOTHING;
        """, (
            "TAG_ELEVATED",
            tag,
            day,
            "warning",
            json.dumps({"confidence": float(confidence)})
        ))

    # ---- Trigger B: Brand Divergence (may be empty until you have multi-day share movement) ----
    cur.execute("""
        SELECT tag_name, brand_name, day, delta_pct
        FROM v_trigger_brand_divergence
        ORDER BY day DESC;
    """)
    divergence = cur.fetchall()

    for tag_name, brand_name, day, delta_pct in divergence:
        cur.execute("""
            INSERT INTO signal_events (event_type, tag, brand, day, severity, payload)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT DO NOTHING;
        """, (
            "BRAND_DIVERGENCE",
            tag_name,
            brand_name,
            day,
            "warning",
            json.dumps({"delta_pct": float(delta_pct)})
        ))

    conn.commit()
    cur.close()
    conn.close()




def get_conn():
    return psycopg2.connect(DATABASE_URL)


def fallback_brain_extract(raw_id: int, text: str):
    """
    Minimal, brand-agnostic fallback extractor.

    Purpose:
      - Never block the pipeline
      - Preserve behavioral intent and basic tags
      - Avoid hardcoded brands, products, or tickers
    """
    text_lower = (text or "").lower()

    brand = []
    product = []
    category = []
    tickers = []
    tags = []
    sentiment = "neutral"
    intent = "none"

    # --- Basic tags ---
    if any(w in text_lower for w in ["run", "running", "runner"]):
        tags.append("running")

    if "comfort" in text_lower or "comfortable" in text_lower:
        tags.append("comfort")

    if any(w in text_lower for w in ["switching", "switched", "done with", "never going back"]):
        tags.append("brand-switch")
        intent = "own"

    # --- Sentiment ---
    if any(w in text_lower for w in ["love", "amazing", "insane", "way better", "never going back"]):
        sentiment = "strong_positive"
    elif any(w in text_lower for w in ["hate", "terrible", "awful", "never again"]):
        sentiment = "strong_negative"

    # --- Recommendation intent ---
    if any(w in text_lower for w in ["you should", "highly recommend", "must try"]):
        intent = "recommendation"
        if sentiment == "neutral":
            sentiment = "positive"

    return {
        "raw_id": raw_id,
        "brand": brand,
        "product": product,
        "category": category,
        "sentiment": sentiment,
        "intent": intent,
        "tickers": tickers,
        "tags": tags,
        "processor_version": PROCESSOR_FALLBACK,
    }

def brain_extract(raw_id: int, text: str):
    if client is None:
        return fallback_brain_extract(raw_id, text)

    system_prompt = """
You are the EVA-Finance conversational data analyzer.

Extract structured information from ONE short post/comment.

Return ONLY valid JSON with ALL keys present:

{
  "brand": [...],
  "product": [...],
  "category": [...],
  "sentiment": "strong_positive|positive|neutral|negative|strong_negative",
  "intent": "buy|own|recommendation|complaint|none",
  "tickers": [...],
  "tags": [...]
}

Rules:
- brand: include ALL brands explicitly mentioned (e.g., "Nike" and "Hoka" if both appear).
- sentiment: do NOT use "neutral" if the text clearly expresses preference, excitement, hate, or switching.
- intent: choose "own" if the user is describing their usage/switching; "recommendation" only if they advise others.
- tags: include 2–5 useful tags when there is signal; include "brand-switch" for switching text;
  include "running" for running context; include "comfort-shoes" if comfort is mentioned.
Output JSON only. No markdown. No extra fields.
"""

    user_prompt = f"Text:\n{text}\n\nReturn JSON only."

    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = resp.choices[0].message.content
        data = json.loads(content)

        brand = data.get("brand") or []
        product = data.get("product") or []
        category = data.get("category") or []
        sentiment = data.get("sentiment") or "neutral"
        intent = data.get("intent") or "none"
        tickers = data.get("tickers") or []
        tags = data.get("tags") or []

        

        # -----------------------------
        # Brand-agnostic heuristic layer
        # -----------------------------
        text_lower = (text or "").lower()

        def ensure(lst, value):
            if value not in lst:
                lst.append(value)    

        # Context tags
        if any(w in text_lower for w in ["run", "running", "runner"]):
            ensure(tags, "running")
        

        # Track comfort generically; only escalate to comfort-shoes if footwear context exists
        if any(w in text_lower for w in ["comfort", "comfortable"]):
            ensure(tags, "comfort")
            if "running" in tags or any(w in text_lower for w in ["shoe", "shoes", "sneaker", "sneakers"]):
                ensure(tags, "comfort-shoes")

        # Switch / comparative signals (tight, not "going to", not "over")
        switch_signals = [
            "switching from", "switched from", "moving from",
            "done with", "never going back", "i'm done with", "im done with",
            "ditching", "replacing"
        ]

        comparative_signals = [
            "better than", "worse than",
            "more comfortable than", "less comfortable than",
            "not even close", "beats", "crushes", "smokes", "blows"
        ]

        strong_pos_signals = ["love", "amazing", "insane", "never going back", "so much better", "obsessed"]
        strong_neg_signals = ["hate", "trash", "awful", "terrible", "never again", "done with"]

        is_switchy = any(s in text_lower for s in switch_signals)
        is_comparative = any(s in text_lower for s in comparative_signals)

        # If we have >=2 brands and switch/comparison language, enforce contract
        if len(brand) >= 2 and (is_switchy or is_comparative):
            ensure(tags, "brand-switch")
            intent = "own"  # switching implies personal use

        # Don't allow neutral if it's clearly comparative/switchy
        if sentiment == "neutral" and (is_switchy or is_comparative):
            if any(s in text_lower for s in strong_neg_signals):
                sentiment = "strong_negative"
            elif any(s in text_lower for s in strong_pos_signals):
                sentiment = "strong_positive"
            else:
                sentiment = "positive"

        # If brand-switch exists for any reason, intent shouldn't be none
        if "brand-switch" in tags and (intent in ("none", None, "")):
            intent = "own"

        # Category nudges only when context supports it
        if "running" in tags:
            ensure(category, "Footwear")
            ensure(category, "Running Shoes")

        # Optional: enforce tag count
        if len(tags) > 5:
            tags = tags[:5]

        # Normalize overlapping comfort tags
        if "comfort" in tags and "comfort-shoes" in tags:
            tags = [t for t in tags if t != "comfort"]   

        # Final intent normalization (authoritative)
        if "brand-switch" in tags and intent in (None, "", "none"):
            intent = "own"

         
        if "brand-switch" in tags and sentiment == "neutral":
            sentiment = "positive"   

        return {
            "raw_id": raw_id,
            "brand": brand,
            "product": product,
            "category": category,
            "sentiment": sentiment,
            "intent": intent,
            "tickers": tickers,
            "tags": tags,
            "processor_version": PROCESSOR_LLM,
        }

    except Exception as e:
        print(f"[EVA-WORKER] LLM extraction failed for raw_id={raw_id}: {e}")
        return fallback_brain_extract(raw_id, text)


def process_batch(limit: int = 20) -> int:
    # 1) Fetch unprocessed rows
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, text
        FROM raw_messages
        WHERE processed = FALSE
        ORDER BY id ASC
        LIMIT %s;
        """,
        (limit,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return 0

    # 2) Process each row
    count = 0
    for raw_id, text in rows:
        try:
            data = brain_extract(raw_id, text)

            conn = get_conn()
            cur = conn.cursor()

            # Insert processed row
            cur.execute(
                """
                INSERT INTO processed_messages
                  (raw_id, brand, product, category, sentiment, intent, tickers, tags, processor_version)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    data["raw_id"],
                    data["brand"],
                    data["product"],
                    data["category"],
                    data["sentiment"],
                    data["intent"],
                    data["tickers"],
                    data["tags"],
                    data["processor_version"],
                ),
            )

            _new_id = cur.fetchone()[0]

            # Mark raw processed
            cur.execute(
                "UPDATE raw_messages SET processed = TRUE WHERE id = %s;",
                (raw_id,),
            )

            conn.commit()
            cur.close()
            conn.close()

            count += 1

        except Exception as e:
            print(f"[EVA-WORKER] Failed processing raw_id={raw_id}: {e}")

    return count

def main():
    print("EVA worker starting up...")
    last_notification_poll = 0

    while True:
        n = process_batch(limit=20)
        if n:
            print(f"Processed {n} messages")

        # Emit trigger-based signal events
        emit_trigger_events()

        # Notification polling (every NOTIFICATION_POLL_INTERVAL seconds)
        current_time = time.time()
        print(f"[DEBUG] Checking notification poll: poll_and_notify={bool(poll_and_notify)}, elapsed={current_time - last_notification_poll:.1f}s, interval={NOTIFICATION_POLL_INTERVAL}s", flush=True)
        if poll_and_notify and (current_time - last_notification_poll) >= NOTIFICATION_POLL_INTERVAL:
            print("[DEBUG] Entering notification poll...", flush=True)
            try:
                stats = poll_and_notify()
                if stats["sent"] > 0 or stats["failed"] > 0:
                    logger.info(f"[EVA-WORKER] Notifications: {stats['sent']} sent, {stats['failed']} failed")
            except Exception as e:
                logger.error(f"[EVA-WORKER] Notification polling error: {e}")
            finally:
                last_notification_poll = current_time

        time.sleep(10)

if __name__ == "__main__":
    main()