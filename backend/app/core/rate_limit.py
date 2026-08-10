from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from app.config.settings import get_settings

settings = get_settings()


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
        current = await self._redis.incr(key)
        if current == 1:
            await self._redis.expire(key, self._window_seconds)
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
