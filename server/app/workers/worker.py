import os

from rq import Connection, SimpleWorker, Worker
from rq.timeouts import TimerDeathPenalty

from app.core.config import settings
from app.core.redis import redis_connection


def run_worker() -> None:
    with Connection(redis_connection):
        if os.name == "nt":
            worker = SimpleWorker([settings.rq_queue_name])
            worker.death_penalty_class = TimerDeathPenalty
        else:
            worker = Worker([settings.rq_queue_name])
        worker.work()


if __name__ == "__main__":
    run_worker()
