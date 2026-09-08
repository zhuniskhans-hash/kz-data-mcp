#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Official exchange rates from the National Bank of Kazakhstan.

Two public XML endpoints, both verified live:

    https://nationalbank.kz/rss/rates_all.xml
        Today's rates. Each <item> carries <title> (ISO code), <pubDate>,
        <description> (rate), <quant>, <index> (UP/DOWN) and <change>.

    https://nationalbank.kz/rss/get_rates.cfm?fdate=DD.MM.YYYY
        Rates for a given date. Same fields plus <fullname> (Russian name).

The ``quant`` field is what makes this awkward and worth wrapping. Rates are
quoted per N units, not per unit: AMD is published as 12.72 with quant=10,
meaning one dram is 1.272 ₸. Reading ``description`` alone and treating it as
a per-unit rate is a factor-of-ten error on several currencies, so this module
always returns the normalised per-unit value alongside the raw quote.

Rates are published on business days. A request for a weekend or a holiday
returns the published set for that date, which may be empty — reported as
such rather than silently substituted with a nearby day.
"""
from __future__ import annotations

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

TODAY_URL = "https://nationalbank.kz/rss/rates_all.xml"
DATED_URL = "https://nationalbank.kz/rss/get_rates.cfm?fdate={date}"

TIMEOUT = 20


class NbrkError(RuntimeError):
    """The National Bank endpoint could not be read."""


@dataclass
class Rate:
    code: str                 # ISO 4217, e.g. USD
    name: str | None          # Russian full name, when the endpoint provides it
    quote: float              # as published, for `quant` units
    quant: int                # number of units the quote refers to
    per_unit: float           # quote / quant — the number you actually want
    change: float | None      # absolute change vs the previous publication
    direction: str | None     # UP / DOWN
    on_date: str              # DD.MM.YYYY as published

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "quote": self.quote,
            "quant": self.quant,
            "per_unit": round(self.per_unit, 6),
            "change": self.change,
            "direction": self.direction,
            "date": self.on_date,
        }


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "kz-data-mcp/1.0",
        "Accept": "application/xml, text/xml",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NbrkError(f"National Bank endpoint unreachable: {exc}") from exc


def _text(item: ET.Element, tag: str) -> str | None:
    node = item.find(tag)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _parse(xml_bytes: bytes, fallback_date: str) -> list[Rate]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise NbrkError(f"malformed XML from the National Bank: {exc}") from exc

    rates: list[Rate] = []
    # rates_all.xml nests items under channel; get_rates.cfm puts them at the
    # root. iter() covers both without branching on the endpoint.
    for item in root.iter("item"):
        code = _text(item, "title")
        raw_quote = _text(item, "description")
        if not code or not raw_quote:
            continue

        try:
            quote = float(raw_quote.replace(",", "."))
        except ValueError:
            continue

        try:
            quant = int(_text(item, "quant") or 1)
        except ValueError:
            quant = 1
        if quant <= 0:
            quant = 1

        raw_change = _text(item, "change")
        try:
            change = float(raw_change.replace(",", ".")) if raw_change else None
        except ValueError:
            change = None

        rates.append(Rate(
            code=code.upper(),
            name=_text(item, "fullname"),
            quote=quote,
            quant=quant,
            per_unit=quote / quant,
            change=change,
            direction=_text(item, "index"),
            on_date=_text(item, "pubDate") or fallback_date,
        ))

    return rates


def get_rates(on: date | None = None) -> list[Rate]:
    """
    Official rates against the tenge.

    ``on`` selects a publication date; omit it for today. Dates are sent in the
    endpoint's own DD.MM.YYYY format.
    """
    if on is None:
        return _parse(_fetch(TODAY_URL), date.today().strftime("%d.%m.%Y"))

    stamp = on.strftime("%d.%m.%Y")
    return _parse(_fetch(DATED_URL.format(date=stamp)), stamp)


def get_rate(code: str, on: date | None = None) -> Rate | None:
    """One currency by ISO code, or None if it was not published that day."""
    wanted = code.strip().upper()
    for rate in get_rates(on):
        if rate.code == wanted:
            return rate
    return None
