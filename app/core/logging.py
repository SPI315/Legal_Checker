from __future__ import annotations

import logging


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    for noisy_logger in (
        "httpx",
        "httpcore",
        "huggingface_hub",
        "transformers",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
