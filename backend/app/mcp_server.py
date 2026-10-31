"""MCP server exposing every agent tool over stdio.

Run (from backend/):  python -m app.mcp_server
ToolClient starts this as a subprocess at app startup. stdout carries the MCP protocol, so logs go to stderr.
"""
import logging
import sys

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except ImportError:  # mcp 2.x renamed FastMCP to MCPServer; same decorator/add_tool/run API
    from mcp.server.mcpserver import MCPServer as FastMCP

from .db import init_db
from .tools import TOOLS

server = FastMCP("qr-wapsi-tools", instructions="Tools for re-verifying paused Paytm merchants (simulated integrations).")
for _name, _fn in TOOLS.items():
    server.add_tool(_fn, name=_name)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[mcp-server] %(levelname)s %(name)s %(message)s")
    init_db()
    server.run("stdio")


if __name__ == "__main__":
    main()
