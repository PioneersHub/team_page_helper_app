import logging
import os
from pathlib import Path

import structlog
import yaml
from dotenv import load_dotenv

with (Path(__file__).parent / "config.yml").open("r") as f:
    CONFIG = yaml.safe_load(f)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%Y%m%dT%H%M%S", utc=True),
        structlog.dev.ConsoleRenderer(),  # Ensure ConsoleRenderer is used
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False
)

log = structlog.get_logger()
log.info("Logging configured")


load_dotenv()

TEAM_SHEET_ID = os.getenv('TEAM_SHEET_ID')
TEAM_WORKSHEET_NAME = os.getenv('TEAM_WORKSHEET_NAME')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')


__all__ = ["CONFIG", "log", "TEAM_SHEET_ID", "TEAM_WORKSHEET_NAME", "GITHUB_TOKEN"]
