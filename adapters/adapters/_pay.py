"""Holds the rules for a Silver pay value."""

import math
import re

PAY_PERIODS: tuple[str, ...] = ("year", "month", "week", "day", "hour")

# One pattern per period, matched whole-word so that "Monday" and "holiday" name none.
_PERIOD_PATTERNS: dict[str, re.Pattern[str]] = {
    "year": re.compile(r"\b(year(s|ly)?|annual(ly)?)\b"),
    "month": re.compile(r"\bmonth(s|ly)?\b"),
    "week": re.compile(r"\bweek(s|ly)?\b"),
    "day": re.compile(r"\b(days?|daily)\b"),
    "hour": re.compile(r"\bhour(s|ly)?\b"),
}

# The largest value a Numeric(12, 2) column holds.
_MAX_AMOUNT = 9999999999.99

_PAY_KEYS = frozenset({"min", "max", "currency", "period"})
_BOUNDS = ("min", "max")


def pay_period(text: str) -> str | None:
    """The period *text* names, or None when it names none of PAY_PERIODS."""
    lowered = text.lower()
    # Several periods in one text mean it is ambiguous, and a wrong period is worse
    # than none because it would pass validation and be shown.
    matches = [
        period
        for period, pattern in _PERIOD_PATTERNS.items()
        if pattern.search(lowered)
    ]
    return matches[0] if len(matches) == 1 else None


def _is_positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def pay_violation(pay: object) -> str | None:
    """What makes *pay* an invalid Silver pay value, or None when it is valid or
    None.
    """
    if pay is None:
        return None
    if not isinstance(pay, dict):
        return "pay is not an object"
    if set(pay) != _PAY_KEYS:
        return "pay keys are not exactly min, max, currency and period"
    for bound in _BOUNDS:
        value = pay[bound]
        if value is not None and not _is_positive_number(value):
            return f"pay {bound} is not a positive number or null"
    low, high = pay["min"], pay["max"]
    if low is None and high is None:
        return "pay states neither min nor max"
    if low is not None and high is not None and low > high:
        return "pay min exceeds max"
    for bound in _BOUNDS:
        if pay[bound] is not None and pay[bound] > _MAX_AMOUNT:
            return f"pay {bound} exceeds {_MAX_AMOUNT}"
    currency = pay["currency"]
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return "pay currency is not a three-letter ISO 4217 code"
    if pay["period"] not in PAY_PERIODS:
        return "pay period is not one of " + ", ".join(PAY_PERIODS)
    return None
