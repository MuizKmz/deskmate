"""Special days: your birthday, public holidays, payday, Friday. Pure Python.

Holidays come from the ``holidays`` package (it knows Hari Raya, Chinese New Year, Deepavali
and the rest for Malaysia, and for most other countries too). If it isn't installed, she
still knows birthdays, payday and Fridays.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

log = logging.getLogger(__name__)

# Friendlier English names than the official ones, where the package's English is stiff.
NICER = {
    "Eid al-Fitr": "Hari Raya Aidilfitri",
    "Eid al-Fitr (Second Day)": "Hari Raya Aidilfitri",
    "Eid al-Adha": "Hari Raya Haji",
    "Chinese New Year": "Chinese New Year",
    "Chinese New Year (Second Day)": "Chinese New Year",
    "Diwali": "Deepavali",
    "Deepavali": "Deepavali",
    "National Day": "Merdeka Day",
    "Labor Day": "Labour Day",
    "Christmas Day": "Christmas",
    "Islamic New Year": "Awal Muharram",
    "Vesak Day": "Wesak Day",
    "Beginning of Ramadan": "Ramadan",
}
SKIP_WORDS = ("in lieu", "observed", "holiday)", "eve", "special", "replacement", "day off")


@dataclass(frozen=True)
class SpecialDay:
    kind: str   # "birthday" | "holiday" | "payday" | "friday"
    name: str   # "Hari Raya Aidilfitri", "your birthday", ...


@lru_cache(maxsize=64)
def _table(country: str, subdiv: str, year: int):
    import holidays

    try:
        return holidays.country_holidays(country, subdiv=subdiv or None, years=year, language="en_US")
    except (NotImplementedError, KeyError, ValueError):  # (no English names here, or no such state)
        return holidays.country_holidays(country, subdiv=subdiv or None, years=year)


def _names(day: date, country: str, subdiv: str) -> list[str]:
    names = []
    for name in _table(country, subdiv, day.year).get_list(day):
        if not any(word in name.lower() for word in SKIP_WORDS):  # a day off in lieu isn't the festival itself
            names.append(name)
    return names


def _holiday(day: date, country: str, subdiv: str = "") -> str | None:
    if not country:
        return None
    try:
        import holidays
    except ImportError:
        return None
    try:
        names = _names(day, country, subdiv)
        if not names and not subdiv:
            # No state set: a holiday most states have counts too (in Malaysia, Deepavali isn't
            # "national" because one state doesn't have it, but nearly everyone celebrates it).
            states = list(holidays.list_supported_countries().get(country.upper(), []))
            if states:
                counts: dict[str, int] = {}
                for state in states:
                    for name in _names(day, country, state):
                        counts[name] = counts.get(name, 0) + 1
                names = [name for name, n in counts.items() if n * 2 > len(states)]
    except Exception as error:
        log.info("No holidays for %s/%s: %s", country, subdiv, error)
        return None
    return NICER.get(names[0], names[0]) if names else None


def special_day(day: date, birthday: str = "", country: str = "", subdiv: str = "", payday: int = 0) -> SpecialDay | None:
    """What's special about ``day`` (the most special thing), or None.

    ``birthday``: "MM-DD" (or ""). ``payday``: day of the month (0 = don't mention; 31 = the last day)."""
    if birthday and day.strftime("%m-%d") == birthday:
        return SpecialDay("birthday", "your birthday")
    holiday = _holiday(day, country, subdiv)
    if holiday:
        return SpecialDay("holiday", holiday)
    if payday:
        import calendar

        last = calendar.monthrange(day.year, day.month)[1]
        if day.day == min(payday, last):
            return SpecialDay("payday", "payday")
    if day.weekday() == 4:
        return SpecialDay("friday", "Friday")
    return None


def valid_birthday(text: str) -> str | None:
    """"31/12", "12-31", "Dec 31", "31 December" -> "12-31" (None if it isn't a date)."""
    import re

    text = (text or "").strip().lower()
    if not text:
        return ""
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    month = day = None
    named = re.search(r"([a-z]{3})[a-z]*", text)
    number = re.findall(r"\d{1,2}", text)
    if named and named.group(1) in months and number:
        month, day = months.index(named.group(1)) + 1, int(number[0])
    elif len(number) >= 2:
        first, second = int(number[0]), int(number[1])
        day, month = (first, second) if first > 12 or "/" in text else (second, first)
        if "-" in text and first <= 12:  # "12-31" is month-day
            month, day = first, second
    if not month or not day:
        return None
    try:
        date(2024, month, day)  # (a leap year, so 29 Feb is fine)
    except ValueError:
        return None
    return f"{month:02d}-{day:02d}"
