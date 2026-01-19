"""
Helper script to research brand ticker mappings.

Usage:
    python brand_research.py "Nike"
    python brand_research.py --list-unmapped
    python brand_research.py --add "Nike" "NKE" --material
"""

import yfinance as yf
import argparse
from psycopg2.extras import RealDictCursor
from typing import Optional, Dict

from eva_common.db import get_connection

def research_ticker(ticker: str) -> Dict:
    """
    Research a ticker using yfinance

    Returns company info if valid ticker, None if not found
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        return {
            'ticker': ticker,
            'company_name': info.get('longName', 'N/A'),
            'exchange': info.get('exchange', 'N/A'),
            'market_cap': info.get('marketCap', 0),
            'sector': info.get('sector', 'N/A'),
            'current_price': info.get('currentPrice', 0),
            'valid': True
        }
    except Exception as e:
        return {
            'ticker': ticker,
            'valid': False,
            'error': str(e)
        }

def add_brand_mapping(
    brand: str,
    ticker: Optional[str],
    parent_company: Optional[str],
    material: bool,
    exchange: Optional[str],
    notes: Optional[str]
):
    """Add brand-ticker mapping to database"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO brand_ticker_mapping
                    (brand, ticker, parent_company, material, exchange, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (brand) DO UPDATE SET
                        ticker = EXCLUDED.ticker,
                        parent_company = EXCLUDED.parent_company,
                        material = EXCLUDED.material,
                        exchange = EXCLUDED.exchange,
                        notes = EXCLUDED.notes,
                        updated_at = NOW()
                """, (brand, ticker, parent_company, material, exchange, notes))
                conn.commit()

        print(f"✅ Added mapping: {brand} → {ticker or 'PRIVATE'}")

        # Verify ticker if provided
        if ticker:
            result = research_ticker(ticker)
            if result['valid']:
                print(f"   Company: {result['company_name']}")
                print(f"   Exchange: {result['exchange']}")
                print(f"   Market Cap: ${result['market_cap']:,}")
            else:
                print(f"   ⚠️  Warning: Could not verify ticker {ticker}")

    except Exception as e:
        print(f"❌ Error: {e}")

def list_unmapped_brands():
    """Show brands that need ticker mapping"""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM v_unmapped_brands LIMIT 20")
            brands = cur.fetchall()

    print("\n🔍 Brands Needing Research (Top 20):\n")
    print(f"{'Brand':<20} {'Signals':<10} {'Max Confidence':<15}")
    print("-" * 50)

    for b in brands:
        print(f"{b['brand']:<20} {b['signal_count']:<10} {b['max_confidence'] or 0.0:<15.4f}")

def main():
    parser = argparse.ArgumentParser(description='Research and add brand-ticker mappings')
    parser.add_argument('brand', nargs='?', help='Brand name to research')
    parser.add_argument('ticker', nargs='?', help='Stock ticker symbol')
    parser.add_argument('--list-unmapped', action='store_true', help='List unmapped brands')
    parser.add_argument('--parent', help='Parent company name')
    parser.add_argument('--material', action='store_true', help='Brand is material to parent revenue')
    parser.add_argument('--exchange', help='Stock exchange (NYSE, NASDAQ)')
    parser.add_argument('--notes', help='Research notes')
    parser.add_argument('--private', action='store_true', help='Mark as privately held (no ticker)')

    args = parser.parse_args()

    if args.list_unmapped:
        list_unmapped_brands()
    elif args.brand and (args.ticker or args.private):
        ticker = None if args.private else args.ticker
        add_brand_mapping(
            brand=args.brand,
            ticker=ticker,
            parent_company=args.parent,
            material=args.material,
            exchange=args.exchange,
            notes=args.notes
        )
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
