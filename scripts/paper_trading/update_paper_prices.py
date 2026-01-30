#!/usr/bin/env python3
"""
Daily Price Updater

Updates current prices for all open paper trading positions.
Run this daily (via cron) to track unrealized P&L.

Usage:
    python update_paper_prices.py

Schedule:
    0 16 * * 1-5  # Run at 4pm ET (market close) Monday-Friday
"""

import os
import sys
from datetime import datetime
from typing import Dict, List
import logging
import time

import psycopg2
from psycopg2.extras import RealDictCursor
import yfinance as yf

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'db'),
    'port': int(os.getenv('DB_PORT', '5432')),
    'database': os.getenv('DB_NAME', 'eva_finance'),
    'user': os.getenv('DB_USER', 'eva'),
    'password': os.getenv('DB_PASSWORD', 'eva_password_change_me')
}


def get_open_positions(conn) -> List[Dict]:
    """
    Fetch all open paper trading positions

    Returns:
        List of open position dictionaries
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    query = """
        SELECT
            id,
            ticker,
            brand,
            entry_date,
            entry_price,
            current_price,
            position_size
        FROM paper_trades
        WHERE status = 'open'
        ORDER BY ticker, entry_date
    """

    cursor.execute(query)
    results = cursor.fetchall()
    cursor.close()

    logger.info(f"Found {len(results)} open positions to update")
    return results


def get_batch_prices(tickers: List[str]) -> Dict[str, float]:
    """
    Fetch current prices for multiple tickers efficiently

    Args:
        tickers: List of ticker symbols

    Returns:
        Dictionary mapping ticker -> current price
    """
    prices = {}

    # Batch download for efficiency
    try:
        ticker_string = " ".join(tickers)
        data = yf.download(
            ticker_string,
            period='1d',
            progress=False
        )

        if data.empty:
            logger.warning("No price data returned from batch download")
            return prices

        # Handle single ticker vs multiple
        if len(tickers) == 1:
            if not data.empty:
                prices[tickers[0]] = float(data['Close'].iloc[-1].iloc[0] if hasattr(data['Close'].iloc[-1], 'iloc') else data['Close'].iloc[-1])
        else:
            for ticker in tickers:
                try:
                    if ticker in data['Close'].columns:
                        price = float(data['Close'][ticker].iloc[-1])
                        prices[ticker] = price
                except Exception as e:
                    logger.warning(f"Could not extract price for {ticker}: {e}")

    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        # Fallback to individual downloads
        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='1d')
                if not hist.empty:
                    prices[ticker] = float(hist['Close'].iloc[-1])
                time.sleep(0.5)  # Rate limiting
            except Exception as e2:
                logger.warning(f"Failed to get price for {ticker}: {e2}")

    logger.info(f"Successfully fetched {len(prices)}/{len(tickers)} prices")
    return prices


def update_position_price(conn, position_id: int, new_price: float):
    """
    Update current price for a paper trading position

    Args:
        conn: Database connection
        position_id: Paper trade ID
        new_price: Current market price
    """
    cursor = conn.cursor()

    update_query = """
        UPDATE paper_trades
        SET current_price = %s,
            updated_at = NOW()
        WHERE id = %s
    """

    try:
        cursor.execute(update_query, (new_price, position_id))
        conn.commit()

    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating position {position_id}: {e}")

    finally:
        cursor.close()


def update_all_prices():
    """
    Main update loop: fetch prices and update database
    """
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        # Get open positions
        positions = get_open_positions(conn)

        if not positions:
            logger.info("No open positions to update")
            return

        # Get unique tickers
        tickers = list(set(p['ticker'] for p in positions))
        logger.info(f"Fetching prices for {len(tickers)} unique tickers")

        # Batch fetch prices
        prices = get_batch_prices(tickers)

        # Update each position
        updated_count = 0
        failed_count = 0

        for position in positions:
            ticker = position['ticker']

            if ticker not in prices:
                logger.warning(f"⚠ No price data for {ticker} ({position['brand']})")
                failed_count += 1
                continue

            new_price = prices[ticker]
            old_price = float(position['current_price']) if position['current_price'] else None
            entry_price = float(position['entry_price']) if position['entry_price'] else None

            # Calculate return
            if entry_price:
                return_pct = ((new_price - entry_price) / entry_price) * 100
            else:
                return_pct = 0

            # Update database
            update_position_price(conn, position['id'], new_price)

            # Log significant changes
            if old_price:
                price_change_pct = ((new_price - old_price) / old_price) * 100
                if abs(price_change_pct) > 2:  # Log if >2% daily move
                    logger.info(
                        f"  {ticker} ({position['brand']}): "
                        f"${old_price:.2f} → ${new_price:.2f} "
                        f"({price_change_pct:+.1f}% today, {return_pct:+.1f}% total)"
                    )
            else:
                logger.info(
                    f"  {ticker} ({position['brand']}): ${new_price:.2f} "
                    f"({return_pct:+.1f}% total)"
                )

            updated_count += 1

        logger.info(
            f"Price update complete: "
            f"{updated_count} updated, {failed_count} failed"
        )

        # Show summary stats
        show_summary(conn)

    finally:
        conn.close()


def show_summary(conn):
    """
    Display summary of current paper trading performance
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    query = "SELECT * FROM v_paper_trading_performance"
    cursor.execute(query)
    stats = cursor.fetchone()
    cursor.close()

    if not stats:
        return

    logger.info("=" * 70)
    logger.info("PAPER TRADING PERFORMANCE SUMMARY")
    logger.info("=" * 70)

    # Closed positions
    if stats['total_closed_trades'] > 0:
        logger.info(f"Closed Positions: {stats['total_closed_trades']}")
        logger.info(f"  Win Rate: {stats['win_rate_pct']:.1f}%")
        logger.info(f"  Avg Return: {stats['avg_return_pct']:+.2f}%")
        logger.info(f"  Winners: {stats['avg_winner_return_pct']:+.2f}%")
        logger.info(f"  Losers: {stats['avg_loser_return_pct']:+.2f}%")
        logger.info(f"  Best: {stats['best_return_pct']:+.2f}%")
        logger.info(f"  Worst: {stats['worst_return_pct']:+.2f}%")
        logger.info(f"  Avg Hold: {stats['avg_days_held']:.1f} days")

    # Open positions
    if stats['open_positions'] > 0:
        logger.info(f"\nOpen Positions: {stats['open_positions']}")
        logger.info(f"  Currently Winning: {stats['open_winning']}")
        logger.info(f"  Currently Losing: {stats['open_losing']}")
        logger.info(f"  Avg Unrealized: {stats['avg_unrealized_return_pct']:+.2f}%")

    logger.info("=" * 70)


def main():
    """Entry point"""
    logger.info("=" * 70)
    logger.info(f"Daily Price Update - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

    try:
        update_all_prices()

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    logger.info("✓ Price update complete")


if __name__ == '__main__':
    main()
