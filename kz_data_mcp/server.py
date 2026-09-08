#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP server exposing Kazakhstan reference data over stdio.

The Model Context Protocol is JSON-RPC 2.0 with a defined handshake. This
implements it directly rather than through an SDK — it is about 150 lines,
it keeps the package dependency-free, and the wire format stays visible.

Lifecycle:

    client -> initialize                    -> server replies with the
                                               negotiated protocol version,
                                               capabilities and server info
    client -> notifications/initialized     -> notification, no reply
    client -> tools/list                    -> the tool catalogue
    client -> tools/call                    -> the result

Two error channels, and they are not interchangeable:

  * **Protocol errors** — unknown method, malformed request, unknown tool —
    are JSON-RPC ``error`` responses.
  * **Tool errors** — a currency that does not exist, an unreachable
    endpoint — are *successful* responses carrying ``isError: true``. The
    spec is explicit about this: a tool failure returned as a protocol error
    is invisible to the model, which then cannot correct itself.
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import date, datetime
from typing import Any, Callable

from . import identifiers, nbrk

SERVER_NAME = "kz-data-mcp"
SERVER_VERSION = "1.0.0"

#: Protocol revisions this server implements. The spec says: echo the
#: client's version when supported, otherwise answer with our latest and let
#: the client decide whether it can continue.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "kz_exchange_rate",
        "title": "Kazakhstan official exchange rate",
        "description": (
            "Official National Bank of Kazakhstan exchange rate against the "
            "tenge (KZT). Returns the per-unit rate, correctly normalised — "
            "the Bank quotes some currencies per 10 or 100 units. Omit "
            "'currency' for the full published list, omit 'date' for today. "
            "Rates are published on business days only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "currency": {
                    "type": "string",
                    "description": "ISO 4217 code, e.g. USD, EUR, CNY, RUB. "
                                   "Omit to get every published currency.",
                },
                "date": {
                    "type": "string",
                    "description": "Publication date as YYYY-MM-DD. "
                                   "Omit for today's rates.",
                },
            },
        },
    },
    {
        "name": "kz_validate_id",
        "title": "Validate ИИН / БИН",
        "description": (
            "Validate a Kazakhstan ИИН (individual) or БИН (legal entity) "
            "by its check digit, and decode date of birth and sex from an "
            "ИИН. A pass means the number is well-formed — it does not "
            "confirm the number exists in the state registry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "The 12-digit identifier. Spaces and "
                                   "dashes are ignored.",
                },
            },
            "required": ["id"],
        },
    },
]


def tool_exchange_rate(arguments: dict) -> str:
    on: date | None = None
    raw_date = arguments.get("date")
    if raw_date:
        try:
            on = datetime.strptime(str(raw_date), "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"date must be YYYY-MM-DD, got {raw_date!r}")

    currency = arguments.get("currency")
    if currency:
        rate = nbrk.get_rate(str(currency), on)
        if rate is None:
            raise ValueError(
                f"{str(currency).upper()} was not published for "
                f"{on.isoformat() if on else 'today'}. The National Bank "
                f"publishes on business days; check the code and the date."
            )
        return json.dumps(rate.as_dict(), ensure_ascii=False, indent=2)

    rates = nbrk.get_rates(on)
    if not rates:
        raise ValueError(
            f"no rates published for {on.isoformat() if on else 'today'} "
            f"— most likely a weekend or a public holiday"
        )
    return json.dumps(
        {"count": len(rates), "rates": [r.as_dict() for r in rates]},
        ensure_ascii=False, indent=2,
    )


def tool_validate_id(arguments: dict) -> str:
    value = arguments.get("id")
    if value is None:
        raise ValueError("'id' is required")
    return json.dumps(identifiers.validate(str(value)).as_dict(),
                      ensure_ascii=False, indent=2)


HANDLERS: dict[str, Callable[[dict], str]] = {
    "kz_exchange_rate": tool_exchange_rate,
    "kz_validate_id": tool_validate_id,
}


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

def negotiate_version(requested: str | None) -> str:
    """Echo the client's version when we speak it, else offer our latest."""
    if requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


def handle(message: dict) -> dict | None:
    """
    Process one JSON-RPC message. Returns the response, or None for a
    notification (no ``id`` — the spec forbids replying to those).
    """
    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    is_notification = message_id is None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "protocolVersion": negotiate_version(params.get("protocolVersion")),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Kazakhstan reference data. Use kz_exchange_rate for "
                    "official National Bank rates against the tenge, and "
                    "kz_validate_id to check an ИИН or БИН."
                ),
            },
        }

    if is_notification:
        # notifications/initialized, notifications/cancelled and friends.
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": message_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            # Failing to *find* a tool is a protocol error, unlike a tool
            # that runs and fails.
            return error(message_id, INVALID_PARAMS, f"unknown tool: {name}")

        try:
            text = handler(params.get("arguments") or {})
        except (ValueError, nbrk.NbrkError) as exc:
            # A tool that ran and failed. Reported inside a successful
            # response so the model can see it and adjust.
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            }
        except Exception:  # noqa: BLE001 — must not take the server down
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "content": [{"type": "text",
                                 "text": "internal error:\n" + traceback.format_exc()}],
                    "isError": True,
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {"content": [{"type": "text", "text": text}]},
        }

    if method in ("ping",):
        return {"jsonrpc": "2.0", "id": message_id, "result": {}}

    return error(message_id, METHOD_NOT_FOUND, f"unknown method: {method}")


def error(message_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": message_id,
            "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> None:
    """Read line-delimited JSON-RPC from stdin, write responses to stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    for line in stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            write(stdout, error(None, PARSE_ERROR, f"invalid JSON: {exc}"))
            continue

        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            write(stdout, error(None, INVALID_REQUEST,
                                "expected a JSON-RPC 2.0 object"))
            continue

        try:
            response = handle(message)
        except Exception as exc:  # noqa: BLE001 — a crash would kill the session
            response = error(message.get("id"), INTERNAL_ERROR, str(exc))

        if response is not None:
            write(stdout, response)


def write(stream, payload: dict) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    stream.flush()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
