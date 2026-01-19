#!/usr/bin/env python3
"""
Test script for brand_mapper_service.py

Validates FMP API integration with example brands:
- Duluth Trading → DLTH (pure-play, material)
- MAC Cosmetics → EL (subsidiary of Estée Lauder)
- Covergirl → COTY (subsidiary of Coty Inc)

Usage:
    # From eva-finance directory:
    python -m eva_worker.test_brand_mapper

    # Or with docker:
    docker exec eva_worker python -m eva_worker.test_brand_mapper
"""

import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def test_fmp_api_connection():
    """Test that FMP API is reachable and key is valid"""
    import requests

    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        logger.error("FMP_API_KEY not set - skipping API test")
        return False

    try:
        # Use stable API endpoint (v3/search is legacy/deprecated)
        url = f"https://financialmodelingprep.com/stable/search-name"
        params = {"query": "Apple", "limit": 1, "apikey": api_key}
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            logger.info(f"✓ FMP API connection successful - got {len(data)} results")
            return True
        elif response.status_code == 401:
            logger.error("✗ FMP API key invalid or expired")
            return False
        elif response.status_code == 429:
            logger.warning("⚠ FMP API rate limited - try again later")
            return False
        else:
            logger.error(f"✗ FMP API returned status {response.status_code}")
            return False

    except Exception as e:
        logger.error(f"✗ FMP API connection failed: {e}")
        return False


def test_brand_mapping():
    """Test brand mapping with known examples"""
    from eva_worker.brand_mapper_service import BrandMapper, MappingStatus

    mapper = BrandMapper()

    test_cases = [
        {
            "brand": "Duluth Trading",
            "expected_ticker": "DLTH",
            "expected_material": True,
            "notes": "Pure-play retailer"
        },
        {
            "brand": "MAC Cosmetics",
            "expected_ticker": "EL",  # Estée Lauder
            "expected_material": False,  # Subsidiary
            "notes": "Should map to parent Estée Lauder"
        },
        {
            "brand": "Covergirl",
            "expected_ticker": "COTY",  # Coty Inc
            "expected_material": False,  # Subsidiary
            "notes": "Should map to parent Coty"
        },
        {
            "brand": "Patagonia",
            "expected_ticker": None,  # Private
            "expected_material": False,
            "notes": "Private company - should not map"
        },
    ]

    results = []
    for tc in test_cases:
        brand = tc["brand"]
        logger.info(f"\nTesting: {brand}")
        logger.info(f"  Notes: {tc['notes']}")

        result = mapper.map_brand(brand)

        # Check status
        status_ok = result.status in (
            MappingStatus.ALREADY_MAPPED,
            MappingStatus.MAPPED_SUCCESS,
            MappingStatus.NOT_FOUND,
            MappingStatus.AMBIGUOUS,
        )

        logger.info(f"  Status: {result.status.value}")
        logger.info(f"  Ticker: {result.ticker}")
        logger.info(f"  Parent: {result.parent_company}")
        logger.info(f"  Material: {result.material}")

        if result.candidates:
            logger.info(f"  Candidates: {len(result.candidates)}")
            for c in result.candidates[:3]:
                logger.info(f"    - {c.get('symbol')}: {c.get('name')}")

        results.append({
            "brand": brand,
            "status": result.status.value,
            "ticker": result.ticker,
            "expected_ticker": tc["expected_ticker"],
            "match": result.ticker == tc["expected_ticker"],
        })

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)

    for r in results:
        match_str = "✓" if r["match"] else "✗"
        logger.info(
            f"{match_str} {r['brand']}: {r['ticker']} "
            f"(expected: {r['expected_ticker']}) - {r['status']}"
        )

    # Print metrics
    metrics = mapper.get_metrics()
    logger.info("\nMetrics:")
    for k, v in metrics.items():
        logger.info(f"  {k}: {v}")

    return all(r["match"] for r in results)


def test_database_integration():
    """Test that mappings are persisted to database"""
    from eva_common.db import get_connection
    from psycopg2.extras import RealDictCursor

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'brand_ticker_mapping'
                    )
                """)
                exists = cur.fetchone()["exists"]

                if not exists:
                    logger.warning("⚠ brand_ticker_mapping table does not exist")
                    logger.info("  Run migration 009_brand_ticker_mapping.sql first")
                    return False

                # Count mappings
                cur.execute("SELECT COUNT(*) as count FROM brand_ticker_mapping")
                count = cur.fetchone()["count"]
                logger.info(f"✓ Database connected - {count} mappings in table")

                # Show recent mappings
                cur.execute("""
                    SELECT brand, ticker, material, notes
                    FROM brand_ticker_mapping
                    ORDER BY updated_at DESC
                    LIMIT 5
                """)
                recent = cur.fetchall()

                if recent:
                    logger.info("\nRecent mappings:")
                    for r in recent:
                        logger.info(
                            f"  {r['brand']} → {r['ticker'] or 'PRIVATE'} "
                            f"(material={r['material']})"
                        )

                return True

    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}")
        return False


def main():
    logger.info("=" * 60)
    logger.info("Brand Mapper Service Test")
    logger.info("=" * 60)

    # Test 1: Database connection
    logger.info("\n[1/3] Testing database integration...")
    db_ok = test_database_integration()

    # Test 2: FMP API connection
    logger.info("\n[2/3] Testing FMP API connection...")
    api_ok = test_fmp_api_connection()

    # Test 3: Brand mapping (only if API works)
    if api_ok:
        logger.info("\n[3/3] Testing brand mapping...")
        mapping_ok = test_brand_mapping()
    else:
        logger.warning("\n[3/3] Skipping brand mapping test - API not available")
        mapping_ok = False

    # Final summary
    logger.info("\n" + "=" * 60)
    logger.info("FINAL RESULTS")
    logger.info("=" * 60)
    logger.info(f"Database: {'✓ PASS' if db_ok else '✗ FAIL'}")
    logger.info(f"FMP API:  {'✓ PASS' if api_ok else '✗ FAIL'}")
    logger.info(f"Mapping:  {'✓ PASS' if mapping_ok else '✗ FAIL/SKIPPED'}")

    return 0 if (db_ok and api_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
