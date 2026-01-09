#!/usr/bin/env python3
"""
Paper Trade Entry Script

Automatically creates paper trading positions when signals reach
RECOMMENDATION_ELIGIBLE status. This enables forward-looking validation
of the investment thesis.

Usage:
    python paper_trade_entry.py

Runs continuously or as a scheduled job to monitor for new tradeable signals.
"""

import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any
import logging

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
    'host': os.getenv('DB_HOST', '172.20.0.2'),
    'port': int(os.getenv('DB_PORT', '5432')),
    'database': os.getenv('DB_NAME', 'eva_finance'),
    'user': os.getenv('DB_USER', 'eva'),
    'password': os.getenv('DB_PASSWORD', 'eva_password_change_me')
}

# Brand to ticker mapping (from backtest)
BRAND_TO_TICKER = {
    'hoka': 'DECK',       # Deckers Outdoor (Hoka parent)
    'on running': 'ONON',
    'lululemon': 'LULU',
    'crocs': 'CROX',
    'yeti': 'YETI',
    'duluth trading': 'DLTH',
    'allbirds': 'BIRD',
    'ugg': 'DECK',        # Also Deckers
    'teva': 'DECK',       # Also Deckers
    'columbia': 'COLM',
    'north face': 'VFC',   # VF Corp
    'vans': 'VFC',         # VF Corp
    'timberland': 'VFC',   # VF Corp
    'patagonia': None,     # Private
    'arcteryx': 'ANTA',    # Anta Sports (Hong Kong)
    'salomon': 'ADS.DE',   # Adidas
    'brooks': 'BRK.A',     # Berkshire Hathaway (owner)
    'new balance': None,   # Private
    'carhartt': None,      # Private
}


def get_current_price(ticker: str) -> Optional[float]:
    """
    Fetch current stock price using yfinance

    Args:
        ticker: Stock ticker symbol

    Returns:
        Current price or None if unavailable
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='1d')

        if hist.empty:
            logger.warning(f"No price data available for {ticker}")
            return None

        price = float(hist['Close'].iloc[-1])
        logger.debug(f"{ticker} current price: ${price:.2f}")
        return price

    except Exception as e:
        logger.error(f"Error fetching price for {ticker}: {e}")
        return None


def get_pending_signals(conn) -> list[Dict[str, Any]]:
    """
    Find signal events that are RECOMMENDATION_ELIGIBLE but don't have paper trades yet

    Returns:
        List of signal dictionaries ready for paper trading
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    query = """
        SELECT
            se.id AS signal_event_id,
            se.brand,
            se.tag,
            se.day AS signal_date,
            se.payload->>'final_confidence' AS confidence
        FROM signal_events se
        LEFT JOIN paper_trades pt ON pt.signal_event_id = se.id
        WHERE se.event_type = 'RECOMMENDATION_ELIGIBLE'
        AND pt.id IS NULL  -- No paper trade created yet
        ORDER BY se.day DESC
    """

    cursor.execute(query)
    results = cursor.fetchall()
    cursor.close()

    logger.info(f"Found {len(results)} signals pending paper trade entry")
    return results


def create_paper_trade(conn, signal: Dict[str, Any]) -> Optional[int]:
    """
    Create a paper trading position for a signal

    Args:
        conn: Database connection
        signal: Signal event dictionary

    Returns:
        Paper trade ID if created, None if skipped
    """
    brand = signal['brand'].lower()
    ticker = BRAND_TO_TICKER.get(brand)

    if ticker is None:
        logger.info(f"⊘ Skipping {signal['brand']} - private company")
        return None

    # Get current price
    entry_price = get_current_price(ticker)
    if entry_price is None:
        logger.warning(f"⚠ Skipping {signal['brand']} ({ticker}) - price unavailable")
        return None

    # Create paper trade
    cursor = conn.cursor()

    insert_query = """
        INSERT INTO paper_trades (
            signal_event_id,
            brand,
            tag,
            ticker,
            entry_date,
            entry_price,
            current_price,
            signal_confidence,
            position_size,
            status
        ) VALUES (
            %(signal_event_id)s,
            %(brand)s,
            %(tag)s,
            %(ticker)s,
            %(entry_date)s,
            %(entry_price)s,
            %(current_price)s,
            %(confidence)s,
            1000.00,  -- $1000 per position
            'open'
        )
        RETURNING id
    """

    try:
        cursor.execute(insert_query, {
            'signal_event_id': signal['signal_event_id'],
            'brand': signal['brand'],
            'tag': signal['tag'],
            'ticker': ticker,
            'entry_date': signal['signal_date'],
            'entry_price': entry_price,
            'current_price': entry_price,
            'confidence': signal.get('confidence')
        })

        paper_trade_id = cursor.fetchone()[0]
        conn.commit()

        logger.info(
            f"✓ Paper trade #{paper_trade_id}: {signal['brand']} ({ticker}) "
            f"@ ${entry_price:.2f} | Signal: {signal['signal_date']}"
        )

        return paper_trade_id

    except psycopg2.IntegrityError as e:
        conn.rollback()
        logger.warning(f"⊘ Duplicate paper trade for signal {signal['signal_event_id']}: {e}")
        return None

    except Exception as e:
        conn.rollback()
        logger.error(f"✗ Error creating paper trade: {e}")
        return None

    finally:
        cursor.close()


def process_pending_signals():
    """
    Main processing loop: find pending signals and create paper trades
    """
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        # Get signals needing paper trades
        pending = get_pending_signals(conn)

        if not pending:
            logger.info("No pending signals for paper trading")
            return

        # Create paper trades
        created_count = 0
        skipped_count = 0

        for signal in pending:
            result = create_paper_trade(conn, signal)

            if result:
                created_count += 1
            else:
                skipped_count += 1

        logger.info(
            f"Paper trade entry complete: "
            f"{created_count} created, {skipped_count} skipped"
        )

    finally:
        conn.close()


def main():
    """Entry point"""
    logger.info("=" * 70)
    logger.info("Paper Trade Entry - Forward Validation System")
    logger.info("=" * 70)

    try:
        process_pending_signals()

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    logger.info("✓ Paper trade entry complete")


if __name__ == '__main__':
    main()
