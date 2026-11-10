"""RQ worker entry point for background job processing.

Run with: python -m app.workers.runner
"""

import logging
import sys

from redis import Redis
from rq import Worker

from app.core.config import settings

logger = logging.getLogger("handoffscope.worker")

QUEUES = ["handoffscope-import", "handoffscope-extract", "handoffscope-default"]


def main() -> None:
    """Start the RQ worker listening on all three queues."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    redis_conn = Redis.from_url(settings.REDIS_URL)
    logger.info("Starting RQ worker on queues: %s", ", ".join(QUEUES))

    worker = Worker(QUEUES, connection=redis_conn)
    worker.work()


if __name__ == "__main__":
    main()
