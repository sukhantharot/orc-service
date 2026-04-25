import io
import json
import logging

from app.logging_config import JsonFormatter, _scrub, request_id_var


def _capture(record_factory):
    """Run a log record through JsonFormatter and return parsed dict."""
    handler = logging.StreamHandler(io.StringIO())
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(f"test-{id(record_factory)}")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    record_factory(logger)
    handler.flush()
    return json.loads(handler.stream.getvalue().strip())


def test_scrub_masks_thai_id_run():
    assert _scrub("id is 1101700157649") == "id is ***"


def test_scrub_masks_passport_number_run():
    assert _scrub("doc=L898902C3 num=123456789") == "doc=L898902C3 num=***"


def test_scrub_keeps_short_runs_intact():
    # Dates like 2026-04-25 contain only short digit groups → keep as-is
    assert _scrub("date=2026-04-25 status=200") == "date=2026-04-25 status=200"


def test_json_formatter_emits_valid_json_with_basic_fields():
    payload = _capture(lambda lg: lg.info("hello world"))
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert "ts" in payload
    assert "logger" in payload


def test_json_formatter_includes_request_id_from_contextvar():
    token = request_id_var.set("rid-abc-123")
    try:
        payload = _capture(lambda lg: lg.info("hi"))
    finally:
        request_id_var.reset(token)
    assert payload["request_id"] == "rid-abc-123"


def test_json_formatter_carries_extra_fields():
    payload = _capture(lambda lg: lg.info("req", extra={"method": "POST", "status": 200}))
    assert payload["method"] == "POST"
    assert payload["status"] == 200


def test_json_formatter_scrubs_pii_in_message():
    # Future regression guard: even if someone logs an ID, the formatter masks it
    payload = _capture(lambda lg: lg.info("processed id 1101700157649 ok"))
    assert "1101700157649" not in payload["msg"]
    assert "***" in payload["msg"]


def test_json_formatter_scrubs_pii_in_extra_string_fields():
    payload = _capture(lambda lg: lg.info("req", extra={"path": "/scan/1101700157649"}))
    assert "1101700157649" not in payload["path"]


def test_json_formatter_does_not_emit_reserved_internal_fields():
    payload = _capture(lambda lg: lg.info("hi"))
    for forbidden in ("args", "msecs", "thread", "processName"):
        assert forbidden not in payload
