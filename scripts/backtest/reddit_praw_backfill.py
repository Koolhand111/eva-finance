#!/usr/bin/env python3
"""
Reddit Historical Backfill using PRAW (Official Reddit API)
Alternative to Pushshift API for getting historical Reddit data
Pulls top 1000 posts from past year per subreddit
"""

import praw
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
import logging
import time
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'eva_finance',
    'user': 'eva',
    'password': 'eva_password_change_me'
}

# Target subreddits
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

def load_credentials():
    """Load Reddit API credentials from .env file"""
    creds_file = Path(__file__).parent / 'reddit_credentials.env'

    if not creds_file.exists():
        raise FileNotFoundError(
            f"Credentials file not found: {creds_file}\n"
            "Please create reddit_credentials.env with:\n"
            "REDDIT_CLIENT_ID=your_id\n"
            "REDDIT_CLIENT_SECRET=your_secret\n"
            "REDDIT_USER_AGENT=eva-finance-backtest/1.0"
        )

    creds = {}
    with open(creds_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                creds[key] = value

    required = ['REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET', 'REDDIT_USER_AGENT']
    missing = [k for k in required if k not in creds]
    if missing:
        raise ValueError(f"Missing credentials: {missing}")

    return creds

def create_reddit_client():
    """Initialize PRAW Reddit client"""
    creds = load_credentials()

    reddit = praw.Reddit(
        client_id=creds['REDDIT_CLIENT_ID'],
        client_secret=creds['REDDIT_CLIENT_SECRET'],
        user_agent=creds['REDDIT_USER_AGENT']
    )

    # Test connection
    try:
        reddit.user.me()  # This will fail if read-only
    except:
        pass  # Expected for script-type apps

    logger.info("Reddit API client initialized successfully")
    return reddit

def insert_post_to_db(conn, post, subreddit_name):
    """Insert a Reddit post into raw_messages table"""
    cursor = conn.cursor()

    # Extract post data
    post_id = post.id
    title = post.title
    selftext = getattr(post, 'selftext', '')
    author = str(post.author) if post.author else '[deleted]'
    score = post.score
    created_utc = post.created_utc
    url = post.url

    # Combine title and selftext
    text = f"{title}\n\n{selftext}".strip()

    # Skip deleted/removed posts
    if author in ['[deleted]', '[removed]']:
        return False
    if selftext in ['[deleted]', '[removed]']:
        return False
    if score < 5:  # Skip low-quality posts
        return False

    # Convert timestamp
    timestamp = datetime.fromtimestamp(created_utc)

    # Prepare metadata
    meta = {
        'subreddit': subreddit_name,
        'author': author,
        'score': score,
        'post_id': post_id,
        'num_comments': post.num_comments
    }

    # Insert into database
    insert_query = """
        INSERT INTO raw_messages (source, platform_id, timestamp, text, url, meta, processed)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, platform_id) DO NOTHING
        RETURNING id
    """

    try:
        cursor.execute(
            insert_query,
            ('reddit', f"r/{subreddit_name}/{post_id}", timestamp, text, url,
             psycopg2.extras.Json(meta), False)
        )
        result = cursor.fetchone()
        conn.commit()

        if result:
            logger.info(f"Inserted post {post_id} from r/{subreddit_name} ({timestamp.date()}, {score} upvotes)")
            return True
        else:
            logger.debug(f"Post {post_id} already exists, skipping")
            return False

    except Exception as e:
        logger.error(f"Error inserting post {post_id}: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()

def backfill_subreddit(reddit, subreddit_name, time_filter='year', limit=1000):
    """
    Backfill historical posts from a subreddit using PRAW

    Args:
        reddit: PRAW Reddit instance
        subreddit_name: Name of subreddit
        time_filter: 'day', 'week', 'month', 'year', 'all'
        limit: Max posts to fetch (PRAW max is ~1000)
    """
    logger.info(f"Starting backfill for r/{subreddit_name} (top {limit} posts from past {time_filter})")

    conn = psycopg2.connect(**DB_CONFIG)
    subreddit = reddit.subreddit(subreddit_name)

    inserted_count = 0
    skipped_count = 0

    try:
        # Get top posts from time period
        for post in subreddit.top(time_filter=time_filter, limit=limit):
            if insert_post_to_db(conn, post, subreddit_name):
                inserted_count += 1
            else:
                skipped_count += 1

            # Rate limiting courtesy
            time.sleep(0.1)

        logger.info(f"r/{subreddit_name}: Inserted {inserted_count}, Skipped {skipped_count}")

    except Exception as e:
        logger.error(f"Error fetching from r/{subreddit_name}: {e}")
    finally:
        conn.close()

    return inserted_count, skipped_count

def main():
    """Main backfill orchestration"""
    logger.info("=" * 60)
    logger.info("EVA-Finance PRAW Historical Backfill")
    logger.info(f"Subreddits: {', '.join(SUBREDDITS)}")
    logger.info("=" * 60)

    # Initialize Reddit client
    reddit = create_reddit_client()

    total_inserted = 0
    total_skipped = 0

    for subreddit_name in SUBREDDITS:
        try:
            inserted, skipped = backfill_subreddit(reddit, subreddit_name)
            total_inserted += inserted
            total_skipped += skipped

            # Rate limiting between subreddits
            time.sleep(2)

        except Exception as e:
            logger.error(f"Failed to backfill r/{subreddit_name}: {e}")
            continue

    logger.info("=" * 60)
    logger.info(f"Backfill complete!")
    logger.info(f"Total inserted: {total_inserted}")
    logger.info(f"Total skipped: {total_skipped}")
    logger.info("=" * 60)
    logger.info("Next step: Run worker.py to extract brands/tags from historical data")

if __name__ == '__main__':
    main()
