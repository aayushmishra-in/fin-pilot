"""Request-independent resources shared by MCP tool handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MCPRuntime:
    redis: Any | None = None

