"""Canonical MCP server facade.

This module intentionally does not reimplement tools.
The real, battle-tested v0.8 server lives in
``ashybulakstroy_mcp_1c_bridge.core_server`` and contains the preserved OData
discovery, inventory validation, recipes, explain trace, capabilities,
resources, prompts and AI-normalization wiring.

Importing from here gives MCP clients and package entry points one stable
location without losing the legacy logic.
"""
from __future__ import annotations

from ..core_server import mcp, main


def create_server():
    """Return the already-wired FastMCP instance from the real server module."""
    return mcp


__all__ = ["mcp", "main", "create_server"]
