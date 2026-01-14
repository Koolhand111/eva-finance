#!/usr/bin/env python3
"""
EVA-Finance Signal Suppression Diagnostic Tool
Phase 1: Identify which gate(s) are blocking signals
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os
from datetime import datetime

# Database connection
DB_URL = os.getenv('DATABASE_URL', 'postgres://eva:eva_password_change_me@localhost:5432/eva_finance')

def get_db():
    return psycopg2.connect(DB_URL)

def print_section(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")

def task_1_1_signal_extraction_quality():
    """Check if signals exist and have good data"""
    print_section("Task 1.1: Signal Extraction Quality Check")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Overall signal quality from processed_messages
    cur.execute("""
        WITH brand_counts AS (
            SELECT DISTINCT unnest(brand) as brand_name
            FROM processed_messages
            WHERE array_length(brand, 1) > 0
        )
        SELECT
            (SELECT COUNT(*) FROM processed_messages) as total_messages,
            (SELECT COUNT(*) FROM processed_messages WHERE array_length(brand, 1) > 0) as messages_with_brand,
            (SELECT COUNT(*) FROM brand_counts) as unique_brands,
            (SELECT COUNT(*) FROM processed_messages WHERE sentiment = 'positive') as positive_sentiment,
            (SELECT COUNT(*) FROM processed_messages WHERE sentiment = 'negative') as negative_sentiment,
            (SELECT COUNT(*) FROM processed_messages WHERE sentiment = 'neutral') as neutral_sentiment,
            (SELECT COUNT(*) FROM processed_messages WHERE tags IS NOT NULL AND array_length(tags, 1) > 0) as messages_with_tags,
            (SELECT COUNT(*) FROM processed_messages WHERE array_length(brand, 1) > 1) as multi_brand_messages;
    """)

    result = cur.fetchone()
    print("Processed Messages Overview:")
    for key, value in result.items():
        print(f"  {key}: {value}")

    # Sentiment distribution
    total = result['total_messages']
    if total > 0:
        print(f"\nSentiment Distribution:")
        print(f"  Positive: {result['positive_sentiment']} ({100*result['positive_sentiment']/total:.1f}%)")
        print(f"  Negative: {result['negative_sentiment']} ({100*result['negative_sentiment']/total:.1f}%)")
        print(f"  Neutral: {result['neutral_sentiment']} ({100*result['neutral_sentiment']/total:.1f}%)")

    # Top brands by mention count
    print("\n\nTop 15 Brands by Mention Count:")
    cur.execute("""
        SELECT
            unnest(brand) as brand_name,
            COUNT(*) as mention_count,
            COUNT(DISTINCT id) as unique_messages,
            COUNT(*) FILTER (WHERE sentiment = 'positive') as positive_count,
            COUNT(*) FILTER (WHERE sentiment = 'negative') as negative_count,
            COUNT(*) FILTER (WHERE sentiment = 'neutral') as neutral_count
        FROM processed_messages
        WHERE array_length(brand, 1) > 0
        GROUP BY brand_name
        ORDER BY mention_count DESC
        LIMIT 15;
    """)

    print(f"{'Brand':<30} {'Mentions':<10} {'Messages':<10} {'Pos':<6} {'Neg':<6} {'Neu':<6}")
    print("-" * 78)
    for row in cur.fetchall():
        print(f"{row['brand_name']:<30} {row['mention_count']:<10} {row['unique_messages']:<10} "
              f"{row['positive_count']:<6} {row['negative_count']:<6} {row['neutral_count']:<6}")

    cur.close()
    conn.close()

def task_1_2_gate_failure_analysis():
    """Identify which gate is the primary blocker"""
    print_section("Task 1.2: Gate-by-Gate Failure Analysis")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Individual gate scores for suppressed signals
    print("Top 20 Suppressed Signals - Gate Scores:")
    cur.execute("""
        SELECT
            brand,
            tag,
            spread_score,
            acceleration_score as velocity,
            intent_score as sentiment,
            baseline_score as recency,
            (details->>'mention_count')::integer as mentions,
            (details->>'unique_subreddits')::integer as subreddits,
            gate_failed_reason as failed_gates,
            final_confidence
        FROM eva_confidence_v1
        WHERE band = 'SUPPRESSED' AND final_confidence = 0.0000
        ORDER BY (details->>'mention_count')::integer DESC NULLS LAST
        LIMIT 20;
    """)

    print(f"{'Brand':<20} {'Tag':<15} {'Spread':<8} {'Velocity':<10} {'Sentiment':<10} {'Recency':<9} {'Mentions':<9} {'Subs':<5}")
    print("-" * 100)
    for row in cur.fetchall():
        spread = float(row['spread_score']) if row['spread_score'] is not None else 0.0
        velocity = float(row['velocity']) if row['velocity'] is not None else 0.0
        sentiment = float(row['sentiment']) if row['sentiment'] is not None else 0.0
        recency = float(row['recency']) if row['recency'] is not None else 0.0
        mentions = row['mentions'] if row['mentions'] is not None else 0
        subs = row['subreddits'] if row['subreddits'] is not None else 0
        print(f"{row['brand']:<20} {row['tag']:<15} {spread:<8.4f} {velocity:<10.4f} {sentiment:<10.4f} "
              f"{recency:<9.4f} {mentions:<9} {subs:<5}")

    # Aggregate: Which gate blocks most signals?
    print("\n\nGate Blocking Analysis:")
    print("(Shows which gate fails FIRST for suppressed signals)")
    cur.execute("""
        SELECT
            CASE
                WHEN spread_score < 0.35 THEN 'spread'
                WHEN acceleration_score < 0.20 THEN 'velocity'
                WHEN intent_score < 0.25 THEN 'sentiment'
                WHEN baseline_score < 0.40 THEN 'recency'
                ELSE 'passed_all'
            END as first_blocking_gate,
            COUNT(*) as signals_blocked,
            ROUND(AVG(spread_score), 3) as avg_spread,
            ROUND(AVG(acceleration_score), 3) as avg_velocity,
            ROUND(AVG(intent_score), 3) as avg_sentiment,
            ROUND(AVG(baseline_score), 3) as avg_recency
        FROM eva_confidence_v1
        WHERE band = 'SUPPRESSED' AND final_confidence = 0.0000
        GROUP BY first_blocking_gate
        ORDER BY signals_blocked DESC;
    """)

    print(f"{'Blocking Gate':<20} {'Signals Blocked':<17} {'Avg Spread':<12} {'Avg Velocity':<14} {'Avg Sentiment':<14} {'Avg Recency'}")
    print("-" * 100)
    for row in cur.fetchall():
        print(f"{row['first_blocking_gate']:<20} {row['signals_blocked']:<17} {float(row['avg_spread']):<12.3f} "
              f"{float(row['avg_velocity']):<14.3f} {float(row['avg_sentiment']):<14.3f} {float(row['avg_recency']):<14.3f}")

    cur.close()
    conn.close()

def task_1_3_data_volume_recency():
    """Verify there's enough data for the current thresholds"""
    print_section("Task 1.3: Data Volume & Recency Check")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Overall message volume
    print("Message Volume and Time Distribution:")
    cur.execute("""
        SELECT
            COUNT(*) as total_messages,
            MIN(r.created_at) as earliest_message,
            MAX(r.created_at) as latest_message,
            DATE_PART('day', MAX(r.created_at) - MIN(r.created_at)) as days_of_data,
            COUNT(*) FILTER (WHERE r.created_at > NOW() - INTERVAL '7 days') as last_7_days,
            COUNT(*) FILTER (WHERE r.created_at > NOW() - INTERVAL '30 days') as last_30_days,
            COUNT(DISTINCT r.meta->>'subreddit') as unique_subreddits
        FROM raw_messages r
        JOIN processed_messages p ON r.id = p.raw_id;
    """)

    result = cur.fetchone()
    print(f"  Total processed messages: {result['total_messages']}")
    print(f"  Earliest message: {result['earliest_message']}")
    print(f"  Latest message: {result['latest_message']}")
    print(f"  Days of data: {result['days_of_data']:.1f}")
    print(f"  Messages in last 7 days: {result['last_7_days']}")
    print(f"  Messages in last 30 days: {result['last_30_days']}")
    print(f"  Unique subreddits: {result['unique_subreddits']}")

    # Data freshness warning
    if result['latest_message']:
        days_since_latest = (datetime.now() - result['latest_message'].replace(tzinfo=None)).days
        if days_since_latest > 7:
            print(f"\n  ⚠️  WARNING: Latest message is {days_since_latest} days old - Recency gate will fail!")

    # Velocity calculation feasibility
    print("\n\nVelocity Calculation Check (Top 15 Brands):")
    cur.execute("""
        SELECT
            unnest(p.brand) as brand_name,
            COUNT(*) as total_mentions,
            COUNT(*) FILTER (WHERE r.created_at > NOW() - INTERVAL '7 days') as recent_7d,
            COUNT(*) FILTER (WHERE r.created_at BETWEEN NOW() - INTERVAL '30 days' AND NOW() - INTERVAL '7 days') as historical_23d,
            ROUND(
                COUNT(*) FILTER (WHERE r.created_at > NOW() - INTERVAL '7 days')::numeric / 7.0, 2
            ) as recent_rate,
            ROUND(
                COUNT(*) FILTER (WHERE r.created_at BETWEEN NOW() - INTERVAL '30 days' AND NOW() - INTERVAL '7 days')::numeric / 23.0, 2
            ) as historical_rate
        FROM raw_messages r
        JOIN processed_messages p ON r.id = p.raw_id
        WHERE array_length(p.brand, 1) > 0
        GROUP BY brand_name
        ORDER BY total_mentions DESC
        LIMIT 15;
    """)

    print(f"{'Brand':<30} {'Total':<8} {'7d':<6} {'23d':<6} {'Recent/day':<12} {'Historical/day':<15}")
    print("-" * 95)
    for row in cur.fetchall():
        recent_rate = float(row['recent_rate']) if row['recent_rate'] else 0.0
        historical_rate = float(row['historical_rate']) if row['historical_rate'] else 0.0
        print(f"{row['brand_name']:<30} {row['total_mentions']:<8} {row['recent_7d']:<6} {row['historical_23d']:<6} "
              f"{recent_rate:<12.2f} {historical_rate:<15.2f}")

    cur.close()
    conn.close()

def main():
    print("\n" + "█"*80)
    print("█" + " "*78 + "█")
    print("█" + "  EVA-FINANCE SIGNAL SUPPRESSION DIAGNOSTIC".center(78) + "█")
    print("█" + "  Phase 1: Root Cause Analysis".center(78) + "█")
    print("█" + " "*78 + "█")
    print("█"*80)

    try:
        task_1_1_signal_extraction_quality()
        task_1_2_gate_failure_analysis()
        task_1_3_data_volume_recency()

        print_section("Diagnostic Complete")
        print("Next Step: Review results above to identify root cause.")
        print("Expected findings documented in Problem Statement Phase 2.\n")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
