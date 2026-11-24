# FinPilot MCP Decisions

## Status and scope

- **Status:** The backend `v1.mcp` working model and the FinPilot OAuth consent route are implemented. Streamable HTTP, signed-token validation, all three read-only tools, consent/deny flows, and fake-backed authenticated tool calls are locally verified. The user enabled Supabase OAuth Server, dynamic client registration, and the Custom Access Token Hook. MCP Inspector established an authenticated Streamable HTTP session after a temporary process-level bypass for Supabase's public JWKS host. Its first `list_my_companies` call failed closed with `identity_not_linked`. The backend's missing Supabase public key prevented FinPilot's existing confirmed-email account-link path from completing; adding the matching frontend public key to the ignored local backend `.env` allowed the normal API to link the confirmed identity. After reconnecting Inspector, a real `list_my_companies` call completed successfully against the local database and Redis; the user reports successful live `get_cash_flow` and `get_budget_vs_actual` calls as well. The active signing key is ECC P-256 (ES256); an older HS256 key remains listed. PostgreSQL and Redis are healthy, but the database-backed MCP test suite has not yet been run.
- **Version label:** `v1.mcp` means the first MCP layer built on the existing FinPilot application. It does not name or change the MCP wire-protocol revision.
- **Baseline:** Existing FinPilot functionality, REST contracts, frontend, worker behavior, and database schema remain the v1 product baseline.
- **Purpose:** Add a model-facing MCP adapter so compatible AI hosts can call selected FinPilot capabilities.
- **Out of scope:** FinPilot v2.1 planning, changing financial product behavior, replacing the existing Anthropic-backed features, changing unrelated frontend flows, creating an MCP microservice, and exposing every existing write action in the first working model.
- **Build boundary:** The first working model demonstrates a signed-token, read-only MCP protocol path. The user later approved the local consent route and enabled Supabase OAuth and the token hook. All three initial tools have been exercised in local Inspector; verification in external AI hosts remains. The broader tool catalog below is not a commitment to implement every tool in this slice.

## Architecture decisions

1. **Host MCP inside the existing FastAPI application.** The MCP endpoint will run in the same process and deployment as the existing API. This reuses the established database session, Redis pool, authentication identity mapping, membership model, logging, and service code. It avoids introducing another network hop or another service's deployment and credentials.

2. **Keep the MCP code as an independent package.** MCP protocol setup, auth adaptation, schemas, tool handlers, MCP errors, and MCP logs will live under `app/mcp/`. Existing API routers will remain under `app/api/routes/`; MCP handlers will not be mixed into those routers.

3. **Make only a small FastAPI integration point.** `app/main.py` mounts the MCP ASGI endpoint and starts its session manager only when `MCP_ENABLED=true`. The default is disabled until the resource URL and OAuth configuration are supplied. Existing `/api/v1` routers, middleware behavior, and response contracts remain available and unchanged.

4. **Use `/mcp` as the protocol endpoint.** MCP will have its own endpoint instead of being modeled as REST routes under `/api/v1`. This keeps the JSON-RPC protocol boundary distinct from FinPilot's REST API versioning.

5. **Use Streamable HTTP as the supported remote transport.** It gives Claude, ChatGPT, and compatible Gemini clients an HTTPS endpoint. Legacy SSE and stdio are not part of the first implementation. The first client path is local MCP Inspector, followed by Gemini CLI after Supabase OAuth is configured.

6. **Use the MCP Python SDK rather than implementing MCP framing by hand.** Pin `mcp==2.3.0`. This major version uses `MCPServer` and its Streamable HTTP ASGI app; it is not the v1 `FastMCP` API. Tool/business logic remains ordinary FinPilot Python code behind the SDK boundary.

7. **Share domain logic, not route functions.** MCP handlers will call shared application/service functions. They will not invoke FastAPI endpoint functions directly and will not make loopback HTTP calls to FinPilot's own REST API.

8. **Extract shared logic only when needed by an MCP tool.** If a capability exists only inside a REST route, the implementation may move that logic into a service used by both entry points. This extraction must preserve existing REST behavior and be covered by the existing REST tests. No duplicate business rule or alternate financial calculation will be added to MCP handlers.

9. **Keep AI provider calls outside the MCP layer.** MCP will not need Claude, OpenAI, or Gemini API keys. The host's own model selects and calls the tools. FinPilot's existing Anthropic calls for invoice processing, categorization, financial Q&A, anomaly explanation, and digests stay as they are.

10. **Use one server identity and release label.** The MCP server will identify itself as `finpilot`; the project/release label for this layer is `v1.mcp`. The MCP protocol version negotiated by clients is independent and must be handled by the SDK.

## Authentication, identity, and tenant authorization

11. **Treat MCP authentication as a first-class design boundary.** Remote financial tools will not be unauthenticated, protected by one shared static API key, or exposed using a developer's personal token.

12. **Use Supabase OAuth 2.1 authorization-code with PKCE for remote user connections.** The MCP endpoint acts as a protected resource; Supabase Auth acts as authorization server and issues user tokens. MCP authorization metadata and bearer challenges follow the SDK's protected-resource implementation. Supabase redirects authorization to a configured application consent path, so that frontend dependency remains outside today's backend-only changes. See [Supabase OAuth setup](https://supabase.com/docs/guides/auth/oauth-server/getting-started).

13. **Do not assume an ordinary Supabase token is suitable for MCP.** FinPilot's existing REST validator expects audience `authenticated`; MCP accepts only a signed token whose `aud` equals the exact `MCP_PUBLIC_URL`, whose issuer matches the Supabase project, whose subject is a UUID, and whose role is `authenticated`. This keeps the REST token path unchanged and makes audience mismatch fail closed.

14. **Do not forward the inbound MCP token to another resource.** After validating the MCP token, the in-process adapter will resolve its subject to a FinPilot user and use that trusted user context for shared application logic. It will not pass the external token to a downstream API or provider.

15. **Resolve company access independently on every tool call.** `list_my_companies` has no company argument. Every company-specific tool requires an explicit `company_id`; the handler checks that the authenticated FinPilot user is a member of that company before accessing data.

16. **Never store an active company as shared server state.** Company identity must be part of each tool request and authorization context. A process-wide or MCP-session-wide active company could mix tenants during concurrent use.

17. **Preserve FinPilot roles as the final authorization authority.** Read tools are available to any authorized company member, including viewers. Any later write tool must enforce the existing owner/accountant permissions in backend code; client confirmation prompts do not grant permission.

18. **Use a signed MCP permission claim because Supabase does not issue custom OAuth scopes.** The Custom Access Token Hook must add `finpilot_permissions: ["read"]` and set `aud` to the exact MCP resource URL for OAuth access tokens. The verifier requires both. This replaces the original `finpilot:read` OAuth-scope proposal because Supabase's OAuth server currently supports only `openid`, `email`, `profile`, and `phone`; FinPilot membership and role checks remain mandatory. Any future write surface needs a separately reviewed signed permission claim plus the existing FinPilot role check. See [Supabase OAuth scopes](https://supabase.com/docs/guides/auth/oauth-server/oauth-flows) and [token hooks](https://supabase.com/docs/guides/auth/oauth-server/token-security).

## Tool surface

19. **Start with three read-only tools for the first working model.** These prove identity resolution, company selection, deterministic financial results, and host interoperability without introducing mutations:

    - `list_my_companies()` — returns up to 100 company IDs, names, currencies, roles, and available permissions, plus a `truncated` flag.
    - `get_cash_flow(company_id, start_date?, end_date?, granularity="month", cash_balance?)` — returns the existing bounded metrics contract. Dates are inclusive, the maximum range is 366 days, granularity is `day` or `month`, and an optional cash balance is request-only and is not persisted.
    - `get_budget_vs_actual(company_id, period)` — `period` is a valid `YYYY-MM` month and results come from FinPilot's existing deterministic calculation.

20. **Keep the initial MCP model read-only.** No transaction creation/edit/delete, invoice upload/confirmation, category or budget mutation, CSV import, company administration, or invitation actions are exposed in the first working model.

21. **Define the broader `v1.mcp` read-tool catalog from existing FinPilot capabilities.** After the first slice works, add the following as separately reviewable tools where useful:

    - Context: `get_company_context`, `list_categories`.
    - Metrics: `get_document_status_summary`.
    - Transactions: `list_transactions`, `get_transaction`, `list_transactions_for_review`.
    - Insights: `get_spending_anomalies`, `get_weekly_digest`.
    - Invoices: `list_invoices`, `get_invoice`.
    - Optional compatibility tool: `ask_financial_question`, delegating to the existing financial Q&A behavior. It is optional because that route already invokes Anthropic and would add a second model step when called from an AI host.

22. **Design each tool around a user task, not a one-to-one copy of REST.** Keep the catalog small, use clear descriptions and parameter limits, and expose only data needed for the requested task. Tools that reveal transaction descriptions or invoice details require explicit privacy review because results are returned to the host model.

23. **Treat write tools as a later increment within `v1.mcp`, not as a separate product version.** If approved later, candidates are transaction CRUD/review acceptance, budget CRUD, category CRUD, and invoice detail update/confirmation. File upload/import, membership administration, company deletion, and invitation management remain excluded until separately designed.

## Data contracts and financial safety

24. **Reuse existing request/response schemas where they express the right contract.** Add MCP-specific Pydantic input/output schemas under `app/mcp/schemas/` only where MCP needs a distinct shape. Validate all tool input before any query or mutation.

25. **Return structured, bounded results.** Use structured MCP content for facts and concise text for readability. Preserve ISO date strings and FinPilot's decimal amount representation; do not convert monetary values to floating point or recompute totals in the tool handler.

26. **Use existing FinPilot query bounds.** Preserve the 366-day cash-flow range, transaction pagination limits, bounded anomaly result sizes, database statement timeouts, and description truncation rules. Do not expose SQL, arbitrary filters, filesystem paths, or unrestricted record dumps as tool parameters.

27. **Do not expose invoice file downloads in the first working model.** Invoice metadata can be added as bounded read tools later. Binary document transfer and download links have client-specific privacy and handling implications and need a separate design.

28. **Treat all tool results as data that may be sent to the selected AI provider.** Return the minimum fields needed, avoid secrets and internal identifiers that are not useful, and document that FinPilot cannot control the host provider's retention policy.

## Error handling and observability

29. **Keep MCP errors separate from REST errors.** MCP protocol/argument errors will be represented using the SDK's MCP error mechanism. Expected tool execution failures will return a bounded tool error with a stable MCP-specific error code. Existing HTTP API error response shapes will not be changed.

30. **Map known failures consistently.** Invalid arguments map to validation errors; unauthenticated requests to HTTP 401; insufficient company membership or role to HTTP 403; missing scoped records to not-found; throttling to a rate-limit error; and dependency or unexpected failures to a generic temporary error. Never return SQL, stack traces, secrets, or provider internals to the model.

31. **Fail closed on identity, membership, database, and rate-limit checks.** A tool must not return data if its authorization check cannot complete. If MCP rate limiting uses Redis and Redis is unavailable, return a temporary error rather than bypassing the limit.

32. **Use MCP-specific structured logs.** Log a request/correlation ID, MCP method, tool name, MCP client name/version where supplied, FinPilot user ID, company ID, duration, outcome, and stable error code. Do not log bearer tokens, full prompts, raw result payloads, or unnecessary financial arguments.

33. **Keep rate limiting independently configurable.** Use an MCP-specific Redis key namespace `mcp:v1:<user_id>:<company_id-or-all>:<tool>:<minute-bucket>`, separate from the financial Q&A counter. The initial limit is 10 calls per minute per user/company/tool; Redis failure fails closed.

34. **Do not add an audit-table migration for the initial read-only slice.** Use structured MCP invocation logs for the first working model. Before write tools or production rollout, decide whether durable MCP audit records are required; any migration must be reviewed manually before application.

## Test and upgrade boundaries

35. **Keep MCP-specific tests in a distinct test module.** `tests/mcp/` covers signed-token verification, rejection of wrong audience/issuer/role/permission, protected-resource metadata, Streamable HTTP initialization and tool discovery, tenant membership, and rate limiting. Database-backed checks require the existing `*_test` PostgreSQL setup.

36. **Preserve the existing FinPilot test suite as a regression gate.** MCP tests must not require real LLM calls. Shared service extractions must retain API-level regression coverage. A change to an MCP tool should not change an existing REST contract.

37. **Keep MCP settings separately named.** `MCP_ENABLED`, `MCP_PUBLIC_URL`, `MCP_READ_CALLS_PER_MINUTE`, `MCP_MAX_SESSIONS`, `MCP_SESSION_IDLE_TIMEOUT_SECONDS`, and `MCP_ALLOWED_BROWSER_ORIGINS` live in `app/mcp/settings.py`; defaults keep MCP disabled until configured. Do not overload Anthropic model settings or Financial Q&A settings.

38. **Keep MCP dependency and lifecycle changes local.** Pin the SDK at `mcp==2.3.0`; initialize the Streamable HTTP session manager through the FastAPI lifespan and share only the existing Redis pool. MCP startup validation is separate from API route logic; no MCP database migration is needed.

39. **Version the tool catalog with compatibility in mind.** Keep stable tool names and avoid breaking input/output changes silently. Tool catalog changes require host refresh/retesting. `v1.mcp` labels this first integration; it does not imply a new FinPilot core version or an MCP protocol release number.

## Implementation decisions and remaining external setup

40. **Build the first tool catalog as three read-only tools.** The implemented names are `list_my_companies`, `get_cash_flow`, and `get_budget_vs_actual`. They return validated structured content and perform no writes.

41. **Share metrics logic through a service.** Cash-flow range validation, cash-balance validation, aggregate SQL, budget-vs-actual SQL, and deterministic formatting live in `app/services/metrics.py` and are called by both REST and MCP. The REST route remains responsible for HTTP validation and its existing response contract.

42. **Resolve MCP users without creating or mutating FinPilot accounts.** Each tool maps the signed token's Supabase `sub` to an existing `User.auth_user_id`. An unknown subject fails with `identity_not_linked`; it does not create a user or auto-link by email. A user must already have completed normal FinPilot account provisioning.

43. **Check membership for every company-scoped call.** The company ID is a required tool argument. The server queries `company_members` for that user/company pair on every call and returns the same non-enumerating access-denied error for missing companies and non-members.

44. **Keep tool and server failures bounded.** Expected tool failures use stable code prefixes such as `invalid_arguments`, `company_access_denied`, `rate_limited`, and `temporary_failure`. Unexpected database details and traces are logged server-side and are not returned to the model.

45. **Use stateful Streamable HTTP sessions with bounded capacity.** The SDK app uses a 1 MiB request-body limit, a maximum of 100 open sessions, and a 30-minute idle timeout. MCP sessions carry no active-company state; identity and company authorization are resolved for every tool call.

46. **Use explicit transport and URL safety.** `MCP_PUBLIC_URL` must be the canonical `/mcp` URL; remote URLs must use HTTPS. Only loopback HTTP is accepted for local development. DNS-rebinding protection remains enabled, with the resource host and local Inspector origins allow-listed. MCP-only CORS permits loopback browser clients by default; other browser origins must be explicitly configured in `MCP_ALLOWED_BROWSER_ORIGINS`.

47. **Do not change database schema or add MCP audit tables.** MCP uses existing users, companies, memberships, transactions, and budgets; no migration is needed for this read-only slice.

48. **Keep MCP opt-in and preserve existing app startup by default.** `MCP_ENABLED` defaults to `false`; enabling it without `MCP_PUBLIC_URL` or `SUPABASE_URL` fails startup with a configuration error instead of exposing a partially configured endpoint.

49. **Implement OAuth consent in the existing frontend after the backend checkpoint.** The route is `/oauth/consent`, uses the existing Supabase browser client and session, preserves `authorization_id` through sign-in, displays the requesting client/scopes plus the exact read-only MCP capabilities, and calls Supabase's get/approve/deny authorization methods. It adds no service key, database write, or migration. Sign-in redirects now honor a validated internal `next` path so OAuth consent returns to the pending request.

50. **Start host verification locally.** The MCP protocol is checked with signed test tokens and the official Streamable HTTP client. Local MCP Inspector is the first manual host target; Gemini CLI follows once OAuth is enabled. A public deployment URL and HTTPS reverse-proxy configuration must be selected before Claude, ChatGPT, or cloud-hosted Gemini connections.

51. **Limit the token hook to Supabase OAuth-client tokens.** The hook will set `aud` to the configured MCP resource URL and add `finpilot_permissions: ["read"]` only when `authentication_method` is `oauth` or `token_refresh` and the token contains a `client_id`. Password, OTP, and external identity-provider tokens keep the ordinary `authenticated` audience. The active ECC P-256 key is ES256 and the MCP verifier validates it through the Supabase JWKS endpoint; the previous HS256 key is left in place during the test.

## Remaining build gates

- Supabase OAuth Server and dynamic client registration are enabled; the selected Site URL is `http://localhost:5173` and the authorization path is `/oauth/consent`. Supabase uses Site URL for default auth redirects too, so restore the appropriate production value after local testing if needed.
- The user reports the Custom Access Token Hook is saved and enabled with the exact local MCP audience `http://localhost:8000/mcp` and `finpilot_permissions: ["read"]` for OAuth-client tokens. Inspector has an authenticated MCP session after the temporary JWKS network fix; `list_my_companies` succeeded with the linked identity, and the user reports both financial report tools succeeded. Retain `authenticated` audience for standard FinPilot REST/provider tokens.
- The active signing key is ECC P-256, corresponding to ES256; keep the previous HS256 key during testing. No signing-key settings need to change for this local setup.
- Enable the adapter locally with `MCP_ENABLED=true` and `MCP_PUBLIC_URL=http://localhost:8000/mcp`; production requires the externally reachable HTTPS `/mcp` URL.
- PostgreSQL and Redis are running and healthy; run the database-backed MCP tenant and metrics regression checks against the guarded `*_test` database.
- Verify each named AI host separately after OAuth and deployment configuration; client support and deployment requirements differ.
- Add an account-side connected-apps/grant revocation screen before treating host connections as production-complete.

## Repository references checked

- `docs/ARCHITECTURE.md` — current stack, financial Q&A, metrics, transactions, and tenant-isolation contracts.
- `docs/REQUIREMENTS.md` — deterministic financial calculations, LLM validation, and company data-isolation constraints.
- `docs/ENGINEERING_LOG.md` — current implementation status and remaining deployment/verification notes.
- `app/main.py` — FastAPI app lifespan, API registration, and opt-in MCP mount.
- `app/api/deps.py` and `app/core/security.py` — current Supabase token verification, user resolution, and company membership checks.
- `app/api/routes/companies.py`, `metrics.py`, `transactions.py`, `insights.py`, `digests.py`, and `invoices.py` — existing functions that could back future MCP tools.
- `app/services/financial_qa.py`, `app/services/cash_flow.py`, and `app/services/metrics.py` — deterministic financial logic and shared metrics queries.
- `docker-compose.yml` — current PostgreSQL, Redis, and worker services; no API service is defined.
- [MCP transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [MCP authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization), and current host documentation for Claude, ChatGPT, and Gemini.
