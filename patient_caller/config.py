"""Settings that must stay stable across every test call."""

from __future__ import annotations

import os
import re
from pathlib import Path

# The assessment line. The dialer has no flag to change this.
ALLOWED_DESTINATION = "+18054398008"
AGENT_NAME = "patient-caller"
SIP_IDENTITY = "clinic-line"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VOICE = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"


class DestinationError(ValueError):
    """Raised when a dial target is anything other than the assessment line."""


def calls_dir() -> Path:
    raw = os.getenv("CALLS_DIR", "calls")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def normalize_e164(number: str) -> str:
    digits = re.sub(r"\D", "", number or "")
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) != 11 or not digits.startswith("1"):
        raise DestinationError(f"Not a US number: {number!r}")
    return f"+{digits}"


def assert_destination(number: str) -> str:
    """Return the assessment number, or refuse to dial."""
    normalized = normalize_e164(number)
    if normalized != ALLOWED_DESTINATION:
        raise DestinationError(
            f"Refusing to dial {normalized}. "
            f"The only allowed number is {ALLOWED_DESTINATION}."
        )
    return normalized


def caller_number() -> str:
    raw = os.getenv("SIP_CALLER_NUMBER", "").strip()
    if not raw:
        raise SystemExit(
            "Missing SIP_CALLER_NUMBER. Set the single caller ID you will submit, in E.164."
        )
    number = normalize_e164(raw)
    if number == ALLOWED_DESTINATION:
        raise SystemExit(
            "SIP_CALLER_NUMBER is the assessment line. Use your own outbound caller ID."
        )
    return number


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}. Copy .env.example to .env and fill it in.")
    return value
