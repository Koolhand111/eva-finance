"""
EVA-Finance Database Connection Pool

Provides thread-safe connection pooling for PostgreSQL.

Usage:
    from eva_common.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()
    # Connection automatically returned to pool

For RealDictCursor:
    from psycopg2.extras import RealDictCursor

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users")
            rows = cur.fetchall()  # List of dicts
"""

from __future__ import annotations

import logging
import atexit
from contextlib import contextmanager
from typing import Generator, TYPE_CHECKING

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

from .config import db_settings

if TYPE_CHECKING:
    from psycopg2.extensions import connection

logger = logging.getLogger(__name__)

# Module-level pool singleton
_pool: ThreadedConnectionPool | None = None


def _create_pool() -> ThreadedConnectionPool:
    """Create the connection pool with settings from config."""
    logger.info(
        f"[EVA-DB] Creating connection pool: "
        f"min={db_settings.db_pool_min}, max={db_settings.db_pool_max}"
    )
    return ThreadedConnectionPool(
        minconn=db_settings.db_pool_min,
        maxconn=db_settings.db_pool_max,
        dsn=db_settings.connection_url,
    )


def get_pool() -> ThreadedConnectionPool:
    """
    Get or create the connection pool singleton.

    Returns:
        ThreadedConnectionPool instance
    """
    global _pool
    if _pool is None:
        _pool = _create_pool()
    return _pool


@contextmanager
def get_connection() -> Generator[connection, None, None]:
    """
    Context manager that provides a database connection from the pool.

    The connection is automatically returned to the pool when the context exits.
    If an exception occurs, the connection is still returned to the pool.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

    Yields:
        psycopg2 connection object
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    except Exception:
        # Rollback on error to reset connection state
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    """
    Close all connections in the pool.

    Call this on application shutdown to cleanly release resources.
    Registered with atexit for automatic cleanup.
    """
    global _pool
    if _pool is not None:
        logger.info("[EVA-DB] Closing connection pool")
        _pool.closeall()
        _pool = None


# Register cleanup on interpreter shutdown
atexit.register(close_pool)
