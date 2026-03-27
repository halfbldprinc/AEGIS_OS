import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structured logging for AegisOS services."""
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S%z"

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)

    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    logger = logging.getLogger("aegis")
    logger.debug("Aegis logging configured at level %s", logging.getLevelName(level))
