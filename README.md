# Darwin AI Workbench

Governed, multi-agent AI platform for finance and EPM teams. Built to Darwin Analytics v5.0 specification.

## Project Status

**Phase 0 - Minimal Viable Workstation (MVW)**

Currently building the MVW per Section 02 of the v5.0 spec. Target: working council connected to a real SAP BPC MS environment, deployable in under 20 minutes in a clean AWS account (acceptance criterion AC-00).

## Architecture

Four-layer architecture per spec Section 01:

- **Layer 1 - Workstation**: Stateless compute. LangGraph, MCP servers, UI.
- **Layer 2 - Organization**: Shared persistent infrastructure (DynamoDB, S3, RAG, Bedrock endpoint).
- **Layer 3 - Darwin Platform**: Software updates, licensing, Marketplace.
- **Layer 4 - Darwin Hive**: Anonymized cross-org telemetry (no customer data, ever).

## Repo Structure

Follows Section 15 of the v5.0 spec:

| Folder | Purpose |
|---|---|
| `agents/` | Council agent system prompts (YAML) + council config |
| `mcp/` | MCP platform servers (SAP_BPC_MS in MVW; more in Phase 1+) |
| `orchestration/` | LangGraph graph, nodes, CIM state model, request classifier |
| `pipelines/` | Agentic pipeline definitions (Phase 1+) |
| `rag/` | Knowledge base source documents (Phase 1+) |
| `engagements/` | Per-engagement branches (runtime) |
| `ui/` | React Workbench UI |
| `lambdas/` | Lambda functions (14 per Section 19) |
| `infra/` | Terraform/CDK provisioning |
| `tests/` | Unit + integration tests |
| `docs/` | ADRs, runbooks, SOC 2 control mapping |

## Development

Requires Python 3.12 (managed by uv) and Node 22 LTS (for UI).

    uv sync          # install Python 3.12 + dependencies
    uv run pytest    # run tests

## Confidentiality

This repository is confidential. Darwin v5.0 specification is NDA-required.
