"""A tiny OpenAI-compatible chat server for the browser tests (no real model, no API key).

Replies echo the question as Markdown (a table and a code block), report token usage, and take
3 seconds when the question contains "slow" so the Stop button can be tested.
Run: python fake_llm.py 8766
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def answer(question: str) -> str:
    return (f"**Answer** to: {question}\n\n| Item | Qty |\n|---|---|\n| Apples | 3 |\n\n"
            "```js\nconsole.log('hi')\n```")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        messages = body.get("messages", [])
        question = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
        if "slow" in question:
            time.sleep(3)
        # With document sources in the prompt, answer from the first one and cite it.
        sources = next((m.get("content") for m in messages if "<sources>" in (m.get("content") or "")), None)
        if sources:
            first = sources.split("<sources>", 1)[1].split("\n", 2)[2].split("\n\n", 1)[0].strip()
            text = f"From your documents: {first} [1]"
        else:
            text = answer(question)
        if body.get("stream"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            for i in range(0, len(text), 12):
                chunk = {"choices": [{"delta": {"content": text[i:i + 12]}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        reply = {"model": "fake-gpt", "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass  # the Stop test cancels requests mid-reply

    def do_GET(self):
        if self.path.startswith("/v0/servers"):  # stands in for the MCP Registry (Marketplace)
            port = self.server.server_address[1]
            listing = {"server": {"name": "io.e2e/demo", "title": "E2E Demo", "description": "A demo server for the browser tests",
                                  "version": "1.0.0", "remotes": [{"type": "streamable-http", "url": f"http://127.0.0.1:{port}/mcp"}]},
                       "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "isLatest": True,
                                                                               "updatedAt": "2026-10-09T00:00:00Z"}}}
            data = json.dumps({"servers": [listing], "metadata": {"count": 1}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)  # health check for Playwright's webServer
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
