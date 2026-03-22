"""Disk-based caching for API responses and computed data.

TTL values:
  - Yahoo API responses: 15 minutes
  - pybaseball/FanGraphs data: 24 hours
  - Projections: 7 days
"""

import logging
from functools import wraps
from pathlib import Path

import diskcache

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".cache")
cache = diskcache.Cache(str(CACHE_DIR))

# TTL constants (seconds)
TTL_YAHOO = 15 * 60  # 15 minutes
TTL_STATS = 24 * 60 * 60  # 24 hours
TTL_PROJECTIONS = 7 * 24 * 60 * 60  # 7 days


def cached(prefix: str, ttl: int = TTL_STATS):
    """Decorator for caching async function results.

    Usage:
        @cached("batting_stats", ttl=TTL_STATS)
        async def fetch_batting_stats(season: int):
            ...
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from function name + args
            key = f"{prefix}:{func.__name__}:{args}:{sorted(kwargs.items())}"
            result = cache.get(key)
            if result is not None:
                logger.debug(f"Cache hit: {key}")
                return result

            logger.debug(f"Cache miss: {key}")
            result = await func(*args, **kwargs)
            cache.set(key, result, expire=ttl)
            return result

        return wrapper

    return decorator


def invalidate(prefix: str | None = None) -> int:
    """Clear cache entries. If prefix given, only clear matching keys."""
    if prefix is None:
        count = len(cache)
        cache.clear()
        logger.info(f"Cleared entire cache ({count} entries)")
        return count

    count = 0
    for key in list(cache):
        if isinstance(key, str) and key.startswith(prefix):
            cache.delete(key)
            count += 1
    logger.info(f"Cleared {count} cache entries with prefix '{prefix}'")
    return count
