#!/usr/bin/env python3
"""
Historical Signal Backtest
Validates that Reddit brand trends predicted stock performance
Implements Phase 0 validation from social-signal-trading skill
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import yfinance as yf
import pandas as pd
import numpy as np
import logging
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database config
DB_CONFIG = {
    'host': '172.20.0.2',  # Docker container IP
    'port': 5432,
    'database': 'eva_finance',
    'user': 'eva',
    'password': 'eva_password_change_me'
}

# Brand to ticker mapping (update with actual mappings)
BRAND_TO_TICKER = {
    # Athletic/Running
    'hoka': 'DECK',  # Deckers Outdoor
    'on running': 'ONON',
    'brooks': 'BRK.A',  # Berkshire Hathaway owns Brooks (complicated)
    'asics': '7936.T',  # Tokyo stock exchange
    'nike': 'NKE',
    'adidas': 'ADDYY',  # ADR
    'new balance': None,  # Private

    # Footwear
    'allbirds': 'BIRD',
    'crocs': 'CROX',
    'birkenstock': 'BIRK',

    # Apparel
    'lululemon': 'LULU',
    'patagonia': None,  # Private
    'arc\'teryx': None,  # Owned by Amer Sports (private until recent IPO)
    'carhartt': None,  # Private
    'duluth trading': 'DLTH',

    # Outdoor/Travel
    'osprey': None,  # Private, owned by Helen of Troy (HELE) - small %
    'yeti': 'YETI',
    'hydro flask': None,  # Owned by Helen of Troy

    # Boots/Shoes
    'red wing': None,  # Private
    'thursday boots': None,  # Private
    'blundstone': None,  # Private
}

# Material brand analysis (what % of parent company revenue)
BRAND_MATERIALITY = {
    'hoka': {'ticker': 'DECK', 'revenue_share': 0.35, 'growth_lever': 0.9},  # Growing fast
    'on running': {'ticker': 'ONON', 'revenue_share': 1.0, 'growth_lever': 1.0},  # Pure-play
    'allbirds': {'ticker': 'BIRD', 'revenue_share': 1.0, 'growth_lever': 1.0},
    'crocs': {'ticker': 'CROX', 'revenue_share': 1.0, 'growth_lever': 1.0},
    'lululemon': {'ticker': 'LULU', 'revenue_share': 1.0, 'growth_lever': 1.0},
    'duluth trading': {'ticker': 'DLTH', 'revenue_share': 1.0, 'growth_lever': 1.0},
    'yeti': {'ticker': 'YETI', 'revenue_share': 1.0, 'growth_lever': 1.0},
    'nike': {'ticker': 'NKE', 'revenue_share': 1.0, 'growth_lever': 0.4},  # Too big to move on trends
}


def get_brand_mentions_over_time(brand: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """
    Get daily mention counts for a brand over time period
    """
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    query = """
        SELECT
            DATE(timestamp) as date,
            COUNT(*) as mention_count,
            AVG(CAST(meta->>'score' AS INT)) as avg_score
        FROM processed_messages pm
        JOIN raw_messages rm ON rm.id = pm.raw_id
        WHERE %s = ANY(brand)
        AND timestamp BETWEEN %s AND %s
        GROUP BY DATE(timestamp)
        ORDER BY DATE(timestamp)
    """

    cursor.execute(query, (brand.lower(), start_date, end_date))
    results = cursor.fetchall()

    conn.close()

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    return df


def detect_historical_trends(min_increase: float = 2.0, min_baseline_mentions: int = 3) -> List[Dict]:
    """
    Find clear brand trends in historical data

    Args:
        min_increase: Minimum mention increase ratio (2.0 = 2x increase)
        min_baseline_mentions: Minimum mentions in baseline period

    Returns:
        List of detected trends with metadata
    """
    logger.info("Scanning for historical brand trends...")

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Get all unique brands
    cursor.execute("""
        SELECT DISTINCT unnest(brand) as brand
        FROM processed_messages
        WHERE brand IS NOT NULL AND brand != '{}'
        ORDER BY brand
    """)
    brands = [row['brand'] for row in cursor.fetchall()]

    conn.close()

    logger.info(f"Found {len(brands)} unique brands in historical data")

    trends = []

    for brand in brands:
        # Skip if not tradeable
        ticker = BRAND_TO_TICKER.get(brand.lower())
        if not ticker:
            continue

        # Get mentions over time (last 12 months of historical data)
        end_date = datetime.now() - timedelta(days=30)
        start_date = end_date - timedelta(days=365)

        mentions_df = get_brand_mentions_over_time(brand, start_date, end_date)

        if mentions_df.empty:
            continue

        # Resample to weekly for trend detection
        weekly = mentions_df.resample('W').sum()

        if len(weekly) < 8:  # Need at least 8 weeks of data
            continue

        # Split into baseline (first 4 weeks) and surge (next 4 weeks)
        for i in range(4, len(weekly) - 4):
            baseline = weekly.iloc[i-4:i]['mention_count'].sum()
            surge = weekly.iloc[i:i+4]['mention_count'].sum()

            if baseline < min_baseline_mentions:
                continue

            increase_ratio = surge / baseline if baseline > 0 else 0

            if increase_ratio >= min_increase:
                trend_start = weekly.index[i]

                trends.append({
                    'brand': brand,
                    'ticker': ticker,
                    'trend_start': trend_start,
                    'baseline_mentions': int(baseline),
                    'surge_mentions': int(surge),
                    'increase_ratio': float(increase_ratio),
                    'materiality': BRAND_MATERIALITY.get(brand.lower(), {}).get('revenue_share', 0.5)
                })

                logger.info(f"Found trend: {brand} ({ticker}) - {increase_ratio:.1f}x increase starting {trend_start.date()}")
                break  # Only take first clear trend per brand

    logger.info(f"Detected {len(trends)} tradeable historical trends")
    return trends


def get_stock_performance(ticker: str, start_date: datetime, days_forward: List[int] = [30, 60, 90, 180]) -> Dict[int, float]:
    """
    Get stock returns at various intervals after a signal date

    Args:
        ticker: Stock ticker symbol
        start_date: Signal date
        days_forward: List of days to measure returns (e.g., [30, 60, 90])

    Returns:
        Dict mapping days_forward to return percentages
    """
    try:
        # Download stock data (start - 7 days for baseline, end + max days forward)
        download_start = start_date - timedelta(days=7)
        download_end = start_date + timedelta(days=max(days_forward) + 30)

        stock = yf.Ticker(ticker)
        hist = stock.history(start=download_start, end=download_end)

        if hist.empty:
            logger.warning(f"No stock data for {ticker}")
            return {}

        # Get price at signal date (or closest trading day after)
        signal_prices = hist.loc[hist.index >= start_date]['Close']
        if signal_prices.empty:
            return {}

        entry_price = signal_prices.iloc[0]
        entry_date = signal_prices.index[0]

        returns = {}

        for days in days_forward:
            target_date = entry_date + timedelta(days=days)
            future_prices = hist.loc[hist.index >= target_date]['Close']

            if future_prices.empty:
                returns[days] = None
            else:
                exit_price = future_prices.iloc[0]
                returns[days] = ((exit_price - entry_price) / entry_price) * 100

        return returns

    except Exception as e:
        logger.error(f"Error fetching stock data for {ticker}: {e}")
        return {}


def run_backtest(trends: List[Dict]) -> pd.DataFrame:
    """
    Run backtest on detected trends

    Args:
        trends: List of trend dictionaries from detect_historical_trends()

    Returns:
        DataFrame with backtest results
    """
    logger.info(f"Running backtest on {len(trends)} historical trends...")

    results = []

    for trend in trends:
        brand = trend['brand']
        ticker = trend['ticker']
        trend_start = trend['trend_start']

        logger.info(f"Backtesting {brand} ({ticker}) from {trend_start.date()}")

        # Get stock performance
        returns = get_stock_performance(ticker, trend_start)

        if not returns:
            logger.warning(f"Skipping {brand} - no stock data available")
            continue

        result = {
            'brand': brand,
            'ticker': ticker,
            'signal_date': trend_start,
            'baseline_mentions': trend['baseline_mentions'],
            'surge_mentions': trend['surge_mentions'],
            'increase_ratio': trend['increase_ratio'],
            'materiality': trend['materiality'],
            'return_30d': returns.get(30),
            'return_60d': returns.get(60),
            'return_90d': returns.get(90),
            'return_180d': returns.get(180),
        }

        results.append(result)

    df = pd.DataFrame(results)
    return df


def analyze_results(results: pd.DataFrame) -> Dict:
    """
    Analyze backtest results and generate validation report

    Phase 0 Success Criteria:
    - Win rate >55% at 3-6 month horizons
    - Average returns >5% for winners
    - At least 10 validated signals
    - Clear time-to-profit pattern
    """
    logger.info("=" * 60)
    logger.info("PHASE 0 VALIDATION RESULTS")
    logger.info("=" * 60)

    if results.empty:
        logger.error("No results to analyze!")
        return {}

    total_signals = len(results)

    # Calculate win rates
    win_rate_30d = (results['return_30d'] > 0).sum() / results['return_30d'].notna().sum() * 100 if results['return_30d'].notna().sum() > 0 else 0
    win_rate_60d = (results['return_60d'] > 0).sum() / results['return_60d'].notna().sum() * 100 if results['return_60d'].notna().sum() > 0 else 0
    win_rate_90d = (results['return_90d'] > 0).sum() / results['return_90d'].notna().sum() * 100 if results['return_90d'].notna().sum() > 0 else 0
    win_rate_180d = (results['return_180d'] > 0).sum() / results['return_180d'].notna().sum() * 100 if results['return_180d'].notna().sum() > 0 else 0

    # Calculate average returns (winners only)
    winners_30d = results[results['return_30d'] > 0]['return_30d']
    winners_90d = results[results['return_90d'] > 0]['return_90d']
    winners_180d = results[results['return_180d'] > 0]['return_180d']

    avg_return_winners_30d = winners_30d.mean() if len(winners_30d) > 0 else 0
    avg_return_winners_90d = winners_90d.mean() if len(winners_90d) > 0 else 0
    avg_return_winners_180d = winners_180d.mean() if len(winners_180d) > 0 else 0

    # Calculate overall average returns (all trades)
    avg_return_all_90d = results['return_90d'].mean()
    avg_return_all_180d = results['return_180d'].mean()

    logger.info(f"\nTotal signals analyzed: {total_signals}")
    logger.info(f"\nWin Rates:")
    logger.info(f"  30 days:  {win_rate_30d:.1f}%")
    logger.info(f"  60 days:  {win_rate_60d:.1f}%")
    logger.info(f"  90 days:  {win_rate_90d:.1f}%")
    logger.info(f"  180 days: {win_rate_180d:.1f}%")

    logger.info(f"\nAverage Returns (Winners Only):")
    logger.info(f"  30 days:  {avg_return_winners_30d:.1f}%")
    logger.info(f"  90 days:  {avg_return_winners_90d:.1f}%")
    logger.info(f"  180 days: {avg_return_winners_180d:.1f}%")

    logger.info(f"\nAverage Returns (All Trades):")
    logger.info(f"  90 days:  {avg_return_all_90d:.1f}%")
    logger.info(f"  180 days: {avg_return_all_180d:.1f}%")

    logger.info("\n" + "=" * 60)
    logger.info("PHASE 0 DECISION GATE")
    logger.info("=" * 60)

    # Check success criteria
    criteria_met = []
    criteria_failed = []

    if win_rate_90d > 55 or win_rate_180d > 55:
        criteria_met.append(f"✓ Win rate >55%: {max(win_rate_90d, win_rate_180d):.1f}%")
    else:
        criteria_failed.append(f"✗ Win rate <55%: {max(win_rate_90d, win_rate_180d):.1f}%")

    if avg_return_winners_90d > 5 or avg_return_winners_180d > 5:
        criteria_met.append(f"✓ Average returns >5%: {max(avg_return_winners_90d, avg_return_winners_180d):.1f}%")
    else:
        criteria_failed.append(f"✗ Average returns <5%: {max(avg_return_winners_90d, avg_return_winners_180d):.1f}%")

    if total_signals >= 10:
        criteria_met.append(f"✓ At least 10 signals: {total_signals}")
    else:
        criteria_failed.append(f"✗ Fewer than 10 signals: {total_signals}")

    for criterion in criteria_met:
        logger.info(criterion)
    for criterion in criteria_failed:
        logger.info(criterion)

    logger.info("\n" + "=" * 60)

    if len(criteria_failed) == 0:
        logger.info("🚀 DECISION: GO - Proceed to Phase 1")
        logger.info("Core thesis validated. Social signals predict stock returns.")
        decision = "GO"
    elif len(criteria_met) >= 2:
        logger.info("⚠️  DECISION: CAUTIOUS GO - Proceed with refinements")
        logger.info("Thesis shows promise but needs improvement.")
        decision = "CAUTIOUS_GO"
    else:
        logger.info("❌ DECISION: NO-GO - Refine social signals before proceeding")
        logger.info("Core thesis not validated. Need to improve signal quality.")
        decision = "NO_GO"

    logger.info("=" * 60)

    return {
        'total_signals': total_signals,
        'win_rate_90d': win_rate_90d,
        'win_rate_180d': win_rate_180d,
        'avg_return_winners_90d': avg_return_winners_90d,
        'avg_return_winners_180d': avg_return_winners_180d,
        'decision': decision,
        'criteria_met': criteria_met,
        'criteria_failed': criteria_failed
    }


def main():
    """
    Main backtest execution
    """
    logger.info("Starting EVA-Finance Phase 0 Historical Backtest")

    # Step 1: Detect historical trends
    trends = detect_historical_trends(min_increase=2.0, min_baseline_mentions=5)

    if len(trends) < 5:
        logger.warning(f"Only found {len(trends)} trends - may need more historical data or lower thresholds")

    # Step 2: Run backtest
    results = run_backtest(trends)

    # Step 3: Analyze results
    analysis = analyze_results(results)

    # Step 4: Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"/home/koolhand/projects/eva-finance/backtest_results_{timestamp}.csv"
    analysis_file = f"/home/koolhand/projects/eva-finance/backtest_analysis_{timestamp}.json"

    results.to_csv(results_file, index=False)
    with open(analysis_file, 'w') as f:
        json.dump(analysis, f, indent=2, default=str)

    logger.info(f"\nResults saved to:")
    logger.info(f"  CSV: {results_file}")
    logger.info(f"  Analysis: {analysis_file}")


if __name__ == '__main__':
    main()
