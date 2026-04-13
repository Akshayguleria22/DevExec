from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from rq import Queue

from app.core.config import settings

redis_connection = Redis.from_url(settings.redis_url)
async_redis_connection = AsyncRedis.from_url(settings.redis_url)
task_queue = Queue(name=settings.rq_queue_name, connection=redis_connection)


def get_task_queue() -> Queue:
    return task_queue


def get_async_redis_connection() -> AsyncRedis:
    return async_redis_connection
