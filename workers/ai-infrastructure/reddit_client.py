"""
Reddit client using public JSON API (no authentication required).

Matches the method used by eva_ingest/reddit_posts.py for consistency.
"""
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from config import USER_AGENT, RATE_LIMIT_SLEEP


class RedditClient:
    """Fetches posts from Reddit's public JSON API with rate limiting."""

    def __init__(self):
        self.last_request_time = 0.0

    def fetch_recent_posts(self, subreddit_name, limit=50):
        """
        Fetch recent posts from a subreddit's public JSON endpoint.

        Args:
            subreddit_name: Name of subreddit (e.g., "datacenter")
            limit: Number of posts to fetch (max 100 per Reddit API)

        Returns:
            List of post dictionaries
        """
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < RATE_LIMIT_SLEEP:
            sleep_time = RATE_LIMIT_SLEEP - elapsed
            time.sleep(sleep_time)

        url = f"https://www.reddit.com/r/{subreddit_name}/new.json?limit={limit}"

        request = Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urlopen(request, timeout=30) as response:
                self.last_request_time = time.time()
                data = json.loads(response.read().decode("utf-8"))

                if not data or "data" not in data or "children" not in data["data"]:
                    print(f"Unexpected response structure from r/{subreddit_name}")
                    return []

                posts = []
                for child in data["data"]["children"]:
                    post_data = child["data"]
                    posts.append({
                        'id': post_data.get("id", ""),
                        'title': post_data.get("title", ""),
                        'body': post_data.get("selftext", ""),
                        'author': post_data.get("author", ""),
                        'subreddit': subreddit_name,
                        'created_utc': post_data.get("created_utc", 0),
                        'url': post_data.get("url", ""),
                        'score': post_data.get("score", 0),
                        'num_comments': post_data.get("num_comments", 0)
                    })

                return posts

        except HTTPError as e:
            print(f"HTTP error fetching r/{subreddit_name}: {e.code} {e.reason}")
            return []
        except URLError as e:
            print(f"Network error fetching r/{subreddit_name}: {e.reason}")
            return []
        except json.JSONDecodeError as e:
            print(f"JSON decode error for r/{subreddit_name}: {e}")
            return []
        except Exception as e:
            print(f"Error fetching posts from r/{subreddit_name}: {e}")
            return []
