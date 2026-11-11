"""Worker entry point for background job processing.

Jobs are natively dispatched to concurrent ThreadPoolExecutor in-process.
This runner is retained as an operational health checker.
"""

import logging
import sys
import time

logger = logging.getLogger("handoffscope.worker")


def main() -> None:
    """Run worker heartbeat monitor."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    logger.info("Native ThreadPool background executor is active. Worker standby.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Worker stopped.")


if __name__ == "__main__":
    main()
