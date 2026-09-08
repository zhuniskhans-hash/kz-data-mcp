#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the MCP wire protocol: handshake, catalogue, dispatch and the
distinction between protocol errors and tool errors. No network needed —
the one tool that would reach out is stubbed.
"""
import io
import json
import unittest

from kz_data_mcp import server


def run(messages: list[dict]) -> list[dict]:
    """Feed messages through the stdio loop and collect the responses."""
    stdin = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
    stdout = io.StringIO()
    server.serve(stdin=stdin, stdout=stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line]


INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    },
}


class HandshakeTests(unittest.TestCase):
    def test_initialize_echoes_a_supported_version(self):
        [response] = run([INITIALIZE])
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], server.SERVER_NAME)

    def test_unknown_version_falls_back_to_our_latest(self):
        message = dict(INITIALIZE)
        message["params"] = dict(INITIALIZE["params"], protocolVersion="1999-01-01")
        [response] = run([message])
        self.assertEqual(response["result"]["protocolVersion"],
                         server.LATEST_PROTOCOL_VERSION)

    def test_notification_gets_no_response(self):
        """A message without an id must not be answered."""
        responses = run([{"jsonrpc": "2.0", "method": "notifications/initialized"}])
        self.assertEqual(responses, [])

    def test_ping(self):
        [response] = run([{"jsonrpc": "2.0", "id": 9, "method": "ping"}])
        self.assertEqual(response["result"], {})


class CatalogueTests(unittest.TestCase):
    def test_tools_list_shape(self):
        [_, response] = run([INITIALIZE,
                             {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        tools = response["result"]["tools"]
        self.assertEqual({t["name"] for t in tools},
                         {"kz_exchange_rate", "kz_validate_id"})
        for tool in tools:
            self.assertIn("description", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_every_advertised_tool_has_a_handler(self):
        advertised = {t["name"] for t in server.TOOLS}
        self.assertEqual(advertised, set(server.HANDLERS))


class DispatchTests(unittest.TestCase):
    def test_tool_call_returns_content(self):
        [_, response] = run([INITIALIZE, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "kz_validate_id", "arguments": {"id": "900101300123"}},
        }])
        result = response["result"]
        self.assertNotIn("isError", result)
        payload = json.loads(result["content"][0]["text"])
        self.assertIn("valid", payload)

    def test_tool_failure_is_a_successful_response_with_isError(self):
        """
        A tool that runs and fails must not surface as a JSON-RPC error —
        the model would never see it.
        """
        [_, response] = run([INITIALIZE, {
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "kz_exchange_rate", "arguments": {"date": "not-a-date"}},
        }])
        self.assertNotIn("error", response)
        self.assertTrue(response["result"]["isError"])
        self.assertIn("YYYY-MM-DD", response["result"]["content"][0]["text"])

    def test_unknown_tool_is_a_protocol_error(self):
        [_, response] = run([INITIALIZE, {
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        }])
        self.assertEqual(response["error"]["code"], server.INVALID_PARAMS)

    def test_unknown_method_is_a_protocol_error(self):
        [response] = run([{"jsonrpc": "2.0", "id": 6, "method": "nonsense"}])
        self.assertEqual(response["error"]["code"], server.METHOD_NOT_FOUND)


class RobustnessTests(unittest.TestCase):
    def test_malformed_json_does_not_stop_the_loop(self):
        stdin = io.StringIO(
            "{ this is not json\n" + json.dumps(INITIALIZE) + "\n")
        stdout = io.StringIO()
        server.serve(stdin=stdin, stdout=stdout)
        responses = [json.loads(l) for l in stdout.getvalue().splitlines() if l]
        self.assertEqual(responses[0]["error"]["code"], server.PARSE_ERROR)
        # The server kept going and served the next message.
        self.assertIn("result", responses[1])

    def test_blank_lines_are_skipped(self):
        stdin = io.StringIO("\n\n" + json.dumps(INITIALIZE) + "\n\n")
        stdout = io.StringIO()
        server.serve(stdin=stdin, stdout=stdout)
        self.assertEqual(len(stdout.getvalue().strip().splitlines()), 1)

    def test_non_jsonrpc_object_is_rejected(self):
        [response] = run([{"id": 1, "method": "initialize"}])
        self.assertEqual(response["error"]["code"], server.INVALID_REQUEST)


if __name__ == "__main__":
    unittest.main()
