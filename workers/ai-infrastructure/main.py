import time
from datetime import datetime
from config import ENABLED, LOOP_INTERVAL_SECONDS, POSTS_PER_SUBREDDIT
from reddit_client import RedditClient
from db_client import DatabaseClient


def main():
    # Kill switch check
    if not ENABLED:
        print("=" * 60)
        print("AI Infrastructure Worker is DISABLED")
        print("Set AI_INFRA_ENABLED=true in docker-compose.yml to activate")
        print("=" * 60)
        while True:
            time.sleep(3600)  # Sleep forever

    print("=" * 60)
    print("AI Infrastructure Raw Ingestion STARTING")
    print(f"Timestamp: {datetime.now()}")
    print("Mode: RAW INGESTION ONLY (no LLM extraction)")
    print("=" * 60)

    # Initialize clients
    reddit = RedditClient()
    db = DatabaseClient()

    # Load configuration
    subreddits = db.get_active_subreddits()
    print(f"Monitoring {len(subreddits)} subreddits: {', '.join(subreddits)}")
    print(f"Fetching {POSTS_PER_SUBREDDIT} posts per subreddit")
    print(f"Loop interval: {LOOP_INTERVAL_SECONDS}s ({LOOP_INTERVAL_SECONDS/60:.0f} minutes)")
    print()

    # Main ingestion loop
    loop_count = 0
    while True:
        loop_count += 1
        loop_start = time.time()
        print(f"[{datetime.now()}] Loop #{loop_count} starting...")

        total_new = 0
        total_skipped = 0

        for subreddit in subreddits:
            try:
                print(f"  Fetching r/{subreddit}...")
                posts = reddit.fetch_recent_posts(subreddit, limit=POSTS_PER_SUBREDDIT)

                new_count = 0
                for post in posts:
                    inserted = db.insert_raw_post(post)
                    if inserted:
                        new_count += 1
                        total_new += 1
                    else:
                        total_skipped += 1

                print(f"    ✓ {len(posts)} posts fetched, {new_count} new, {len(posts)-new_count} duplicates")

            except Exception as e:
                print(f"    ✗ ERROR: {e}")
                continue

        loop_duration = time.time() - loop_start
        print(f"  Loop complete: {total_new} new posts, {total_skipped} duplicates")
        print(f"  Duration: {loop_duration:.1f}s")
        print()

        print(f"  Next loop in {LOOP_INTERVAL_SECONDS}s ({LOOP_INTERVAL_SECONDS/60:.0f} minutes)...")
        time.sleep(LOOP_INTERVAL_SECONDS)


if __name__ == '__main__':
    main()
