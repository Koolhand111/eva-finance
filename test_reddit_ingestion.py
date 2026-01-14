#!/usr/bin/env python3
"""
Quick validation test for Reddit ingestion module.

Tests the Reddit ingestion components without requiring Docker or EVA API.
"""

import sys
sys.path.insert(0, '/home/koolhand/projects/eva-finance')

from eva_ingest.reddit_posts import (
    RedditFetcher,
    RedditPostProcessor,
    EVAAPIClient,
)


def test_reddit_api_fetch():
    """Test fetching from Reddit's public JSON API."""
    print("=" * 60)
    print("TEST 1: Fetching from Reddit API")
    print("=" * 60)

    fetcher = RedditFetcher(rate_limit_sleep=0)  # No sleep for test

    try:
        posts = fetcher.fetch_new_posts("BuyItForLife", limit=5)
        print(f"✅ Fetched {len(posts)} posts from r/BuyItForLife")

        if posts:
            first_post = posts[0]
            print(f"   Sample post ID: {first_post.get('id')}")
            print(f"   Sample title: {first_post.get('title', '')[:50]}...")

        return True

    except Exception as e:
        print(f"❌ Failed to fetch: {e}")
        return False


def test_post_filtering():
    """Test post filtering logic."""
    print("\n" + "=" * 60)
    print("TEST 2: Post Filtering")
    print("=" * 60)

    processor = RedditPostProcessor()

    # Valid post
    valid_post = {
        "id": "test123",
        "title": "Great running shoes",
        "selftext": "I've been using these shoes for 5 years and they're still great!",
        "subreddit": "running",
        "author": "testuser",
        "created_utc": 1705147800,
        "permalink": "/r/running/comments/test123/great_running_shoes/",
    }

    # Invalid posts
    invalid_posts = [
        {"id": "1", "selftext": ""},  # Empty selftext
        {"id": "2", "selftext": "[removed]"},  # Removed
        {"id": "3", "selftext": "[deleted]"},  # Deleted
        {"id": "4", "selftext": "Short"},  # Too short
    ]

    # Test valid post
    if processor.is_valid_text_post(valid_post):
        print("✅ Valid post correctly accepted")
    else:
        print("❌ Valid post incorrectly rejected")
        return False

    # Test invalid posts
    rejected_count = sum(
        1 for post in invalid_posts
        if not processor.is_valid_text_post(post)
    )

    if rejected_count == len(invalid_posts):
        print(f"✅ All {rejected_count} invalid posts correctly rejected")
    else:
        print(f"❌ Only {rejected_count}/{len(invalid_posts)} invalid posts rejected")
        return False

    return True


def test_normalization():
    """Test post normalization to EVA format."""
    print("\n" + "=" * 60)
    print("TEST 3: Post Normalization")
    print("=" * 60)

    processor = RedditPostProcessor()

    sample_post = {
        "id": "abc123",
        "title": "Best running shoes for wide feet",
        "selftext": "I've been searching for running shoes that fit my wide feet...",
        "subreddit": "running",
        "author": "runner123",
        "created_utc": 1705147800,
        "permalink": "/r/running/comments/abc123/best_running_shoes/",
    }

    try:
        normalized = processor.normalize_to_eva_format(sample_post)

        # Validate schema
        required_fields = ["source", "platform_id", "timestamp", "text", "url", "meta"]
        missing_fields = [f for f in required_fields if f not in normalized]

        if missing_fields:
            print(f"❌ Missing fields: {missing_fields}")
            return False

        # Validate values
        assert normalized["source"] == "reddit"
        assert normalized["platform_id"] == "reddit_post_abc123"
        assert "Best running shoes" in normalized["text"]
        assert "searching for running shoes" in normalized["text"]
        assert "reddit.com" in normalized["url"]
        assert normalized["meta"]["subreddit"] == "running"
        assert normalized["meta"]["author"] == "runner123"

        print("✅ Normalization successful")
        print(f"   Source: {normalized['source']}")
        print(f"   Platform ID: {normalized['platform_id']}")
        print(f"   Text length: {len(normalized['text'])} chars")
        print(f"   URL: {normalized['url'][:50]}...")
        print(f"   Meta: {normalized['meta']}")

        return True

    except Exception as e:
        print(f"❌ Normalization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Reddit Ingestion Module - Validation Tests")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("Reddit API Fetch", test_reddit_api_fetch()))
    results.append(("Post Filtering", test_post_filtering()))
    results.append(("Post Normalization", test_normalization()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")

    all_passed = all(result[1] for result in results)

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Start Docker containers: docker-compose up -d")
        print("2. Run end-to-end test: docker exec eva_worker python3 -m eva_ingest.reddit_posts --limit 5")
        print("3. Verify in database: make db-query-reddit")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
