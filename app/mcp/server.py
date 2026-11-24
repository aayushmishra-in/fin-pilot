"""Build the FastAPI-mounted Streamable HTTP MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

from app.core.config import settings as finpilot_settings
from app.mcp.auth import SupabaseMCPTokenVerifier
from app.mcp.runtime import MCPRuntime
from app.mcp.settings import MCPSettings, mcp_settings
from app.mcp.tools import register_tools


@dataclass
class MCPBundle:
    server: MCPServer
    http_app: ASGIApp
    runtime: MCPRuntime


def build_mcp_bundle(
    config: MCPSettings | None = None, *, token_verifier: TokenVerifier | None = None
) -> MCPBundle:
    """Create the protocol server, tools, and mounted ASGI app."""
    config = config or mcp_settings
    if config.public_url is None:
        raise RuntimeError("MCP_PUBLIC_URL must be configured before MCP is enabled")
    if not finpilot_settings.supabase_url:
        raise RuntimeError("SUPABASE_URL is required before MCP is enabled")

    resource_url = str(config.public_url)
    parsed_resource_url = urlsplit(resource_url)
    if (
        parsed_resource_url.path != "/mcp"
        or parsed_resource_url.query
        or parsed_resource_url.fragment
        or parsed_resource_url.username
        or parsed_resource_url.password
    ):
        raise RuntimeError(
            "MCP_PUBLIC_URL must be the canonical /mcp URL without credentials, query, or fragment"
        )
    if parsed_resource_url.scheme != "https" and parsed_resource_url.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeError("MCP_PUBLIC_URL must use HTTPS outside localhost development")

    issuer = f"{finpilot_settings.supabase_url.rstrip('/')}/auth/v1"
    verifier = token_verifier or SupabaseMCPTokenVerifier(
        issuer=issuer,
        resource_url=resource_url,
        jwks_url=f"{finpilot_settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
        hs256_secret=(
            finpilot_settings.supabase_jwt_secret.get_secret_value()
            if finpilot_settings.supabase_jwt_secret is not None
            else None
        ),
    )
    auth = AuthSettings(
        issuer_url=issuer,
        resource_server_url=resource_url,
        # Supabase OAuth does not support custom scopes. TokenVerifier checks the
        # MCP-only signed permission claim in addition to validating the audience.
        required_scopes=None,
        validate_token_resource=True,
    )
    server = MCPServer(
        name="finpilot",
        title="FinPilot",
        description="Read-only access to company-scoped FinPilot financial reports.",
        version="v1.mcp",
        auth=auth,
        token_verifier=verifier,
    )
    runtime = MCPRuntime()
    register_tools(server, runtime=runtime, config=config)

    allowed_hosts = sorted(
        {
            parsed_resource_url.netloc,
            parsed_resource_url.hostname or "",
            "localhost:*",
            "127.0.0.1:*",
            "[::1]:*",
        }
        - {""}
    )
    local_origins = [
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://[::1]:*",
    ]
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        # The first working client is a local browser-based Inspector; native
        # clients normally omit Origin. Add any hosted browser origin explicitly
        # when a hosted MCP client is selected.
        allowed_origins=[*local_origins, *config.allowed_browser_origins],
    )
    streamable_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        host=parsed_resource_url.hostname or "127.0.0.1",
        transport_security=transport_security,
        max_request_body_size=1_048_576,
        max_sessions=config.max_sessions,
        session_idle_timeout=float(config.session_idle_timeout_seconds),
    )
    http_app = CORSMiddleware(
        streamable_app,
        allow_origins=config.allowed_browser_origins,
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$",
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["MCP-Session-Id", "MCP-Protocol-Version", "WWW-Authenticate"],
    )
    return MCPBundle(server=server, http_app=http_app, runtime=runtime)
