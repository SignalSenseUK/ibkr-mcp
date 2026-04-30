"""Translate ISO 8601 durations into IB-native duration strings.

Spec §6.4 mandates the server accept both formats:

* IB-native: ``"30 D"``, ``"3600 S"``, ``"1 Y"`` — passed through unchanged.
* ISO 8601:  ``"P30D"``, ``"PT3600S"``, ``"P1Y"`` — translated.

The spec table is the single source of truth; the implementation below
matches every row of it. Mixed-component ISO durations (e.g. ``P1Y6M``) are
rejected with ``ValueError`` so the caller can surface a clear error to the
client.
"""

from __future__ import annotations

import re
from typing import Final

# IB-native: "<n> <unit>" with unit ∈ {S, D, W, M, Y}.
_IB_NATIVE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<value>\d+)\s+(?P<unit>[SDWMY])\s*$")

# ISO 8601 duration: PnYnMnWnDTnHnMnS (any single component may be absent).
# Note: weeks (P{n}W) cannot legally combine with other components in the
# strict ISO grammar but we allow any combination and validate ourselves.
_ISO_RE: Final[re.Pattern[str]] = re.compile(
    r"^P"
    r"(?:(?P<years>\d+)Y)?"
    r"(?:(?P<months>\d+)M)?"
    r"(?:(?P<weeks>\d+)W)?"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?"
    r")?$"
)


def parse_duration(duration: str) -> str:
    """Return an IB-native duration string for either input format.

    Raises:
        ValueError: when ``duration`` is empty, malformed, or mixes ISO date
            and time components (which IB cannot represent in a single field).
    """

    if not isinstance(duration, str) or not duration.strip():
        raise ValueError("duration must be a non-empty string")

    text = duration.strip()

    # Pass-through for IB-native strings.
    native = _IB_NATIVE_RE.match(text)
    if native:
        return f"{int(native['value'])} {native['unit']}"

    iso = _ISO_RE.match(text)
    if not iso or text == "P" or text == "PT":
        raise ValueError(f"Invalid duration: {duration!r}")

    years = int(iso["years"] or 0)
    months = int(iso["months"] or 0)
    weeks = int(iso["weeks"] or 0)
    days = int(iso["days"] or 0)
    hours = int(iso["hours"] or 0)
    minutes = int(iso["minutes"] or 0)
    seconds = int(iso["seconds"] or 0)

    has_date = bool(years or months or weeks or days)
    has_time = bool(hours or minutes or seconds)

    if has_date and has_time:
        raise ValueError(f"Mixed date and time components are not supported: {duration!r}")

    if has_time:
        total_seconds = hours * 3600 + minutes * 60 + seconds
        return f"{total_seconds} S"

    # Date-only: pick the single non-zero component.
    components = [
        ("Y", years),
        ("M", months),
        ("W", weeks),
        ("D", days),
    ]
    non_zero = [(unit, value) for unit, value in components if value]
    if len(non_zero) != 1:
        raise ValueError(f"Multi-component ISO date durations are not supported: {duration!r}")
    unit, value = non_zero[0]
    return f"{value} {unit}"
