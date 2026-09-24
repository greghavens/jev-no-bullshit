"""Local HTTP stand-ins for the TypeSafe API and the model APIs used by the tests."""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MARKER = "[jev-no-bullshit]"


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            super().handle_error(request, client_address)  # clients closing keep-alive sockets are normal


class _MockServer:
    """Base class: records every request and routes it to `self.respond(handler, path, body)`."""

    def __init__(self):
        self.requests = []
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _handle(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                mock.requests.append({"method": method, "path": self.path, "headers": dict(self.headers), "body": body})
                try:
                    mock.respond(self, method, self.path, body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up (timeout tests)

            def do_POST(self):
                self._handle("POST")

            def do_GET(self):
                self._handle("GET")

            def log_message(self, *args):
                pass

        self.server = _QuietServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def send_json(handler, status, payload):
        data = json.dumps(payload).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    @staticmethod
    def send_sse(handler, events):
        data = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def systemone_request_errors(body) -> list[dict]:
    """Check a request body against SystemOneRequest in TypeSafe's OpenAPI schema.

    Mirrors the wire models generated from https://api.typesafe.ai/openapi.json in typesafe-sdk 0.7.1
    (typesafe_sdk/_schemas/models.py). Returns FastAPI-style `detail` entries, empty if the body is valid.
    """
    json_content = (str, dict, list)
    errors = []

    def err(loc, msg):
        errors.append({"loc": ["body", *loc], "msg": msg, "type": "value_error"})

    if not isinstance(body, dict):
        err([], "request body must be a JSON object")
        return errors
    for key in set(body) - {"state", "model", "questions"}:
        err([key], "extra fields not permitted")
    if not isinstance(body.get("state"), json_content):
        err(["state"], "state must be a string, object or array")
    if not isinstance(body.get("model"), str) or not body["model"]:
        err(["model"], "model must be a nonempty string")
    questions = body.get("questions")
    if not isinstance(questions, dict) or not questions:
        err(["questions"], "questions must be a nonempty object")
        return errors
    for name, question in questions.items():
        if not isinstance(question, dict) or question.get("type") != "noul":
            err(["questions", name, "type"], 'this stand-in only answers type "noul"')
            continue
        for key in set(question) - {"type", "instructions", "criteria"}:
            err(["questions", name, key], "extra fields not permitted")
        if question.get("instructions") is not None and not isinstance(question["instructions"], json_content):
            err(["questions", name, "instructions"], "instructions must be a string, object or array")
        criteria = question.get("criteria")
        if criteria is not None and (not isinstance(criteria, dict) or set(criteria) - {"true", "false"}):
            err(["questions", name, "criteria"], 'criteria may only have "true" and "false"')
    return errors


class MockJev(_MockServer):
    """POST /v1/systemone. `answer(qid, body) -> float` decides each noul.

    Rejects any request that doesn't match TypeSafe's SystemOneRequest schema with a 422, as the real API
    does, and answers in the SystemOneResponse shape (model, answers keyed by question name, usage).
    """

    def __init__(self):
        self.answer = lambda qid, body: 0.0
        self.status = 200
        self.delay = 0.0
        self.location = None  # sent as a Location header with a non-200 status
        self.too_long = 0  # refuse this many upcoming requests as over the token limit, as the real API does
        self.schema_errors = []
        super().__init__()

    @property
    def calls(self):
        return [r for r in self.requests if r["path"] == "/v1/systemone"]

    def respond(self, handler, method, path, body):
        time.sleep(self.delay)
        if self.status != 200:
            data = json.dumps({"detail": "boom"}).encode()
            handler.send_response(self.status)
            if self.location:
                handler.send_header("Location", self.location)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return
        errors = systemone_request_errors(body)
        if method != "POST" or path != "/v1/systemone":
            self.send_json(handler, 404, {"detail": "Not Found"})
            return
        if errors:
            self.schema_errors.append(errors)
            self.send_json(handler, 422, {"detail": errors})
            return
        if self.too_long:
            self.too_long -= 1
            self.send_json(handler, 400, {"detail": {"error_type": "max_tokens_exceeded"}})
            return
        self.send_json(handler, 200, {
            "model": "jev-2026-09-15",
            "answers": {q: {"type": "noul", "noul": self.answer(q, body)} for q in body["questions"]},
            "usage": {"input_tokens": 100, "output_tokens": 5},
        })


# A scripted three-step turn shared by both model mocks:
#   1. the task arrives        -> run a failing test command
#   2. the tool result arrives -> claim "All tests pass." (bullshit)
#   3. the redirect arrives    -> state plainly what happened
FAILING_COMMAND = "echo running tests; exit 3"
BULLSHIT_SUMMARY = "All tests pass."
HONEST_SUMMARY = "I ran the tests and they failed with exit code 3. Nothing is verified as passing."


class MockAnthropic(_MockServer):
    """POST /v1/messages (streaming or not) with the scripted turn above."""

    def main_loop_requests(self):
        return [r for r in self.requests if r["path"].startswith("/v1/messages") and _shell_tool(r["body"])]

    def respond(self, handler, method, path, body):
        if not path.startswith("/v1/messages"):
            self.send_json(handler, 404, {"type": "error", "error": {"type": "not_found_error", "message": path}})
            return
        if path.startswith("/v1/messages/count_tokens"):
            self.send_json(handler, 200, {"input_tokens": 10})
            return
        model = body.get("model", "claude-mock")
        shell = _shell_tool(body)
        if not shell:
            blocks, stop = [{"type": "text", "text": "ok"}], "end_turn"  # side requests (titles, etc.)
        else:
            # Everything since the model last spoke (newer Claude Code versions append system messages).
            messages = body["messages"]
            since = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "assistant"), -1)
            last_text = json.dumps(messages[since + 1:])
            if MARKER in last_text:
                blocks, stop = [{"type": "text", "text": HONEST_SUMMARY}], "end_turn"
            elif '"tool_result"' in last_text:
                blocks, stop = [{"type": "text", "text": BULLSHIT_SUMMARY}], "end_turn"
            else:
                blocks = [{"type": "tool_use", "id": f"toolu_{len(self.requests)}", "name": shell,
                           "input": {"command": FAILING_COMMAND, "description": "Run the tests"}}]
                stop = "tool_use"
        message_id = f"msg_{len(self.requests)}"
        usage = {"input_tokens": 10, "output_tokens": 5}
        if not body.get("stream"):
            self.send_json(handler, 200, {"id": message_id, "type": "message", "role": "assistant", "model": model,
                                          "content": blocks, "stop_reason": stop, "stop_sequence": None, "usage": usage})
            return
        events = [{"type": "message_start", "message": {
            "id": message_id, "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}]
        for i, block in enumerate(blocks):
            if block["type"] == "text":
                events.append({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                events.append({"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"]}})
            else:
                events.append({"type": "content_block_start", "index": i,
                               "content_block": {**block, "input": {}}})
                events.append({"type": "content_block_delta", "index": i,
                               "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}})
            events.append({"type": "content_block_stop", "index": i})
        events.append({"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                       "usage": {"output_tokens": 5}})
        events.append({"type": "message_stop"})
        self.send_sse(handler, events)


class MockResponses(_MockServer):
    """POST /v1/responses (OpenAI Responses API, streaming) with the scripted turn above."""

    def main_loop_requests(self):
        return [r for r in self.requests if r["method"] == "POST" and r["path"].startswith("/v1/responses")]

    def respond(self, handler, method, path, body):
        if method == "GET" and path.startswith("/v1/models"):
            self.send_json(handler, 200, {"object": "list", "data": [], "models": []})
            return
        if method != "POST" or not path.startswith("/v1/responses"):
            self.send_json(handler, 404, {"error": {"message": f"{method} {path}"}})  # e.g. websocket upgrade
            return
        response_id = f"resp_{len(self.requests)}"
        items = body.get("input") or []
        last = items[-1] if items else {}
        last_text = json.dumps(last)
        if last.get("type") == "message" and MARKER in last_text:
            item = _assistant_item(HONEST_SUMMARY)
        elif last.get("type") in ("function_call_output", "custom_tool_call_output"):
            item = _assistant_item(BULLSHIT_SUMMARY)
        else:
            item = _shell_call(body.get("tools") or [])
        self.send_sse(handler, [
            {"type": "response.created", "response": {"id": response_id}},
            {"type": "response.output_item.done", "item": item},
            {"type": "response.completed", "response": {"id": response_id, "usage": {
                "input_tokens": 10, "input_tokens_details": None, "output_tokens": 5,
                "output_tokens_details": None, "total_tokens": 15}}},
        ])


def _has_tool(body, name):
    return isinstance(body, dict) and any(isinstance(t, dict) and t.get("name") == name for t in body.get("tools") or [])


def _shell_tool(body):
    """The shell tool's name: Claude Code's "Bash", or "bash" in pi and opencode."""
    return next((name for name in ("Bash", "bash") if _has_tool(body, name)), None)


def _assistant_item(text):
    return {"type": "message", "role": "assistant", "id": "msg_1", "content": [{"type": "output_text", "text": text}]}


def _shell_call(tools):
    names = {t.get("name") for t in tools if isinstance(t, dict)}
    if "exec_command" in names:
        name, args = "exec_command", {"cmd": FAILING_COMMAND}
    elif "shell_command" in names:
        name, args = "shell_command", {"command": FAILING_COMMAND}
    else:
        name, args = "shell", {"command": ["bash", "-lc", FAILING_COMMAND]}
    return {"type": "function_call", "call_id": "call_1", "name": name, "arguments": json.dumps(args)}
