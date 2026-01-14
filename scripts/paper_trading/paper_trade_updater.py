#!/usr/bin/env python3
"""
Paper Trade Daily Updater

Updates all open paper trading positions with current market prices
and checks exit conditions (profit target, stop loss, time limit).

Exit Conditions:
- Profit Target: >= 15% gain → Close with profit_target
- Stop Loss: <= -10% loss → Close with stop_loss
- Time Limit: >= 90 days held → Close with time_exit

Usage:
    python paper_trade_updater.py

Designed to run daily at 4pm ET (market close + 30 min)
"""

import os
import sys
from datetime import datetime, date
from typing import Optional, Dict, Any, List
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
    'host': os.getenv('DB_HOST', 'eva_db'),
    'port': int(os.getenv('DB_PORT', '5432')),
    'database': os.getenv('DB_NAME', 'eva_finance'),
    'user': os.getenv('DB_USER', 'eva'),
    'password': os.getenv('DB_PASSWORD', 'eva_password_change_me')
}

# Exit thresholds
PROFIT_TARGET = 0.15  # 15% gain
STOP_LOSS = -0.10     # -10% loss
MAX_DAYS_HELD = 90    # 90 day time limit


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


def get_open_positions(conn) -> List[Dict[str, Any]]:
    """
    Retrieve all open paper trading positions

    Returns:
        List of position dictionaries
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    query = """
        SELECT
            id,
            brand,
            ticker,
            entry_date,
            entry_price,
            current_price,
            position_size,
            signal_confidence,
            tag
        FROM paper_trades
        WHERE status = 'open'
        ORDER BY entry_date ASC
    """

    cursor.execute(query)
    positions = cursor.fetchall()
    cursor.close()

    logger.info(f"Found {len(positions)} open positions")
    return positions


def calculate_position_metrics(position: Dict[str, Any], current_price: float) -> Dict[str, Any]:
    """
    Calculate position performance metrics

    Args:
        position: Position dictionary
        current_price: Current market price

    Returns:
        Dictionary with calculated metrics
    """
    entry_price = float(position['entry_price'])
    position_size = float(position['position_size'])
    days_held = (date.today() - position['entry_date']).days

    # Calculate shares (position_size is dollar amount)
    shares = position_size / entry_price

    # Calculate returns
    current_value = shares * current_price
    return_dollar = current_value - position_size
    return_pct = (current_price - entry_price) / entry_price

    return {
        'current_price': current_price,
        'current_value': current_value,
        'return_dollar': return_dollar,
        'return_pct': return_pct,
        'days_held': days_held,
        'shares': shares
    }


def check_exit_conditions(metrics: Dict[str, Any]) -> Optional[str]:
    """
    Check if position should be closed based on exit conditions

    Args:
        metrics: Position metrics dictionary

    Returns:
        Exit reason string if should exit, None otherwise
    """
    return_pct = metrics['return_pct']
    days_held = metrics['days_held']

    # Check profit target
    if return_pct >= PROFIT_TARGET:
        return 'profit_target'

    # Check stop loss
    if return_pct <= STOP_LOSS:
        return 'stop_loss'

    # Check time limit
    if days_held >= MAX_DAYS_HELD:
        return 'time_exit'

    return None


def update_position(conn, position: Dict[str, Any], metrics: Dict[str, Any]) -> None:
    """
    Update open position with current metrics

    Args:
        conn: Database connection
        position: Position dictionary
        metrics: Current metrics
    """
    cursor = conn.cursor()

    update_query = """
        UPDATE paper_trades
        SET
            current_price = %(current_price)s,
            days_held = %(days_held)s,
            return_pct = %(return_pct)s,
            return_dollar = %(return_dollar)s,
            updated_at = NOW()
        WHERE id = %(position_id)s
    """

    cursor.execute(update_query, {
        'current_price': metrics['current_price'],
        'days_held': metrics['days_held'],
        'return_pct': metrics['return_pct'],
        'return_dollar': metrics['return_dollar'],
        'position_id': position['id']
    })

    conn.commit()
    cursor.close()

    logger.info(
        f"Updated #{position['id']} {position['brand']} ({position['ticker']}): "
        f"${metrics['current_price']:.2f} | "
        f"{metrics['return_pct']*100:+.2f}% | "
        f"${metrics['return_dollar']:+.2f} | "
        f"{metrics['days_held']} days"
    )


def close_position(conn, position: Dict[str, Any], metrics: Dict[str, Any], exit_reason: str) -> None:
    """
    Close a position that met exit conditions

    Args:
        conn: Database connection
        position: Position dictionary
        metrics: Current metrics
        exit_reason: Reason for exit
    """
    cursor = conn.cursor()

    close_query = """
        UPDATE paper_trades
        SET
            status = 'closed',
            exit_date = CURRENT_DATE,
            exit_price = %(exit_price)s,
            exit_reason = %(exit_reason)s,
            current_price = %(exit_price)s,
            days_held = %(days_held)s,
            return_pct = %(return_pct)s,
            return_dollar = %(return_dollar)s,
            updated_at = NOW()
        WHERE id = %(position_id)s
    """

    cursor.execute(close_query, {
        'exit_price': metrics['current_price'],
        'exit_reason': exit_reason,
        'days_held': metrics['days_held'],
        'return_pct': metrics['return_pct'],
        'return_dollar': metrics['return_dollar'],
        'position_id': position['id']
    })

    conn.commit()
    cursor.close()

    exit_emoji = {
        'profit_target': '🎯',
        'stop_loss': '🛑',
        'time_exit': '⏰'
    }

    logger.info(
        f"{exit_emoji.get(exit_reason, '✓')} CLOSED #{position['id']} {position['brand']} ({position['ticker']}): "
        f"Entry ${float(position['entry_price']):.2f} → Exit ${metrics['current_price']:.2f} | "
        f"{metrics['return_pct']*100:+.2f}% ({exit_reason}) | "
        f"${metrics['return_dollar']:+.2f} | {metrics['days_held']} days"
    )


def process_position(conn, position: Dict[str, Any]) -> Dict[str, str]:
    """
    Process a single position: fetch price, update metrics, check exits

    Args:
        conn: Database connection
        position: Position dictionary

    Returns:
        Dictionary with action taken
    """
    # Fetch current price
    current_price = get_current_price(position['ticker'])

    if current_price is None:
        logger.warning(f"Skipping {position['brand']} - price unavailable")
        return {'action': 'skipped', 'reason': 'no_price'}

    # Calculate metrics
    metrics = calculate_position_metrics(position, current_price)

    # Check exit conditions
    exit_reason = check_exit_conditions(metrics)

    if exit_reason:
        close_position(conn, position, metrics, exit_reason)
        return {'action': 'closed', 'reason': exit_reason}
    else:
        update_position(conn, position, metrics)
        return {'action': 'updated'}


def update_all_positions():
    """
    Main processing loop: update all open positions
    """
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        # Get all open positions
        positions = get_open_positions(conn)

        if not positions:
            logger.info("No open positions to update")
            return

        # Process each position
        results = {
            'updated': 0,
            'closed': 0,
            'skipped': 0,
            'closed_reasons': {}
        }

        for position in positions:
            result = process_position(conn, position)

            if result['action'] == 'updated':
                results['updated'] += 1
            elif result['action'] == 'closed':
                results['closed'] += 1
                reason = result['reason']
                results['closed_reasons'][reason] = results['closed_reasons'].get(reason, 0) + 1
            elif result['action'] == 'skipped':
                results['skipped'] += 1

        # Summary
        logger.info("=" * 70)
        logger.info(f"Update complete: {results['updated']} updated, {results['closed']} closed, {results['skipped']} skipped")

        if results['closed_reasons']:
            logger.info("Closed positions breakdown:")
            for reason, count in results['closed_reasons'].items():
                logger.info(f"  - {reason}: {count}")

    finally:
        conn.close()


def main():
    """Entry point"""
    logger.info("=" * 70)
    logger.info("Paper Trade Daily Updater")
    logger.info(f"Run Date: {date.today()}")
    logger.info("=" * 70)

    try:
        update_all_positions()

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    logger.info("✓ Daily update complete")


if __name__ == '__main__':
    main()
