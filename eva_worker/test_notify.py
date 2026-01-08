#!/usr/bin/env python3
"""
Test script for notification polling.

Usage:
    python test_notify.py

Environment variables:
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    NTFY_URL
"""
import sys
import logging
from pathlib import Path

# Add eva_worker package to path
sys.path.insert(0, str(Path(__file__).parent))

from eva_worker.notify import poll_and_notify

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    print("=" * 60)
    print("EVA-Finance Notification Test")
    print("=" * 60)
    print()

    try:
        result = poll_and_notify()
        print()
        print("=" * 60)
        print(f"Results: {result['sent']} sent, {result['failed']} failed")
        print("=" * 60)

        if result["sent"] == 0 and result["failed"] == 0:
            print("\n✓ No pending notifications found (this is normal)")
        elif result["failed"] > 0:
            print("\n⚠ Some notifications failed. Check logs above.")
            sys.exit(1)
        else:
            print("\n✓ All notifications sent successfully")

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
