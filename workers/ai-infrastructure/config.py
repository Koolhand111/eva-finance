import os
from dotenv import load_dotenv

load_dotenv()

# Environment variables
DATABASE_URL = os.getenv('DATABASE_URL')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT', 'EVA-Finance AI Infrastructure Monitor')

# Feature flag (kill switch)
ENABLED = os.getenv('AI_INFRA_ENABLED', 'false').lower() == 'true'

# Worker settings
LOOP_INTERVAL_SECONDS = 15 * 60  # 15 minutes
POSTS_PER_SUBREDDIT = 50
