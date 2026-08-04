"""Parser and conversion helpers for Alert2 records."""

from __future__ import annotations

from datetime import datetime
import logging
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

_MESSAGE_PATTERN = re.compile(r"^\s*(\d{1,3})\s+(.+?)\s*$", re.DOTALL)
_LINK_PATTERN = re.compile(r"\s*\[\[(.*?)\]\]\s*$", re.DOTALL)


def parse_alert2_message(message: str | None) -> dict[str, str | None] | None:
    """Parse an Alert2 last_fired_message.

    Supported examples:
      1 Message text
      111 Message text
      111 Message text[[/dashboard/path]]

    For a three-digit code, the third digit is the message type. For an older
    one-digit message, that digit is used as the message type.
    """

    if not message:
        return None

    match = _MESSAGE_PATTERN.match(str(message))
    if not match:
        _LOGGER.debug("Alert2 message does not match expected format: %r", message)
        return None

    code = match.group(1)
    text = match.group(2).strip()
    link: str | None = None

    link_match = _LINK_PATTERN.search(text)
    if link_match:
        link = link_match.group(1).strip() or None
        text = _LINK_PATTERN.sub("", text).strip()

    typ = code[2] if len(code) >= 3 else code[0]
    notify = code[0] if len(code) >= 3 else None
    pushover = code[1] if len(code) >= 3 else None
    
    return {
        "code": code,
        "typ": typ,
        "text": text,
        "link": link,
        "notify": notify,
        "pushover": pushover,
    }


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO datetime value from an Alert2 state attribute."""

    if value in (None, "", "unknown", "unavailable"):
        return None

    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        _LOGGER.warning("Invalid Alert2 datetime: %r", value)
        return None


def format_alert_timestamp(value: Any) -> tuple[str, int]:
    """Return the History-compatible timestamp and Unix timestamp."""

    parsed = parse_iso_datetime(value)
    if parsed is None:
        return "N/A", 0

    return (
        parsed.strftime("%a %d.%m.%Y %H:%M:%S %z"),
        int(parsed.timestamp()),
    )


def priority_to_typ(priority: Any) -> str:
    """Map Alert2 priority to the card color type."""

    mapping = {
        "high": "1",
        "medium": "2",
        "low": "6",
    }

    return mapping.get(str(priority or "").strip().lower(), "5")
