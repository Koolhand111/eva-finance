#!/usr/bin/env python3
"""
Historical Reddit Backfill Script
Pulls 6-12 months of historical posts from target subreddits using Pushshift API
Inserts into raw_messages table for validation backtesting
"""

import requests
import time
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'eva_finance',
    'user': 'eva',
    'password': 'eva_password_change_me'
}

# Target subreddits (from your current setup)
SUBREDDITS = [
    'BuyItForLife',
    'Frugal',
    'running',
    'sneakers',
    'malefashionadvice',
    'femalefashionadvice',
    'goodyearwelt',
    'onebag'
]

# Historical date range (6-12 months ago)
END_DATE = datetime.now() - timedelta(days=30)  # End 1 month ago
START_DATE = END_DATE - timedelta(days=365)  # Go back 12 months from there

PUSHSHIFT_API = "https://api.pushshift.io/reddit/search/submission/"
RATE_LIMIT_DELAY = 0.5  # 2 requests per second (conservative for Pushshift)


def fetch_posts_batch(subreddit: str, after: int, before: int, size: int = 100) -> List[Dict]:
    """
    Fetch a batch of posts from Pushshift API

    Args:
        subreddit: Subreddit name
        after: Unix timestamp (start of range)
        before: Unix timestamp (end of range)
        size: Number of posts to fetch (max 100)

    Returns:
        List of post dictionaries
    """
    params = {
        'subreddit': subreddit,
        'after': after,
        'before': before,
        'size': size,
        'sort': 'created_utc',
        'sort_type': 'asc'
    }

    try:
        response = requests.get(PUSHSHIFT_API, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get('data', [])
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from Pushshift: {e}")
        return []


def insert_post_to_db(conn, post: Dict, subreddit: str):
    """
    Insert a post into raw_messages table

    Args:
        conn: Database connection
        post: Post data from Pushshift
        subreddit: Subreddit name
    """
    cursor = conn.cursor()

    # Extract post data
    post_id = post.get('id')
    title = post.get('title', '')
    selftext = post.get('selftext', '')
    author = post.get('author', '[deleted]')
    score = post.get('score', 0)
    created_utc = post.get('created_utc')
    url = post.get('url', '')

    # Combine title and selftext for full content
    text = f"{title}\n\n{selftext}".strip()

    # Skip deleted/removed posts
    if author == '[deleted]' or author == '[removed]':
        return
    if selftext in ['[deleted]', '[removed]']:
        return
    if score < 5:  # Skip low-quality posts
        return

    # Convert timestamp
    timestamp = datetime.fromtimestamp(created_utc)

    # Prepare metadata
    meta = {
        'subreddit': subreddit,
        'author': author,
        'score': score,
        'post_id': post_id
    }

    # Insert into database
    insert_query = """
        INSERT INTO raw_messages (source, platform_id, timestamp, text, url, meta, processed)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, platform_id) DO NOTHING
    """

    try:
        cursor.execute(
            insert_query,
            ('reddit', f"r/{subreddit}/{post_id}", timestamp, text, url, psycopg2.extras.Json(meta), False)
        )
        conn.commit()
        logger.info(f"Inserted post {post_id} from r/{subreddit} ({timestamp})")
    except Exception as e:
        logger.error(f"Error inserting post {post_id}: {e}")
        conn.rollback()
    finally:
        cursor.close()


def backfill_subreddit(subreddit: str, start_date: datetime, end_date: datetime):
    """
    Backfill historical posts for a single subreddit

    Args:
        subreddit: Subreddit name
        start_date: Start of historical range
        end_date: End of historical range
    """
    logger.info(f"Starting backfill for r/{subreddit} from {start_date} to {end_date}")

    # Connect to database
    conn = psycopg2.connect(**DB_CONFIG)

    # Convert dates to Unix timestamps
    after_ts = int(start_date.timestamp())
    before_ts = int(end_date.timestamp())

    total_posts = 0
    current_after = after_ts

    while current_after < before_ts:
        # Fetch batch
        posts = fetch_posts_batch(subreddit, current_after, before_ts, size=100)

        if not posts:
            logger.warning(f"No more posts returned for r/{subreddit}")
            break

        # Insert each post
        for post in posts:
            insert_post_to_db(conn, post, subreddit)
            total_posts += 1

        # Update cursor for next batch (use last post's timestamp + 1)
        last_post_ts = posts[-1].get('created_utc', current_after)
        current_after = last_post_ts + 1

        logger.info(f"r/{subreddit}: Processed batch, total posts: {total_posts}, current: {datetime.fromtimestamp(current_after)}")

        # Rate limiting
        time.sleep(RATE_LIMIT_DELAY)

    conn.close()
    logger.info(f"Completed backfill for r/{subreddit}: {total_posts} posts inserted")


def main():
    """
    Main backfill orchestration
    """
    logger.info("=" * 60)
    logger.info("EVA-Finance Historical Backfill")
    logger.info(f"Date range: {START_DATE} to {END_DATE}")
    logger.info(f"Subreddits: {', '.join(SUBREDDITS)}")
    logger.info("=" * 60)

    for subreddit in SUBREDDITS:
        try:
            backfill_subreddit(subreddit, START_DATE, END_DATE)
        except Exception as e:
            logger.error(f"Error backfilling r/{subreddit}: {e}")
            continue

    logger.info("=" * 60)
    logger.info("Backfill complete!")
    logger.info("Next step: Run worker.py to extract brands/tags from historical data")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
