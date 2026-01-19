import psycopg2
from contextlib import contextmanager
from config import DATABASE_URL


class DatabaseClient:
    def __init__(self):
        self.database_url = DATABASE_URL

    @contextmanager
    def get_connection(self):
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def get_active_subreddits(self):
        """Load active subreddit list"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT subreddit_name FROM ai_infrastructure_subreddits WHERE active = true"
                )
                return [row[0] for row in cur.fetchall()]

    def insert_raw_post(self, post):
        """Insert raw post, return True if new, False if duplicate"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO ai_infrastructure_raw_posts
                        (post_id, subreddit, title, body, author, score, num_comments, created_utc, url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        post['id'],
                        post['subreddit'],
                        post['title'],
                        post['body'],
                        post['author'],
                        post['score'],
                        post['num_comments'],
                        post['created_utc'],
                        post['url']
                    ))
                    return True
        except psycopg2.IntegrityError:
            # Duplicate post_id, skip silently
            return False
        except Exception as e:
            print(f"Error inserting post {post['id']}: {e}")
            return False
