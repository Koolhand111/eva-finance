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
import random
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import pandas as pd

logger = logging.getLogger(__name__)

# Rate limiting configuration
MAX_RETRIES = int(os.getenv("GOOGLE_TRENDS_MAX_RETRIES", "3"))
BASE_DELAY_SECONDS = float(os.getenv("GOOGLE_TRENDS_BASE_DELAY", "5.0"))  # Increased from 2.0
MAX_DELAY_SECONDS = float(os.getenv("GOOGLE_TRENDS_MAX_DELAY", "120.0"))  # Increased from 60.0
REQUEST_DELAY_SECONDS = float(os.getenv("GOOGLE_TRENDS_REQUEST_DELAY", "5.0"))  # Increased from 1.5

# Track last request time for global rate limiting
_last_request_time: float = 0.0

# Metrics tracking
_metrics = {
    'total_requests': 0,
    'successful_requests': 0,
    'failed_requests': 0,
    'rate_limited_requests': 0,
    'cache_hits': 0,
    'retry_attempts': 0,
}

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


def get_metrics() -> Dict:
    """Return current metrics for monitoring."""
    return _metrics.copy()


def reset_metrics():
    """Reset metrics (for testing)."""
    global _metrics
    _metrics = {
        'total_requests': 0,
        'successful_requests': 0,
        'failed_requests': 0,
        'rate_limited_requests': 0,
        'cache_hits': 0,
        'retry_attempts': 0,
    }


def _is_rate_limit_error(error: Exception) -> bool:
    """
    Detect if an exception is a rate limit (429) error.

    pytrends wraps HTTP errors in various ways, so we check multiple patterns.
    """
    error_str = str(error).lower()

    # Common rate limit indicators
    rate_limit_patterns = [
        '429',
        'too many requests',
        'rate limit',
        'quota exceeded',
        'temporarily blocked',
        'google returned a response with code 429',
    ]

    return any(pattern in error_str for pattern in rate_limit_patterns)


def _calculate_backoff_delay(attempt: int) -> float:
    """
    Calculate exponential backoff delay with jitter.

    Formula: min(base * 2^attempt + jitter, max_delay)
    Jitter: random 0-25% of calculated delay
    """
    delay = BASE_DELAY_SECONDS * (2 ** attempt)
    jitter = delay * random.uniform(0, 0.25)
    return min(delay + jitter, MAX_DELAY_SECONDS)


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
        """Initialize pytrends client with fresh session."""
        try:
            from pytrends.request import TrendReq

            # Create fresh TrendReq instance with clean session
            # Note: We handle retries ourselves in _fetch_with_retry()
            self.pytrends = TrendReq(
                hl='en-US',
                tz=360,  # US timezone offset
                timeout=(10, 30),  # (connect, read) timeouts
                requests_args={
                    'headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    }
                }
            )
            logger.info("[TRENDS] pytrends initialized successfully")

        except ImportError:
            logger.error("[TRENDS] pytrends library not installed - run: pip install pytrends")
            self.pytrends = None
        except Exception as e:
            logger.error(f"[TRENDS] Failed to initialize pytrends: {e}")
            self.pytrends = None

    def _reset_session(self):
        """Reset pytrends session to clear any rate limit state."""
        logger.info("[TRENDS] Resetting pytrends session...")
        self._init_pytrends()

    def _fetch_with_retry(self, brand: str, timeframe: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        Fetch Google Trends data with exponential backoff retry on rate limits.

        Returns:
            Tuple of (DataFrame or None, error_message or None)
        """
        global _last_request_time
        last_error = None

        for attempt in range(MAX_RETRIES + 1):  # +1 for initial attempt
            try:
                _metrics['total_requests'] += 1

                # Enforce minimum delay between ALL requests (global rate limiting)
                time_since_last = time.time() - _last_request_time
                if time_since_last < REQUEST_DELAY_SECONDS:
                    wait_time = REQUEST_DELAY_SECONDS - time_since_last
                    logger.debug(f"[TRENDS] Waiting {wait_time:.1f}s before request (rate limiting)")
                    time.sleep(wait_time)

                _last_request_time = time.time()

                self.pytrends.build_payload(
                    kw_list=[brand],
                    timeframe=timeframe,
                    geo='US',
                    gprop=''
                )

                df = self.pytrends.interest_over_time()
                _metrics['successful_requests'] += 1
                return df, None

            except Exception as e:
                last_error = e

                if _is_rate_limit_error(e):
                    _metrics['rate_limited_requests'] += 1

                    if attempt < MAX_RETRIES:
                        delay = _calculate_backoff_delay(attempt)
                        _metrics['retry_attempts'] += 1
                        logger.warning(
                            f"[TRENDS] Rate limited for '{brand}' (attempt {attempt + 1}/{MAX_RETRIES + 1}). "
                            f"Retrying in {delay:.1f}s with session reset..."
                        )
                        # Reset session on rate limit to clear any cookies/state
                        self._reset_session()
                        time.sleep(delay)
                        _last_request_time = time.time()  # Update after sleep
                        continue
                    else:
                        logger.error(
                            f"[TRENDS] Rate limit exceeded for '{brand}' after {MAX_RETRIES + 1} attempts"
                        )
                        _metrics['failed_requests'] += 1
                        return None, f"Rate limit exceeded after {MAX_RETRIES + 1} attempts"
                else:
                    # Non-rate-limit error - don't retry
                    _metrics['failed_requests'] += 1
                    logger.error(f"[TRENDS] API error for '{brand}': {e}")
                    return None, f"API error: {str(e)}"

        # Should not reach here, but safety fallback
        _metrics['failed_requests'] += 1
        return None, f"Failed after {MAX_RETRIES + 1} attempts: {str(last_error)}"

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
                _metrics['cache_hits'] += 1
                return cached

        # Validate inputs
        if not brand or not brand.strip():
            return self._error_result(brand, timeframe, "Empty brand name")

        if self.pytrends is None:
            return self._error_result(brand, timeframe, "pytrends not initialized")

        # Fetch trends data with retry logic
        logger.info(f"[TRENDS] Fetching data for '{brand}' ({timeframe})")

        df, error_msg = self._fetch_with_retry(brand, timeframe)

        if error_msg:
            return self._error_result(brand, timeframe, error_msg)

        if df is None or df.empty or brand not in df.columns:
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
            },
            'validation_status': 'completed'
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

    def _error_result(
        self,
        brand: str,
        timeframe: str,
        error_msg: str,
        pending: bool = False
    ) -> Dict:
        """
        Return neutral result when API fails.

        Args:
            brand: Brand name
            timeframe: Timeframe used
            error_msg: Error description
            pending: If True, marks as pending for retry (non-blocking)
        """
        return {
            'validates_signal': False,
            'search_interest': 0.0,
            'trend_direction': 'unknown',
            'confidence_boost': 0.0,
            'query_term': brand,
            'timeframe': timeframe,
            'error_message': error_msg,
            'raw_data': None,
            'validation_status': 'pending' if pending else 'failed'
        }


def log_metrics():
    """Log current metrics for monitoring."""
    m = get_metrics()
    total = m['total_requests']
    if total == 0:
        logger.info("[TRENDS-METRICS] No requests made yet")
        return

    success_rate = (m['successful_requests'] / total) * 100
    failure_rate = (m['failed_requests'] / total) * 100
    cache_rate = (m['cache_hits'] / (total + m['cache_hits'])) * 100 if (total + m['cache_hits']) > 0 else 0

    logger.info(
        f"[TRENDS-METRICS] Requests: {total} total, "
        f"{m['successful_requests']} success ({success_rate:.1f}%), "
        f"{m['failed_requests']} failed ({failure_rate:.1f}%), "
        f"{m['rate_limited_requests']} rate-limited, "
        f"{m['cache_hits']} cache hits ({cache_rate:.1f}%), "
        f"{m['retry_attempts']} retry attempts"
    )


def validate_brand_non_blocking(
    brand: str,
    validator: 'GoogleTrendsValidator' = None,
    use_cache: bool = True
) -> Dict:
    """
    Non-blocking validation that returns pending status on rate limit errors.

    Use this when trends validation should not block recommendation generation.
    Rate-limited requests return validation_status='pending' instead of failing.
    """
    if validator is None:
        validator = GoogleTrendsValidator()

    result = validator.validate_brand_signal(brand, use_cache=use_cache)

    # If rate-limited, mark as pending instead of failed
    if result.get('error_message') and 'rate limit' in result['error_message'].lower():
        result['validation_status'] = 'pending'
        logger.info(f"[TRENDS] {brand}: marked as pending (rate limited, will retry later)")

    return result


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
