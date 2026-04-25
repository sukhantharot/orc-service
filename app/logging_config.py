import json
import logging
import re
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Defensive scrubber: any 13-digit run (Thai ID) or 9+ digit run (passport number) gets masked.
# Belt-and-braces — middleware shouldn't be logging PII in the first place.
_DIGIT_RUN_RE = re.compile(r"\d{9,}")
_RESERVED_LOG_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName", "asctime",
}


def _scrub(text: str) -> str:
    return _DIGIT_RUN_RE.sub("***", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": _scrub(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        for k, v in record.__dict__.items():
            if k in _RESERVED_LOG_KEYS or k.startswith("_"):
                continue
            payload[k] = _scrub(v) if isinstance(v, str) else v
        if record.exc_info:
            payload["exc"] = _scrub(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "info") -> None:
    """Replace any existing handlers with a single JSON stdout handler at the requested level."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Quiet down libraries that log per-request access lines (we emit our own)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
