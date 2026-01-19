"""
Brand Mapper Service - Automated brand-to-ticker mapping via FMP API

This service automatically looks up and populates brand-to-ticker mappings
when new brands appear in signals. It integrates with Financial Modeling Prep
API to search for company/ticker information.

Usage:
    from eva_worker.brand_mapper_service import ensure_brand_mapped, BrandMapper

    # Single brand lookup
    result = ensure_brand_mapped("Duluth Trading")

    # Batch processing
    mapper = BrandMapper()
    mapper.ensure_brands_mapped(["Duluth Trading", "MAC Cosmetics", "Covergirl"])
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum

import requests
from psycopg2.extras import RealDictCursor

from eva_common.db import get_connection
from eva_common.config import app_settings

# Use centralized config with fallback to env var
FMP_API_KEY = app_settings.fmp_api_key or os.getenv("FMP_API_KEY")
FMP_ENABLED = app_settings.fmp_enabled
FMP_RATE_LIMIT_MS = app_settings.fmp_rate_limit_ms

logger = logging.getLogger(__name__)


class MappingStatus(Enum):
    """Status of a brand mapping attempt"""
    ALREADY_MAPPED = "already_mapped"
    MAPPED_SUCCESS = "mapped_success"
    NOT_FOUND = "not_found"
    API_ERROR = "api_error"
    AMBIGUOUS = "ambiguous"
    RATE_LIMITED = "rate_limited"


@dataclass
class MappingResult:
    """Result of a brand mapping attempt"""
    brand: str
    status: MappingStatus
    ticker: Optional[str] = None
    parent_company: Optional[str] = None
    material: bool = False
    exchange: Optional[str] = None
    notes: Optional[str] = None
    candidates: Optional[List[Dict[str, Any]]] = None


class BrandMapper:
    """
    Service for mapping brand names to stock tickers via FMP API.

    Features:
    - Caches lookups in brand_ticker_mapping table
    - Handles API rate limits gracefully
    - Logs unmapped brands for manual review
    - Non-blocking: failures don't crash the pipeline
    """

    # Use stable API endpoint (v3/search is legacy and deprecated as of Aug 2025)
    FMP_BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the BrandMapper.

        Args:
            api_key: FMP API key. If not provided, uses centralized config
        """
        self.api_key = api_key or FMP_API_KEY
        self.enabled = FMP_ENABLED

        if not self.api_key:
            logger.warning("[BrandMapper] No FMP_API_KEY configured - API lookups disabled")
        elif not self.enabled:
            logger.info("[BrandMapper] FMP API disabled via config")

        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = FMP_RATE_LIMIT_MS / 1000.0  # Convert ms to seconds

        # Metrics
        self._metrics = {
            "lookups": 0,
            "cache_hits": 0,
            "api_calls": 0,
            "api_successes": 0,
            "api_failures": 0,
            "ambiguous": 0,
            "not_found": 0,
        }

    def _rate_limit(self) -> None:
        """Enforce rate limiting between API calls"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _search_fmp(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """
        Search FMP API for companies matching the query.

        Args:
            query: Brand or company name to search

        Returns:
            List of matching companies or None if API error
        """
        if not self.api_key or not self.enabled:
            logger.debug("[BrandMapper] API disabled or no key - skipping FMP search")
            return None

        self._rate_limit()
        self._metrics["api_calls"] += 1

        try:
            url = f"{self.FMP_BASE_URL}/search-name"
            params = {
                "query": query,
                "limit": 10,
                "apikey": self.api_key,
            }

            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 429:
                logger.warning(f"[BrandMapper] Rate limited by FMP API for query: {query}")
                self._metrics["api_failures"] += 1
                return None

            if response.status_code != 200:
                logger.error(
                    f"[BrandMapper] FMP API error {response.status_code} "
                    f"for query: {query}"
                )
                self._metrics["api_failures"] += 1
                return None

            results = response.json()
            self._metrics["api_successes"] += 1

            logger.debug(f"[BrandMapper] FMP returned {len(results)} results for: {query}")
            return results

        except requests.exceptions.Timeout:
            logger.warning(f"[BrandMapper] FMP API timeout for query: {query}")
            self._metrics["api_failures"] += 1
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"[BrandMapper] FMP API request failed for {query}: {e}")
            self._metrics["api_failures"] += 1
            return None
        except Exception as e:
            logger.error(f"[BrandMapper] Unexpected error in FMP search for {query}: {e}")
            self._metrics["api_failures"] += 1
            return None

    def _is_brand_mapped(self, brand: str) -> Optional[Dict[str, Any]]:
        """
        Check if brand already exists in brand_ticker_mapping table.

        Args:
            brand: Brand name to check

        Returns:
            Existing mapping record or None
        """
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT brand, ticker, parent_company, material, exchange, notes
                    FROM brand_ticker_mapping
                    WHERE LOWER(TRIM(brand)) = LOWER(TRIM(%s))
                """, (brand,))
                return cur.fetchone()

    def _determine_materiality(
        self,
        brand_name: str,
        company_name: str
    ) -> bool:
        """
        Heuristic to determine if brand is material to parent company.

        Logic:
        - If brand name ≈ company name → likely pure-play, material=true
        - Otherwise → likely subsidiary, material=false (needs manual review)

        Args:
            brand_name: The brand being mapped
            company_name: Company name from FMP API

        Returns:
            True if brand appears material to company
        """
        brand_lower = brand_name.lower().strip()
        company_lower = company_name.lower().strip()

        # Remove common suffixes for comparison
        suffixes = [
            " inc", " inc.", " corp", " corp.", " co", " co.",
            " ltd", " ltd.", " llc", " plc", " holdings", " group",
            " company", " corporation", " international", " intl"
        ]

        brand_clean = brand_lower
        company_clean = company_lower

        for suffix in suffixes:
            brand_clean = brand_clean.replace(suffix, "")
            company_clean = company_clean.replace(suffix, "")

        brand_clean = brand_clean.strip()
        company_clean = company_clean.strip()

        # Check for strong match
        if brand_clean == company_clean:
            return True

        # Check if brand is a significant substring of company
        if brand_clean in company_clean or company_clean in brand_clean:
            # Only consider material if they're very similar
            len_ratio = len(brand_clean) / max(len(company_clean), 1)
            if len_ratio > 0.6:
                return True

        # Check word overlap
        brand_words = set(brand_clean.split())
        company_words = set(company_clean.split())

        if brand_words and company_words:
            overlap = brand_words & company_words
            overlap_ratio = len(overlap) / len(brand_words)
            if overlap_ratio >= 0.5:
                return True

        return False

    def _select_best_match(
        self,
        brand: str,
        candidates: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Select the best matching company from FMP search results.

        Scoring criteria:
        - Exact name match gets highest priority
        - US exchanges (NYSE, NASDAQ) preferred over foreign
        - Larger companies preferred (as proxy for liquidity)

        Args:
            brand: Original brand name
            candidates: List of FMP search results

        Returns:
            Best matching candidate or None if no good match
        """
        if not candidates:
            return None

        brand_lower = brand.lower().strip()

        # Filter to common US exchanges
        preferred_exchanges = {"NYSE", "NASDAQ", "AMEX", "NYSE American"}

        scored_candidates = []
        for c in candidates:
            score = 0
            name = (c.get("name") or "").lower()
            symbol = c.get("symbol", "")
            exchange = c.get("exchangeShortName") or c.get("exchange", "")

            # Name matching
            if brand_lower in name or name in brand_lower:
                score += 50
            if brand_lower == name:
                score += 100

            # Check individual words
            brand_words = set(brand_lower.split())
            name_words = set(name.split())
            word_overlap = len(brand_words & name_words)
            score += word_overlap * 20

            # Exchange preference
            if exchange in preferred_exchanges:
                score += 30

            # Penalize OTC/pink sheets
            if "OTC" in exchange or "PINK" in exchange:
                score -= 50

            if score > 0:
                scored_candidates.append((score, c))

        if not scored_candidates:
            return None

        # Sort by score descending
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        # Check for ambiguity - if top 2 scores are close, it's ambiguous
        if len(scored_candidates) >= 2:
            top_score = scored_candidates[0][0]
            second_score = scored_candidates[1][0]
            if second_score >= top_score * 0.8:  # Within 20% of top score
                return None  # Ambiguous, needs manual review

        return scored_candidates[0][1]

    def _insert_mapping(
        self,
        brand: str,
        ticker: Optional[str],
        parent_company: Optional[str],
        material: bool,
        exchange: Optional[str],
        notes: Optional[str],
    ) -> bool:
        """
        Insert or update brand mapping in database.

        Args:
            brand: Brand name
            ticker: Stock ticker (None if private)
            parent_company: Parent company name
            material: Whether brand is material to parent
            exchange: Stock exchange
            notes: Research notes

        Returns:
            True if successful
        """
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

            logger.info(
                f"[BrandMapper] Mapped: {brand} → {ticker or 'PRIVATE'} "
                f"(material={material})"
            )
            return True

        except Exception as e:
            logger.error(f"[BrandMapper] Failed to insert mapping for {brand}: {e}")
            return False

    def _log_unmapped(self, brand: str, reason: str, candidates: Optional[List] = None) -> None:
        """Log unmapped brand for manual review"""
        if candidates:
            candidate_info = ", ".join([
                f"{c.get('symbol', '?')}:{c.get('name', '?')}"
                for c in candidates[:3]
            ])
            logger.warning(
                f"[BrandMapper] UNMAPPED: {brand} - {reason} - "
                f"Candidates: {candidate_info}"
            )
        else:
            logger.warning(f"[BrandMapper] UNMAPPED: {brand} - {reason}")

    def map_brand(self, brand: str) -> MappingResult:
        """
        Attempt to map a brand name to a stock ticker.

        This is the main entry point for brand mapping. It:
        1. Checks if brand is already mapped (returns cached result)
        2. Searches FMP API for matching companies
        3. Selects best match and determines materiality
        4. Inserts mapping into database
        5. Logs failures for manual review

        Args:
            brand: Brand name to map

        Returns:
            MappingResult with status and details
        """
        self._metrics["lookups"] += 1

        # Check cache first
        existing = self._is_brand_mapped(brand)
        if existing:
            self._metrics["cache_hits"] += 1
            logger.debug(f"[BrandMapper] Cache hit: {brand} → {existing.get('ticker')}")
            return MappingResult(
                brand=brand,
                status=MappingStatus.ALREADY_MAPPED,
                ticker=existing.get("ticker"),
                parent_company=existing.get("parent_company"),
                material=existing.get("material", False),
                exchange=existing.get("exchange"),
                notes=existing.get("notes"),
            )

        # Search FMP API
        candidates = self._search_fmp(brand)

        if candidates is None:
            # API error - don't insert anything, try again later
            return MappingResult(
                brand=brand,
                status=MappingStatus.API_ERROR,
                notes="FMP API unavailable",
            )

        if not candidates:
            # No results - brand is likely private or too obscure
            self._metrics["not_found"] += 1
            self._log_unmapped(brand, "No FMP results")

            # Insert as unmapped for tracking
            self._insert_mapping(
                brand=brand,
                ticker=None,
                parent_company=None,
                material=False,
                exchange=None,
                notes="Auto: No FMP results - likely private",
            )

            return MappingResult(
                brand=brand,
                status=MappingStatus.NOT_FOUND,
                notes="No matching companies found",
            )

        # Select best match
        best_match = self._select_best_match(brand, candidates)

        if best_match is None:
            # Ambiguous results - need manual review
            self._metrics["ambiguous"] += 1
            self._log_unmapped(brand, "Ambiguous results", candidates)

            # Insert as unmapped with candidates noted
            candidate_str = ", ".join([
                f"{c.get('symbol')}:{c.get('name')}"
                for c in candidates[:5]
            ])
            self._insert_mapping(
                brand=brand,
                ticker=None,
                parent_company=None,
                material=False,
                exchange=None,
                notes=f"Auto: Ambiguous - review candidates: {candidate_str}",
            )

            return MappingResult(
                brand=brand,
                status=MappingStatus.AMBIGUOUS,
                notes="Multiple potential matches - needs manual review",
                candidates=candidates[:5],
            )

        # We have a match - determine materiality
        ticker = best_match.get("symbol")
        company_name = best_match.get("name", "")
        exchange = best_match.get("exchangeShortName") or best_match.get("exchange")
        material = self._determine_materiality(brand, company_name)

        # Insert mapping
        notes = f"Auto-mapped via FMP API"
        if not material:
            notes += " - materiality needs manual verification"

        success = self._insert_mapping(
            brand=brand,
            ticker=ticker,
            parent_company=company_name,
            material=material,
            exchange=exchange,
            notes=notes,
        )

        if success:
            return MappingResult(
                brand=brand,
                status=MappingStatus.MAPPED_SUCCESS,
                ticker=ticker,
                parent_company=company_name,
                material=material,
                exchange=exchange,
                notes=notes,
            )
        else:
            return MappingResult(
                brand=brand,
                status=MappingStatus.API_ERROR,
                notes="Failed to insert mapping",
            )

    def ensure_brands_mapped(self, brands: List[str]) -> Dict[str, MappingResult]:
        """
        Ensure all brands in the list are mapped (or attempted).

        Args:
            brands: List of brand names to map

        Returns:
            Dict mapping brand names to their MappingResult
        """
        results = {}
        for brand in brands:
            if not brand or not brand.strip():
                continue
            brand = brand.strip()
            results[brand] = self.map_brand(brand)
        return results

    def get_metrics(self) -> Dict[str, int]:
        """Return current metrics for monitoring"""
        return self._metrics.copy()


# Module-level singleton for convenience
_mapper: Optional[BrandMapper] = None


def get_mapper() -> BrandMapper:
    """Get or create the global BrandMapper instance"""
    global _mapper
    if _mapper is None:
        _mapper = BrandMapper()
    return _mapper


def ensure_brand_mapped(brand: str) -> MappingResult:
    """
    Convenience function to map a single brand.

    Args:
        brand: Brand name to map

    Returns:
        MappingResult with status and details
    """
    return get_mapper().map_brand(brand)


def ensure_brands_mapped(brands: List[str]) -> Dict[str, MappingResult]:
    """
    Convenience function to map multiple brands.

    Args:
        brands: List of brand names to map

    Returns:
        Dict mapping brand names to their MappingResult
    """
    return get_mapper().ensure_brands_mapped(brands)
