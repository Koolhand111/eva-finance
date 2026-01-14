"""
Test Suite for Google Trends Cross-Validation

Tests the GoogleTrendsValidator and TrendsCache modules with mocked pytrends responses.

Run tests:
    pytest eva_worker/tests/test_google_trends.py -v
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Import modules under test
import sys
sys.path.insert(0, '/app')
from eva_worker.google_trends import (
    GoogleTrendsValidator,
    TrendsCache,
    validate_brand_with_trends
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_pytrends():
    """Mock pytrends TrendReq object with sample data."""
    mock = MagicMock()

    # Generate sample date range (90 days)
    dates = pd.date_range(end=datetime.now(), periods=90, freq='D')

    # Create sample trends data
    df_rising = pd.DataFrame({
        'Nike': list(range(30, 60)) + list(range(60, 90)) + list(range(90, 120)),  # Rising trend
        'isPartial': [False] * 90
    }, index=dates)

    df_stable = pd.DataFrame({
        'Adidas': [50] * 90,  # Stable trend
        'isPartial': [False] * 90
    }, index=dates)

    df_falling = pd.DataFrame({
        'Reebok': list(range(90, 60, -1)) + list(range(60, 30, -1)) + list(range(30, 0, -1)),  # Falling trend
        'isPartial': [False] * 90
    }, index=dates)

    df_empty = pd.DataFrame()

    mock.interest_over_time.side_effect = lambda: df_rising

    return mock, {
        'rising': df_rising,
        'stable': df_stable,
        'falling': df_falling,
        'empty': df_empty
    }


@pytest.fixture
def validator():
    """Create GoogleTrendsValidator instance."""
    return GoogleTrendsValidator(cache_ttl_hours=1)


@pytest.fixture
def cache():
    """Create TrendsCache instance and clear it."""
    c = TrendsCache(ttl_hours=1)
    c.clear()
    return c


# ============================================================================
# CACHE TESTS
# ============================================================================

def test_cache_miss(cache):
    """Test cache returns None on miss."""
    result = cache.get('Nike')
    assert result is None


def test_cache_hit(cache):
    """Test cache returns data on hit."""
    test_data = {'validates_signal': True, 'confidence_boost': 0.10}
    cache.set('Nike', test_data)

    result = cache.get('Nike')
    assert result is not None
    assert result['validates_signal'] is True
    assert result['confidence_boost'] == 0.10


def test_cache_expiration(cache):
    """Test cache expires after TTL."""
    cache_short = TrendsCache(ttl_hours=0.001)  # ~3.6 seconds
    cache_short.set('Nike', {'data': 'test'})

    # Immediate retrieval should work
    assert cache_short.get('Nike') is not None

    # Wait for expiration
    import time
    time.sleep(4)

    # Should be expired now
    assert cache_short.get('Nike') is None


def test_cache_size(cache):
    """Test cache size tracking."""
    assert cache.size() == 0

    cache.set('Nike', {'data': 1})
    assert cache.size() == 1

    cache.set('Adidas', {'data': 2})
    assert cache.size() == 2

    cache.clear()
    assert cache.size() == 0


def test_cache_case_insensitive(cache):
    """Test cache keys are case-insensitive."""
    cache.set('Nike', {'data': 'test'})

    assert cache.get('nike') is not None
    assert cache.get('NIKE') is not None
    assert cache.get('NiKe') is not None


# ============================================================================
# VALIDATOR CORE TESTS
# ============================================================================

def test_validate_empty_brand(validator):
    """Test validation fails gracefully with empty brand."""
    result = validator.validate_brand_signal('')

    assert result['validates_signal'] is False
    assert result['error_message'] == 'Empty brand name'
    assert result['confidence_boost'] == 0.0


def test_validate_brand_signal_success(validator, mock_pytrends):
    """Test successful validation with rising trend."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['rising']

        result = validator.validate_brand_signal('Nike', use_cache=False)

        assert 'validates_signal' in result
        assert 'search_interest' in result
        assert 'trend_direction' in result
        assert 'confidence_boost' in result
        assert result['query_term'] == 'Nike'
        assert result['timeframe'] == 'today 3-m'
        assert result['error_message'] is None


def test_validate_brand_no_data(validator, mock_pytrends):
    """Test validation handles empty pytrends response."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['empty']

        result = validator.validate_brand_signal('UnknownBrand', use_cache=False)

        assert result['validates_signal'] is False
        assert 'No search data' in result['error_message']


# ============================================================================
# TREND DIRECTION TESTS
# ============================================================================

def test_detect_rising_trend(validator, mock_pytrends):
    """Test detection of rising trend (>20% increase)."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['rising']

        result = validator.validate_brand_signal('Nike', use_cache=False)

        assert result['trend_direction'] == 'rising'


def test_detect_stable_trend(validator, mock_pytrends):
    """Test detection of stable trend (within ±20%)."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['stable']

        result = validator.validate_brand_signal('Adidas', use_cache=False)

        assert result['trend_direction'] == 'stable'


def test_detect_falling_trend(validator, mock_pytrends):
    """Test detection of falling trend (<-20% decrease)."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['falling']

        result = validator.validate_brand_signal('Reebok', use_cache=False)

        assert result['trend_direction'] == 'falling'


# ============================================================================
# CONFIDENCE BOOST TESTS
# ============================================================================

def test_confidence_boost_rising(validator, mock_pytrends):
    """Test rising trend gives positive boost."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['rising']

        result = validator.validate_brand_signal('Nike', use_cache=False)

        assert result['confidence_boost'] > 0
        assert result['confidence_boost'] <= 0.15  # Max boost


def test_confidence_boost_stable(validator, mock_pytrends):
    """Test stable trend gives modest boost."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['stable']

        result = validator.validate_brand_signal('Adidas', use_cache=False)

        assert result['confidence_boost'] > 0
        assert result['confidence_boost'] <= 0.05  # Max modest boost


def test_confidence_boost_falling(validator, mock_pytrends):
    """Test falling trend gives penalty."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['falling']

        result = validator.validate_brand_signal('Reebok', use_cache=False)

        assert result['confidence_boost'] < 0
        assert result['confidence_boost'] >= -0.10  # Max penalty


# ============================================================================
# SIGNAL VALIDATION TESTS
# ============================================================================

def test_validates_signal_rising_high_interest(validator, mock_pytrends):
    """Test rising trend with high interest validates signal."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['rising']

        result = validator.validate_brand_signal('Nike', use_cache=False)

        # Rising trend with adequate interest should validate
        assert result['validates_signal'] is True


def test_does_not_validate_falling(validator, mock_pytrends):
    """Test falling trend does not validate signal."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['falling']

        result = validator.validate_brand_signal('Reebok', use_cache=False)

        # Falling trend should not validate
        assert result['validates_signal'] is False


# ============================================================================
# CACHING INTEGRATION TESTS
# ============================================================================

def test_cache_integration(validator, mock_pytrends):
    """Test validator uses cache on second call."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['rising']

        # First call - should hit API
        result1 = validator.validate_brand_signal('Nike', use_cache=True)
        assert mock_trends.build_payload.call_count == 1

        # Second call - should use cache
        result2 = validator.validate_brand_signal('Nike', use_cache=True)
        assert mock_trends.build_payload.call_count == 1  # Not called again

        # Results should match
        assert result1['trend_direction'] == result2['trend_direction']
        assert result1['confidence_boost'] == result2['confidence_boost']


def test_cache_bypass(validator, mock_pytrends):
    """Test validator bypasses cache when use_cache=False."""
    mock_trends, data = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.return_value = data['rising']

        # First call with cache
        validator.validate_brand_signal('Nike', use_cache=True)
        assert mock_trends.build_payload.call_count == 1

        # Second call without cache
        validator.validate_brand_signal('Nike', use_cache=False)
        assert mock_trends.build_payload.call_count == 2  # Called again


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================

def test_pytrends_api_error(validator, mock_pytrends):
    """Test graceful handling of pytrends API errors."""
    mock_trends, _ = mock_pytrends

    with patch.object(validator, 'pytrends', mock_trends):
        mock_trends.interest_over_time.side_effect = Exception("API rate limit exceeded")

        result = validator.validate_brand_signal('Nike', use_cache=False)

        # Should return error result, not crash
        assert result['validates_signal'] is False
        assert 'API error' in result['error_message']
        assert result['confidence_boost'] == 0.0


def test_pytrends_not_initialized():
    """Test validator handles missing pytrends library."""
    validator_no_pytrends = GoogleTrendsValidator()
    validator_no_pytrends.pytrends = None

    result = validator_no_pytrends.validate_brand_signal('Nike')

    assert result['validates_signal'] is False
    assert 'not initialized' in result['error_message']


# ============================================================================
# CONVENIENCE FUNCTION TEST
# ============================================================================

def test_convenience_function(mock_pytrends):
    """Test module-level validate_brand_with_trends function."""
    mock_trends, data = mock_pytrends

    with patch('eva_worker.google_trends.GoogleTrendsValidator') as MockValidator:
        mock_instance = MockValidator.return_value
        mock_instance.validate_brand_signal.return_value = {
            'validates_signal': True,
            'confidence_boost': 0.10,
            'trend_direction': 'rising'
        }

        result = validate_brand_with_trends('Nike')

        assert result['validates_signal'] is True
        assert result['confidence_boost'] == 0.10
        MockValidator.assert_called_once()


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
