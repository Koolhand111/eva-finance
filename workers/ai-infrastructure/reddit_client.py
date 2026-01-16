import praw
from config import REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT


class RedditClient:
    def __init__(self):
        self.reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT
        )

    def fetch_recent_posts(self, subreddit_name, limit=50):
        """Fetch recent posts from subreddit"""
        subreddit = self.reddit.subreddit(subreddit_name)
        posts = []

        try:
            for submission in subreddit.new(limit=limit):
                posts.append({
                    'id': submission.id,
                    'title': submission.title,
                    'body': submission.selftext,
                    'author': str(submission.author),
                    'subreddit': subreddit_name,
                    'created_utc': submission.created_utc,
                    'url': submission.url,
                    'score': submission.score,
                    'num_comments': submission.num_comments
                })
        except Exception as e:
            print(f"Error fetching posts from r/{subreddit_name}: {e}")

        return posts
