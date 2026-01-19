import os
from dotenv import load_dotenv

load_dotenv()

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL')

# Feature flag (kill switch)
ENABLED = os.getenv('AI_INFRA_ENABLED', 'false').lower() == 'true'

# Worker settings
LOOP_INTERVAL_SECONDS = 15 * 60  # 15 minutes
POSTS_PER_SUBREDDIT = 50

# Reddit public API settings (no authentication required)
USER_AGENT = "EVA-Finance/1.0 (AI Infrastructure Monitor; boring and deterministic)"
RATE_LIMIT_SLEEP = 2  # seconds between subreddit fetches
