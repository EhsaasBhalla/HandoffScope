"""Worker retry utilities."""

from __future__ import annotations

import logging
import time
from functools import wraps

logger = logging.getLogger("handoffscope.worker.retry")


def with_retry(max_retries: int = 3, backoff_base: float = 2.0):
    """Decorator that retries a function with exponential backoff."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        wait = backoff_base ** attempt
                        logger.warning(
                            "Attempt %d/%d for %s failed: %s. Retrying in %.1fs",
                            attempt + 1, max_retries + 1, func.__name__, exc, wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            "All %d attempts for %s exhausted. Last error: %s",
                            max_retries + 1, func.__name__, exc,
                        )
            raise last_exc

        return wrapper
    return decorator
