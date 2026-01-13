#!/usr/bin/env python3
"""
Reddit Post Ingestion for EVA-Finance

Boring, deterministic Reddit ingestion that fetches text posts from configured
subreddits and posts them to EVA API for processing.

Features:
- Rate-limited fetching from Reddit's public JSON API
- Idempotent via platform_id deduplication (handled by EVA API)
- Conservative filtering: only text posts with real content
- Clear logging and error handling
- No auto-trading, no recommendation changes

Usage:
    python -m eva_ingest.reddit_posts --subreddits BuyItForLife,Frugal,running --limit 25
    python -m eva_ingest.reddit_posts --help
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ------------------------------------
# Configuration
# ------------------------------------
DEFAULT_SUBREDDITS = ["BuyItForLife", "Frugal", "running"]
DEFAULT_LIMIT = 25
DEFAULT_RATE_LIMIT_SLEEP = 2  # seconds between subreddit fetches
DEFAULT_EVA_API_URL = "http://eva-api:9080/intake/message"
USER_AGENT = "EVA-Finance/1.0 (Reddit text post ingestion; boring and deterministic)"

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ------------------------------------
# Reddit API Client
# ------------------------------------
class RedditFetcher:
    """Fetches posts from Reddit's public JSON API with rate limiting."""

    def __init__(self, rate_limit_sleep: float = DEFAULT_RATE_LIMIT_SLEEP):
        self.rate_limit_sleep = rate_limit_sleep
        self.last_request_time = 0.0

    def fetch_new_posts(self, subreddit: str, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Fetch new posts from a subreddit's public JSON endpoint.

        Args:
            subreddit: Name of subreddit (e.g., "BuyItForLife")
            limit: Number of posts to fetch (max 100 per Reddit API)

        Returns:
            List of post dictionaries from Reddit API

        Raises:
            HTTPError: If Reddit API returns error status
            URLError: If network error occurs
        """
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_sleep:
            sleep_time = self.rate_limit_sleep - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)

        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
        logger.debug(f"Fetching {url}")

        request = Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urlopen(request, timeout=30) as response:
                self.last_request_time = time.time()
                data = json.loads(response.read().decode("utf-8"))

                if not data or "data" not in data or "children" not in data["data"]:
                    logger.warning(f"Unexpected response structure from r/{subreddit}")
                    return []

                posts = [child["data"] for child in data["data"]["children"]]
                logger.info(f"Fetched {len(posts)} posts from r/{subreddit}")
                return posts

        except HTTPError as e:
            logger.error(f"HTTP error fetching r/{subreddit}: {e.code} {e.reason}")
            raise
        except URLError as e:
            logger.error(f"Network error fetching r/{subreddit}: {e.reason}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for r/{subreddit}: {e}")
            raise


# ------------------------------------
# Post Filter and Normalizer
# ------------------------------------
class RedditPostProcessor:
    """Filters and normalizes Reddit posts for EVA ingestion."""

    @staticmethod
    def is_valid_text_post(post: Dict[str, Any]) -> bool:
        """
        Check if post is a valid text post with real content.

        Conservative filtering to favor false negatives over false positives.
        """
        selftext = post.get("selftext", "").strip()

        # Must have selftext
        if not selftext:
            return False

        # Filter out removed/deleted content
        if selftext in ["[removed]", "[deleted]"]:
            return False

        # Must have minimum length (avoid one-word posts)
        if len(selftext) < 10:
            return False

        return True

    @staticmethod
    def normalize_to_eva_format(post: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert Reddit post to EVA IntakeMessage format.

        Returns:
            Dictionary matching EVA's IntakeMessage schema:
            {
                "source": "reddit",
                "platform_id": "reddit_post_{id}",
                "timestamp": ISO8601 string,
                "text": "{title}\\n\\n{selftext}",
                "url": "https://www.reddit.com{permalink}",
                "meta": {"subreddit": ..., "author": ..., ...}
            }
        """
        reddit_id = post["id"]
        title = post.get("title", "").strip()
        selftext = post.get("selftext", "").strip()
        created_utc = post.get("created_utc", 0)

        # Combine title and selftext for better context
        full_text = f"{title}\n\n{selftext}"

        # Convert Unix timestamp to ISO8601
        timestamp = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()

        # Build permalink URL
        permalink = post.get("permalink", "")
        url = f"https://www.reddit.com{permalink}" if permalink else None

        return {
            "source": "reddit",
            "platform_id": f"reddit_post_{reddit_id}",
            "timestamp": timestamp,
            "text": full_text,
            "url": url,
            "meta": {
                "subreddit": post.get("subreddit", ""),
                "author": post.get("author", ""),
                "reddit_id": reddit_id,
            }
        }


# ------------------------------------
# EVA API Client
# ------------------------------------
class EVAAPIClient:
    """Client for posting messages to EVA API."""

    def __init__(self, api_url: str = DEFAULT_EVA_API_URL):
        self.api_url = api_url

    def post_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Post a message to EVA's /intake/message endpoint.

        Args:
            message: Dictionary matching IntakeMessage schema

        Returns:
            API response dict with {"status": "ok", "id": ...} or
            {"status": "received", "duplicate": True}

        Raises:
            HTTPError: If API returns error status
            URLError: If network error occurs
        """
        request = Request(
            self.api_url,
            data=json.dumps(message).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST"
        )

        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result

        except HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            logger.error(f"API error: {e.code} {e.reason} - {error_body}")
            raise
        except URLError as e:
            logger.error(f"Network error posting to EVA API: {e.reason}")
            raise


# ------------------------------------
# Main Ingestion Orchestrator
# ------------------------------------
class RedditIngestionJob:
    """Main orchestrator for Reddit ingestion job."""

    def __init__(
        self,
        subreddits: List[str],
        limit: int = DEFAULT_LIMIT,
        eva_api_url: str = DEFAULT_EVA_API_URL,
        rate_limit_sleep: float = DEFAULT_RATE_LIMIT_SLEEP,
    ):
        self.subreddits = subreddits
        self.limit = limit
        self.fetcher = RedditFetcher(rate_limit_sleep=rate_limit_sleep)
        self.processor = RedditPostProcessor()
        self.api_client = EVAAPIClient(api_url=eva_api_url)

        # Stats
        self.stats = {
            "subreddits_processed": 0,
            "posts_fetched": 0,
            "posts_filtered": 0,
            "posts_posted": 0,
            "posts_duplicate": 0,
            "posts_failed": 0,
        }

    def run(self) -> Dict[str, int]:
        """
        Run the ingestion job for all configured subreddits.

        Returns:
            Dictionary of statistics (fetched, posted, duplicates, failures)
        """
        logger.info(f"Starting Reddit ingestion for {len(self.subreddits)} subreddits")
        logger.info(f"Subreddits: {', '.join(self.subreddits)}")
        logger.info(f"Limit per subreddit: {self.limit}")
        logger.info(f"EVA API: {self.api_client.api_url}")

        for subreddit in self.subreddits:
            self._process_subreddit(subreddit)

        self._log_summary()
        return self.stats

    def _process_subreddit(self, subreddit: str):
        """Process a single subreddit: fetch, filter, normalize, post."""
        logger.info(f"Processing r/{subreddit}...")

        try:
            # Fetch posts
            posts = self.fetcher.fetch_new_posts(subreddit, limit=self.limit)
            self.stats["posts_fetched"] += len(posts)

            # Filter and process
            valid_posts = [p for p in posts if self.processor.is_valid_text_post(p)]
            filtered_count = len(posts) - len(valid_posts)
            self.stats["posts_filtered"] += filtered_count

            logger.info(f"r/{subreddit}: {len(valid_posts)} valid text posts "
                       f"({filtered_count} filtered out)")

            # Post each valid post to EVA
            for post in valid_posts:
                self._post_to_eva(post)

            self.stats["subreddits_processed"] += 1

        except (HTTPError, URLError) as e:
            logger.error(f"Failed to process r/{subreddit}: {e}")
            self.stats["posts_failed"] += 1
        except Exception as e:
            logger.error(f"Unexpected error processing r/{subreddit}: {e}", exc_info=True)
            self.stats["posts_failed"] += 1

    def _post_to_eva(self, post: Dict[str, Any]):
        """Post a single normalized post to EVA API."""
        try:
            message = self.processor.normalize_to_eva_format(post)
            result = self.api_client.post_message(message)

            if result.get("duplicate"):
                self.stats["posts_duplicate"] += 1
                logger.debug(f"Duplicate: {message['platform_id']}")
            else:
                self.stats["posts_posted"] += 1
                logger.debug(f"Posted: {message['platform_id']} (id={result.get('id')})")

        except (HTTPError, URLError) as e:
            self.stats["posts_failed"] += 1
            logger.error(f"Failed to post {post.get('id')}: {e}")
        except Exception as e:
            self.stats["posts_failed"] += 1
            logger.error(f"Unexpected error posting {post.get('id')}: {e}", exc_info=True)

    def _log_summary(self):
        """Log final statistics."""
        logger.info("=" * 60)
        logger.info("Reddit Ingestion Complete")
        logger.info("=" * 60)
        logger.info(f"Subreddits processed:  {self.stats['subreddits_processed']}")
        logger.info(f"Posts fetched:         {self.stats['posts_fetched']}")
        logger.info(f"Posts filtered out:    {self.stats['posts_filtered']}")
        logger.info(f"Posts posted to EVA:   {self.stats['posts_posted']}")
        logger.info(f"Duplicates skipped:    {self.stats['posts_duplicate']}")
        logger.info(f"Failures:              {self.stats['posts_failed']}")
        logger.info("=" * 60)


# ------------------------------------
# CLI Entry Point
# ------------------------------------
def main():
    """CLI entry point for Reddit ingestion."""
    parser = argparse.ArgumentParser(
        description="Ingest Reddit text posts into EVA-Finance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default subreddits
  python -m eva_ingest.reddit_posts

  # Custom subreddits
  python -m eva_ingest.reddit_posts --subreddits BuyItForLife,Frugal,running

  # Fetch more posts per subreddit
  python -m eva_ingest.reddit_posts --limit 50

  # Custom EVA API URL (e.g., for local testing)
  python -m eva_ingest.reddit_posts --eva-api-url http://localhost:9080/intake/message

  # Enable debug logging
  python -m eva_ingest.reddit_posts --debug
        """
    )

    parser.add_argument(
        "--subreddits",
        type=str,
        default=",".join(DEFAULT_SUBREDDITS),
        help=f"Comma-separated list of subreddits (default: {','.join(DEFAULT_SUBREDDITS)})"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Number of posts to fetch per subreddit (default: {DEFAULT_LIMIT})"
    )

    parser.add_argument(
        "--eva-api-url",
        type=str,
        default=os.getenv("EVA_API_URL", DEFAULT_EVA_API_URL),
        help=f"EVA API endpoint URL (default: {DEFAULT_EVA_API_URL}, or $EVA_API_URL)"
    )

    parser.add_argument(
        "--rate-limit-sleep",
        type=float,
        default=DEFAULT_RATE_LIMIT_SLEEP,
        help=f"Seconds to sleep between subreddit fetches (default: {DEFAULT_RATE_LIMIT_SLEEP})"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Configure logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Parse subreddits
    subreddits = [s.strip() for s in args.subreddits.split(",") if s.strip()]

    if not subreddits:
        logger.error("No subreddits specified")
        sys.exit(1)

    # Run ingestion
    job = RedditIngestionJob(
        subreddits=subreddits,
        limit=args.limit,
        eva_api_url=args.eva_api_url,
        rate_limit_sleep=args.rate_limit_sleep,
    )

    try:
        stats = job.run()

        # Exit with error code if there were failures
        if stats["posts_failed"] > 0:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\nIngestion interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
