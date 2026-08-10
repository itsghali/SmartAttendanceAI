import logging
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


class RateLimiter:
    """Fixed-window rate limiter backed by Redis (or any Redis-compatible async client)."""

    def __init__(self, redis: Redis, key_prefix: str, limit: int, window_seconds: int):
        self._redis = redis
        self._key_prefix = key_prefix
        self._limit = limit
        self._window_seconds = window_seconds

    async def check(self, identifier: str) -> None:
        key = f"ratelimit:{self._key_prefix}:{identifier}"
        # Fail-open on purpose: Redis being down must not take auth, check-in,
        # and face-verify down with it. A rate-limit outage is a much smaller
        # blast radius than a login/attendance outage.
        try:
            current = await self._redis.incr(key)
            if current == 1:
                await self._redis.expire(key, self._window_seconds)
        except RedisError:
            logger.warning("rate limiter unavailable (%s) — failing open", self._key_prefix)
            return
        if current > self._limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Try again later.",
            )


def rate_limit(key_prefix: str, limit: int, window_seconds: int):
    """FastAPI dependency factory: limits requests per client IP within a fixed window."""

    async def dependency(request: Request, redis: Redis = Depends(get_redis_client)) -> None:
        identifier = request.client.host if request.client else "unknown"
        limiter = RateLimiter(redis, key_prefix, limit, window_seconds)
        await limiter.check(identifier)

    return dependency
