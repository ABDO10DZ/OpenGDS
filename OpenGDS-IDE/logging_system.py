"""Categorized, rotating logging shared by the Studio GUI and OpenGDS core."""
from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

APP_LOG_DIR = Path.home() / ".opengds-studio" / "logs"

# Stable category palette used by the GUI log viewer and documented log files.
CATEGORY_COLORS = {
    "CORE": "#4FC1FF",
    "GUI": "#9CDCFE",
    "GODOT_ENGINE": "#CE9178",
    "GODOT_ENGINE_ERR": "#F44747",
    "GODOT_DEBUG": "#DCDCAA",
    "GDSCRIPT": "#D7BA7D",
    "GDSC": "#C586C0",
    "PYTHON": "#F44747",
    "LOGIC": "#FFCC66",
    "LSP": "#4EC9B0",
    "DAP": "#B5CEA8",
    "BUILD": "#C586C0",
    "FILE": "#D4D4D4",
    "ARCHIVE": "#D16969",
    "SYSTEM": "#808080",
}


def log_directory() -> Path:
    configured = os.environ.get("OPENGDS_LOG_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else APP_LOG_DIR


def configure_logging(log_file: str | Path | None = None, *, level: int = logging.DEBUG,
                      logger_name: str = "opengds") -> Path:
    """Configure a dedicated logger with a UTF-8 rotating file sink."""
    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    target = Path(log_file).expanduser().resolve() if log_file else directory / "studio.log"
    target.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.flush()
            handler.close()
        except Exception:
            pass

    handler = RotatingFileHandler(target, maxBytes=8 * 1024 * 1024, backupCount=8,
                                  encoding="utf-8", delay=True)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)s [%(category)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    handler.addFilter(_DefaultCategoryFilter())
    logger.addHandler(handler)

    # Child OpenGDS.py processes use a separate core.log file in this directory.
    os.environ["OPENGDS_LOG_DIR"] = str(directory)
    os.environ["OPENGDS_LOG_LEVEL"] = logging.getLevelName(level)
    return target


class _DefaultCategoryFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "category", None):
            record.category = "SYSTEM"
        return True


def category_logger(category: str) -> logging.LoggerAdapter:
    category = str(category or "SYSTEM").upper()
    if category not in CATEGORY_COLORS:
        category = "SYSTEM"
    return logging.LoggerAdapter(logging.getLogger("opengds"), {"category": category})


def log_event(category: str, level: int, message: Any, *, exc_info=None) -> None:
    category_logger(category).log(level, str(message), exc_info=exc_info, stacklevel=2)


def configure_core_logging() -> Path:
    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "core.log"
    configure_logging(target, level=getattr(logging, os.environ.get("OPENGDS_LOG_LEVEL", "DEBUG").upper(), logging.DEBUG))
    return target


def install_exception_hooks() -> None:
    """Persist uncaught main-thread, worker-thread, and unraisable Python errors."""
    if getattr(sys, "_opengds_exception_hooks_installed", False):
        return

    old_sys_hook = sys.excepthook

    def sys_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            old_sys_hook(exc_type, exc_value, exc_tb)
            return
        category_logger("PYTHON").critical(
            "Uncaught Python exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = sys_hook

    if hasattr(threading, "excepthook"):
        old_thread_hook = threading.excepthook

        def thread_hook(args):
            category_logger("PYTHON").critical(
                "Uncaught worker-thread exception in %s",
                getattr(args.thread, "name", "unknown-thread"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            if args.exc_type is KeyboardInterrupt:
                old_thread_hook(args)

        threading.excepthook = thread_hook

    if hasattr(sys, "unraisablehook"):
        old_unraisable_hook = sys.unraisablehook

        def unraisable_hook(args):
            category_logger("PYTHON").error(
                "Unraisable exception in %r: %s",
                args.object, args.err_msg or "no additional details",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            # Preserve interpreter diagnostics for unusual unraisable failures.
            if args.exc_type is KeyboardInterrupt:
                old_unraisable_hook(args)

        sys.unraisablehook = unraisable_hook

    sys._opengds_exception_hooks_installed = True
