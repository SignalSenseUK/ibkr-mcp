"""IBKR MCP Server — read-only Model Context Protocol server for Interactive Brokers."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ibkr-mcp")
except PackageNotFoundError:  # pragma: no cover - during local source runs
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
