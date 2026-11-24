"""Configuration that belongs only to the MCP adapter."""

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    enabled: bool = False
    public_url: AnyHttpUrl | None = None
    read_calls_per_minute: int = Field(default=10, ge=1, le=100)
    max_sessions: int = Field(default=100, ge=1, le=10000)
    session_idle_timeout_seconds: int = Field(default=1800, ge=60, le=86400)
    allowed_browser_origins: list[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MCP_",
        extra="ignore",
    )


mcp_settings = MCPSettings()
