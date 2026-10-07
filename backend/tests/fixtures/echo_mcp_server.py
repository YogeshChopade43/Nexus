"""Minimal stdio MCP server used by the tests."""
import json
import os
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("echo")


@server.tool()
def echo(text: str) -> str:
    """Echo text back."""
    return f"echo: {text}"


@server.tool()
def list_items(count: int = 3) -> dict:
    """Return a list of items."""
    return {"items": list(range(count)), "env_seen": os.environ.get("ECHO_SECRET", "")}


@server.tool()
def list_feed() -> dict:
    """Return the items stored in the JSON file named by FEED_FILE."""
    with open(os.environ["FEED_FILE"], encoding="utf-8") as handle:
        return {"items": json.load(handle)}


@server.tool()
def fail() -> str:
    """Always fails."""
    raise ValueError("boom")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run()
