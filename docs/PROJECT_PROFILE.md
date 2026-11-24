# FinPilot project profile

Use the wording below as a starting point for a portfolio or resume. The live deployment claim should be updated only after the production URL and smoke checks are complete.

## Short description

FinPilot is a multi-tenant finance operations app that turns small-business transactions and invoices into useful cash-flow, budget, and review workflows.

## Portfolio description

FinPilot is a full-stack financial operations project for small businesses. It combines a React and TypeScript workspace with a FastAPI/PostgreSQL backend, asynchronous Redis/arq jobs, and a constrained AI layer for invoice extraction, transaction categorization, financial Q&A planning, anomaly explanations, and weekly summaries. Financial totals and decisions stay in deterministic application code; uncertain AI categorizations are routed to people for review. The product includes company roles, CSV import, invoice review, cash-flow and budget reports, and a deployment path using Vercel and Render.

## Resume-ready bullets

- Built a multi-tenant financial operations application with FastAPI, SQLAlchemy, PostgreSQL, Alembic, React, TypeScript, and a generated OpenAPI client.
- Implemented company-scoped financial workflows for transaction management, bank CSV import with duplicate protection, invoice review, budgets, and cash-flow reporting.
- Added Redis/arq jobs for invoice extraction and transaction categorization, with constrained model outputs, validation, retries, and human review for uncertain results.
- Designed AI-assisted financial Q&A, anomaly explanations, and weekly digests while keeping financial calculations and query execution in deterministic backend code.
- Added backend and frontend test suites covering tenant isolation, role-based access, worker behavior, API contracts, and key user flows.

## One-line resume version

**FinPilot — Full-stack financial operations app:** FastAPI, PostgreSQL, React/TypeScript, Redis/arq, Supabase Auth, and constrained Anthropic workflows for invoices, categorization, financial Q&A, and reporting.

## Current delivery wording

Until deployment is complete, describe FinPilot as an implemented product project with deployment configuration prepared. After the URL is live and the deployed smoke checks pass, change that to “deployed and user-testable on Vercel.” Do not describe it as a commercial product or claim real-world accuracy without measured labeled-sample results.
