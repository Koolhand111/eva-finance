"""
Google Trends Cross-Validation for EVA-Finance

Validates Reddit social signals by checking if Google search interest supports the trend.
Reduces false positives by requiring both social momentum AND search behavior confirmation.

Usage:
    validator = GoogleTrendsValidator()
    result = validator.validate_brand_signal('Nike')

    if result['validates_signal']:
        confidence_boost = result['confidence_boost']  # Apply to base confidence
"""

import os
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)

# In-memory cache (no Redis infrastructure)
_trends_cache: Dict[str, Dict] = {}


class TrendsCache:
    """
    In-memory cache for Google Trends data with TTL expiration.

    Uses simple dict storage since Redis infrastructure is not available.
    Cache key format: brand name (lowercase)
    """

    def __init__(self, ttl_hours: int = 24):
        self.ttl_hours = ttl_hours
        logger.info(f"[TRENDS-CACHE] Initialized with {ttl_hours}h TTL")

    def get(self, brand: str) -> Optional[Dict]:
        """Retrieve cached validation result if not expired."""
        brand_key = brand.lower().strip()

        if brand_key not in _trends_cache:
            logger.debug(f"[TRENDS-CACHE] MISS: {brand}")
            return None

        entry = _trends_cache[brand_key]
        expires_at = entry['expires_at']

        if datetime.now() >= expires_at:
            # Expired - remove from cache
            del _trends_cache[brand_key]
            logger.debug(f"[TRENDS-CACHE] EXPIRED: {brand}")
            return None

        logger.info(f"[TRENDS-CACHE] HIT: {brand} (expires {expires_at.strftime('%Y-%m-%d %H:%M')})")
        return entry['data']

    def set(self, brand: str, data: Dict):
        """Store validation result with TTL expiration."""
        brand_key = brand.lower().strip()
        expires_at = datetime.now() + timedelta(hours=self.ttl_hours)

        _trends_cache[brand_key] = {
            'data': data,
            'expires_at': expires_at,
            'cached_at': datetime.now()
        }

        logger.info(f"[TRENDS-CACHE] SET: {brand} (expires {expires_at.strftime('%Y-%m-%d %H:%M')})")

    def clear(self):
        """Clear entire cache (for testing)."""
        _trends_cache.clear()
        logger.info("[TRENDS-CACHE] Cleared all entries")

    def size(self) -> int:
        """Return number of cached entries."""
        return len(_trends_cache)


class GoogleTrendsValidator:
    """
    Validates brand signals using Google Trends search interest data.

    Methodology:
    1. Fetch 3-month search interest from Google Trends
    2. Calculate recent interest (last 30 days vs full period average)
    3. Detect trend direction (rising/stable/falling)
    4. Apply confidence boost/penalty based on search behavior

    Conservative approach: Prefers false negatives over false positives.
    """

    def __init__(self, cache_ttl_hours: int = 24):
        """
        Initialize validator with retry logic and caching.

        Args:
            cache_ttl_hours: How long to cache results (default 24h)
        """
        self.cache = TrendsCache(ttl_hours=cache_ttl_hours)
        self.pytrends = None
        self._init_pytrends()

    def _init_pytrends(self):
        """Initialize pytrends with retry logic."""
        try:
            from pytrends.request import TrendReq

            # Initialize (simpler config due to urllib3 compatibility)
            self.pytrends = TrendReq(
                hl='en-US',
                tz=360,  # US timezone offset
                timeout=(10, 25)  # (connect, read) timeouts
            )
            logger.info("[TRENDS] pytrends initialized successfully")

        except ImportError:
            logger.error("[TRENDS] pytrends library not installed - run: pip install pytrends")
            self.pytrends = None
        except Exception as e:
            logger.error(f"[TRENDS] Failed to initialize pytrends: {e}")
            self.pytrends = None

    def validate_brand_signal(
        self,
        brand: str,
        timeframe: str = 'today 3-m',
        use_cache: bool = True
    ) -> Dict:
        """
        Validate if Google Trends supports the Reddit signal for this brand.

        Args:
            brand: Brand name to validate (e.g., 'Nike', 'Hoka')
            timeframe: Google Trends timeframe (default: last 3 months)
            use_cache: Whether to use cached results (default: True)

        Returns:
            {
                'validates_signal': bool,           # True if trends support the signal
                'search_interest': float,           # 0.0-1.0 normalized interest
                'trend_direction': str,             # 'rising'|'stable'|'falling'|'unknown'
                'confidence_boost': float,          # -0.1000 to +0.1500
                'query_term': str,                  # What we searched for
                'timeframe': str,                   # Timeframe used
                'error_message': str | None,        # Error details if failed
                'raw_data': dict | None             # Full pytrends response
            }
        """

        # Check cache first
        if use_cache:
            cached = self.cache.get(brand)
            if cached is not None:
                return cached

        # Validate inputs
        if not brand or not brand.strip():
            return self._error_result(brand, timeframe, "Empty brand name")

        if self.pytrends is None:
            return self._error_result(brand, timeframe, "pytrends not initialized")

        # Fetch trends data
        try:
            logger.info(f"[TRENDS] Fetching data for '{brand}' ({timeframe})")

            # Build payload and fetch interest over time
            self.pytrends.build_payload(
                kw_list=[brand],
                timeframe=timeframe,
                geo='US',  # Focus on US market
                gprop=''   # Web search (not images, news, etc.)
            )

            df = self.pytrends.interest_over_time()

            if df.empty or brand not in df.columns:
                logger.warning(f"[TRENDS] No data returned for '{brand}'")
                return self._error_result(brand, timeframe, f"No search data for '{brand}'")

            # Calculate metrics
            search_interest = self._calculate_recent_interest(df, brand)
            trend_direction = self._detect_trend_direction(df, brand)
            confidence_boost = self._calculate_confidence_boost(search_interest, trend_direction)
            validates_signal = self._should_validate(search_interest, trend_direction)

            result = {
                'validates_signal': validates_signal,
                'search_interest': round(search_interest, 4),
                'trend_direction': trend_direction,
                'confidence_boost': round(confidence_boost, 4),
                'query_term': brand,
                'timeframe': timeframe,
                'error_message': None,
                'raw_data': {
                    'values': df[brand].tolist(),
                    'dates': df.index.strftime('%Y-%m-%d').tolist(),
                    'mean': float(df[brand].mean()),
                    'std': float(df[brand].std())
                }
            }

            logger.info(
                f"[TRENDS] ✓ {brand}: interest={search_interest:.2f}, "
                f"direction={trend_direction}, boost={confidence_boost:+.4f}, "
                f"validates={validates_signal}"
            )

            # Cache successful result
            if use_cache:
                self.cache.set(brand, result)

            return result

        except Exception as e:
            error_msg = f"API error: {str(e)}"
            logger.error(f"[TRENDS] ✗ Failed to fetch '{brand}': {e}")
            return self._error_result(brand, timeframe, error_msg)

    def _calculate_recent_interest(self, df: pd.DataFrame, brand: str) -> float:
        """
        Calculate normalized search interest (last 30 days vs full period).

        Returns:
            Float between 0.0 and 1.0, where:
            - 1.0 = Last 30 days had 2x the average search volume
            - 0.5 = Last 30 days matched average
            - 0.0 = No search interest
        """
        try:
            values = df[brand].values

            if len(values) < 30:
                # Not enough data - use what we have
                recent_avg = values.mean()
                full_avg = recent_avg
            else:
                # Compare last 30 days to full period
                recent_avg = values[-30:].mean()
                full_avg = values.mean()

            if full_avg == 0:
                return 0.0

            # Normalize: ratio of recent to full average
            # Clamp to 0.0-1.0 range (cap at 2x = 100% interest)
            ratio = recent_avg / full_avg
            normalized = min(ratio / 2.0, 1.0)

            return float(normalized)

        except Exception as e:
            logger.warning(f"[TRENDS] Error calculating interest for {brand}: {e}")
            return 0.0

    def _detect_trend_direction(self, df: pd.DataFrame, brand: str) -> str:
        """
        Detect if search interest is rising, stable, or falling.

        Logic:
        - Rising: Last 30 days > previous 30 days by >20%
        - Falling: Last 30 days < previous 30 days by >20%
        - Stable: Within ±20%
        - Unknown: Insufficient data

        Returns:
            'rising' | 'stable' | 'falling' | 'unknown'
        """
        try:
            values = df[brand].values

            if len(values) < 60:
                # Not enough data for comparison
                return 'unknown'

            last_30d = values[-30:].mean()
            prev_30d = values[-60:-30].mean()

            if prev_30d == 0:
                return 'unknown'

            change_pct = ((last_30d - prev_30d) / prev_30d) * 100

            if change_pct > 20:
                return 'rising'
            elif change_pct < -20:
                return 'falling'
            else:
                return 'stable'

        except Exception as e:
            logger.warning(f"[TRENDS] Error detecting direction for {brand}: {e}")
            return 'unknown'

    def _calculate_confidence_boost(self, search_interest: float, trend_direction: str) -> float:
        """
        Calculate confidence score adjustment based on trends data.

        Logic:
        - Rising trend + high interest: +15% max boost
        - Stable trend + adequate interest: +5% boost
        - Falling trend: -7.5% penalty
        - Unknown or low interest: 0% (neutral)

        Returns:
            Float between -0.1000 and +0.1500
        """
        # Low search interest = neutral (don't penalize lack of search visibility)
        if search_interest < 0.20:
            return 0.0

        if trend_direction == 'rising':
            # Rising trend: boost scales with search interest
            # Max boost of +0.15 when interest = 1.0
            boost = 0.15 * search_interest
            return min(boost, 0.15)

        elif trend_direction == 'stable':
            # Stable trend with adequate search interest: modest boost
            boost = 0.05 * search_interest
            return min(boost, 0.05)

        elif trend_direction == 'falling':
            # Falling trend: penalty
            # Max penalty of -0.075 when interest is high but declining
            penalty = -0.075 * search_interest
            return max(penalty, -0.10)

        else:  # unknown
            return 0.0

    def _should_validate(self, search_interest: float, trend_direction: str) -> bool:
        """
        Decide if Google Trends validates the Reddit signal.

        Conservative logic: Only validate if trends clearly support the signal.

        Validates if:
        - Rising trend with adequate interest (>0.30)
        - Stable trend with strong interest (>0.50)

        Does NOT validate if:
        - Falling trend (contradicts social signal)
        - Low/unknown search interest
        """
        if trend_direction == 'rising' and search_interest >= 0.30:
            return True

        if trend_direction == 'stable' and search_interest >= 0.50:
            return True

        return False

    def _error_result(self, brand: str, timeframe: str, error_msg: str) -> Dict:
        """Return neutral result when API fails (conservative fallback)."""
        return {
            'validates_signal': False,
            'search_interest': 0.0,
            'trend_direction': 'unknown',
            'confidence_boost': 0.0,
            'query_term': brand,
            'timeframe': timeframe,
            'error_message': error_msg,
            'raw_data': None
        }


# Module-level convenience function
def validate_brand_with_trends(brand: str, use_cache: bool = True) -> Dict:
    """
    Convenience function for validating a single brand.

    Usage:
        result = validate_brand_with_trends('Nike')
        if result['validates_signal']:
            print(f"Boost: {result['confidence_boost']}")
    """
    validator = GoogleTrendsValidator()
    return validator.validate_brand_signal(brand, use_cache=use_cache)


if __name__ == '__main__':
    # Standalone test mode
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    test_brands = sys.argv[1:] if len(sys.argv) > 1 else ['Nike', 'Hoka', 'Lululemon']

    print("=" * 70)
    print("Google Trends Validation Test")
    print("=" * 70)

    validator = GoogleTrendsValidator()

    for brand in test_brands:
        print(f"\nTesting: {brand}")
        print("-" * 70)

        result = validator.validate_brand_signal(brand)

        print(f"  Validates Signal: {result['validates_signal']}")
        print(f"  Search Interest:  {result['search_interest']:.4f}")
        print(f"  Trend Direction:  {result['trend_direction']}")
        print(f"  Confidence Boost: {result['confidence_boost']:+.4f}")

        if result['error_message']:
            print(f"  Error: {result['error_message']}")

    print("\n" + "=" * 70)
    print(f"Cache size: {validator.cache.size()} entries")
