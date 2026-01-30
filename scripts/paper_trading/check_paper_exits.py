#!/usr/bin/env python3
"""
Paper Trade Exit Checker

Checks open paper trading positions against exit criteria and closes
positions that meet exit conditions.

Exit Rules (from validation skill):
- Time-based: 90 days → exit regardless
- Profit target: +15% gain → take profit
- Stop loss: -10% loss → cut losses

Usage:
    python check_paper_exits.py

Schedule:
    0 16 * * 1-5  # Run after price update at market close
"""

import os
import sys
from datetime import datetime, date
from typing import List, Dict, Optional
import logging

import psycopg2
from psycopg2.extras import RealDictCursor

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

# Exit criteria (from validation.md)
MAX_HOLD_DAYS = 90
PROFIT_TARGET_PCT = 15.0
STOP_LOSS_PCT = -10.0


def get_positions_for_exit_check(conn) -> List[Dict]:
    """
    Fetch open positions with current prices for exit checking

    Returns:
        List of position dictionaries with computed metrics
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    query = """
        SELECT
            id,
            ticker,
            brand,
            tag,
            entry_date,
            entry_price,
            current_price,
            position_size,
            signal_confidence,
            CURRENT_DATE - entry_date AS days_held,
            CASE
                WHEN current_price IS NOT NULL AND entry_price > 0
                THEN ((current_price - entry_price) / entry_price) * 100
                ELSE NULL
            END AS return_pct
        FROM paper_trades
        WHERE status = 'open'
        AND current_price IS NOT NULL  -- Need price to evaluate
        ORDER BY days_held DESC
    """

    cursor.execute(query)
    results = cursor.fetchall()
    cursor.close()

    logger.info(f"Checking {len(results)} open positions for exit conditions")
    return results


def check_exit_condition(position: Dict) -> Optional[str]:
    """
    Evaluate whether position meets any exit criteria

    Args:
        position: Position dictionary with metrics

    Returns:
        Exit reason if should exit, None otherwise
    """
    days_held = position['days_held']
    return_pct = position['return_pct']

    if return_pct is None:
        return None

    # Time-based exit (highest priority)
    if days_held >= MAX_HOLD_DAYS:
        return 'time_exit'

    # Profit target
    if return_pct >= PROFIT_TARGET_PCT:
        return 'profit_target'

    # Stop loss
    if return_pct <= STOP_LOSS_PCT:
        return 'stop_loss'

    return None


def close_position(
    conn,
    position_id: int,
    exit_price: float,
    exit_reason: str,
    exit_date: Optional[date] = None
) -> bool:
    """
    Close a paper trading position

    Args:
        conn: Database connection
        position_id: Paper trade ID
        exit_price: Price at exit
        exit_reason: Reason for exit
        exit_date: Exit date (defaults to today)

    Returns:
        True if closed successfully
    """
    if exit_date is None:
        exit_date = date.today()

    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Get position details for calculation
    cursor.execute(
        """
        SELECT entry_date, entry_price, position_size
        FROM paper_trades
        WHERE id = %s
        """,
        (position_id,)
    )
    position = cursor.fetchone()

    if not position:
        logger.error(f"Position {position_id} not found")
        cursor.close()
        return False

    # Calculate performance
    days_held = (exit_date - position['entry_date']).days
    return_pct = ((exit_price - position['entry_price']) / position['entry_price']) * 100
    return_dollar = (exit_price - position['entry_price']) / position['entry_price'] * position['position_size']

    # Update position to closed
    update_query = """
        UPDATE paper_trades
        SET
            status = 'closed',
            exit_date = %s,
            exit_price = %s,
            exit_reason = %s,
            days_held = %s,
            return_pct = %s,
            return_dollar = %s,
            updated_at = NOW()
        WHERE id = %s
    """

    try:
        cursor.execute(
            update_query,
            (exit_date, exit_price, exit_reason, days_held, return_pct, return_dollar, position_id)
        )
        conn.commit()
        cursor.close()
        return True

    except Exception as e:
        conn.rollback()
        cursor.close()
        logger.error(f"Error closing position {position_id}: {e}")
        return False


def process_exits():
    """
    Main processing loop: check positions and close those meeting exit criteria
    """
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        # Get positions to check
        positions = get_positions_for_exit_check(conn)

        if not positions:
            logger.info("No positions ready for exit check")
            return

        # Check each position
        closed_count = 0
        exit_reasons = {}

        for position in positions:
            exit_reason = check_exit_condition(position)

            if exit_reason:
                success = close_position(
                    conn,
                    position['id'],
                    position['current_price'],
                    exit_reason
                )

                if success:
                    closed_count += 1
                    exit_reasons[exit_reason] = exit_reasons.get(exit_reason, 0) + 1

                    outcome = "WIN" if position['return_pct'] > 0 else "LOSS"

                    logger.info(
                        f"✓ Closed #{position['id']}: {position['brand']} ({position['ticker']}) "
                        f"| {position['days_held']} days | {position['return_pct']:+.1f}% | "
                        f"{exit_reason} | {outcome}"
                    )

        # Summary
        if closed_count > 0:
            logger.info(f"\n{closed_count} positions closed:")
            for reason, count in exit_reasons.items():
                logger.info(f"  {reason}: {count}")
        else:
            logger.info("No positions met exit criteria")

        # Show updated performance
        show_performance_summary(conn)

    finally:
        conn.close()


def show_performance_summary(conn):
    """
    Display current paper trading performance after exits
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    query = "SELECT * FROM v_paper_trading_performance"
    cursor.execute(query)
    stats = cursor.fetchone()
    cursor.close()

    if not stats:
        return

    logger.info("=" * 70)
    logger.info("UPDATED PAPER TRADING PERFORMANCE")
    logger.info("=" * 70)

    if stats['total_closed_trades'] > 0:
        logger.info(f"Total Closed: {stats['total_closed_trades']}")
        logger.info(f"Win Rate: {stats['win_rate_pct']:.1f}%")
        logger.info(f"Avg Return: {stats['avg_return_pct']:+.2f}%")
        logger.info(f"Best: {stats['best_return_pct']:+.2f}%")
        logger.info(f"Worst: {stats['worst_return_pct']:+.2f}%")

    if stats['open_positions'] > 0:
        logger.info(f"\nOpen: {stats['open_positions']}")
        logger.info(f"Avg Unrealized: {stats['avg_unrealized_return_pct']:+.2f}%")

    logger.info("=" * 70)

    # Check validation criteria
    if stats['total_closed_trades'] >= 10:
        logger.info("\n⚠️  VALIDATION CHECK:")

        meets_win_rate = stats['win_rate_pct'] >= 50
        meets_avg_return = stats['avg_return_pct'] >= 5

        if meets_win_rate and meets_avg_return:
            logger.info("✓ Phase 0 validation criteria MET!")
            logger.info("  ✓ Win rate ≥50% ✓")
            logger.info("  ✓ Avg return ≥5% ✓")
            logger.info("  → Consider moving to Phase 1 (expand infrastructure)")
        else:
            logger.info("✗ Phase 0 validation criteria NOT MET:")
            logger.info(f"  ✓ Win rate ≥50%: {'✓' if meets_win_rate else '✗'}")
            logger.info(f"  ✓ Avg return ≥5%: {'✓' if meets_avg_return else '✗'}")


def main():
    """Entry point"""
    logger.info("=" * 70)
    logger.info(f"Exit Checker - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Rules: {MAX_HOLD_DAYS} days | +{PROFIT_TARGET_PCT}% profit | {STOP_LOSS_PCT}% stop loss")
    logger.info("=" * 70)

    try:
        process_exits()

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    logger.info("✓ Exit check complete")


if __name__ == '__main__':
    main()
