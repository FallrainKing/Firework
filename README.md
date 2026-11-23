# Firework

**An agent-powered workspace for discovering, reading, and organizing research.**

[中文](README.zh-CN.md) · [Documentation](docs/README.md) · [Roadmap](docs/ROADMAP.md) · [Report an issue](https://github.com/FallrainKing/Firework/issues)

Firework brings your paper library, PDF reader, and research conversations into one workspace. It connects to an existing Claude Code agent and extends its capabilities through Skills, while the application manages documents, sessions, tasks, evidence, and account isolation.

## Start here

- [Usage guide](docs/usage.md): configure a connection and budget, import a PDF, and start a reading session.
- [System architecture](docs/架构.md): deployed components, data boundaries, and how the agent executes tasks.
- [Implementation status](docs/STATUS.md): current scope and verification limits.
- [Project audit](docs/PROJECT-AUDIT.md) (Chinese): documentation map, requirement coverage, and unfinished architecture work.

The current baseline uses business migrations through **0022**, identity schema **3**, Runner protocol **8**, and Zotero plugin **0.1.4**.

## Features

- **Reading workspace:** Start from recent papers, research categories, and reusable task templates.
- **Tabbed PDF reader:** Open multiple papers in a resizable three-panel layout, with reading aids on the left, the original PDF in the center, and an agent conversation on the right. Restore reading positions, layout preferences, and drafts.
- **Paper discovery and import:** Search for papers and add them through PDF uploads, arXiv identifiers, DOIs, and supported public URLs. Organize papers by category and reading status, with visual cards, author affiliations, and abstracts. Rename or move personal category trees, or remove and restore them without deleting their papers.
- **PDF files and versions:** Keep immutable main-text revisions and supplementary PDFs, choose a default reading version, and inspect annotations per version. Download original PDFs, PDFs with standard annotations, or annotation Markdown without invoking the research agent.
- **Persistent research conversations:** Keep tasks linked to agent sessions so you can revisit and continue previous work. Track execution progress, cancel runs, and inspect reported usage.
- **On-demand reading guides:** Explicitly trigger a Skill to produce structured explanations and annotations linked to paper evidence. Opening or switching papers does not automatically run a reading guide.
- **Research frontier tracking:** Define topics, keywords, authors, or teams. Use the agent to discover papers and open-source projects, generate deduplicated timeline reports, and approve discoveries before adding them to your library.
- **Extensible Skills:** Upload Skill ZIP packages, validate and install them, manage categories and versions, and enable or disable capabilities. Templates and structured outputs connect Skills to the interface.
- **Richer agent input:** Combine editable templates, selected paper passages, and image attachments. Image interpretation requires a vision-capable agent or model.
- **Manual Zotero exchange:** Pair a local Zotero 10 client, exchange selected papers, collection paths, tags, and immutable PDF files, and retry transfers without research-model calls. Imported PDFs become readable without waiting for embeddings; full-text indexing is an explicit action. Native annotation sync and automatic Connector ingestion are planned. See the [setup guide](docs/usage.md#9-zotero-手动双向交换).
- **Personal model connections:** Configure an Anthropic Messages-compatible API, encrypted credentials, model name, declared vision/context capabilities, and a research role in the Web UI. Sessions bind a connection revision; custom runs do not inherit host Claude credentials. Per-account and per-run budgets are configurable. Capability checks are configuration-only and do not invoke a model.
- **Account isolation:** Separate each account's research database, files, private Skills, vector collection, and agent workspace. Public registration is currently closed, and the default release permits only the primary administrator to log in.

Firework is under active development. Unified knowledge entries, cross-task long-term memory, OCR-based reading guides, and a complete six-stage deep-reading workflow are planned rather than complete. See the [implementation status](docs/STATUS.md) and [roadmap](docs/ROADMAP.md).

## How it works

```text
Browser · Vue reading workspace
            |
FastAPI · authentication, library, sessions, tasks, evidence
       |                   |                    |
SQLite + files          Qdrant           Private host Runner
                                                |
                                      Existing Claude Code agent
                                                |
                                        Registered Skills
```

The application handles management and persistence. Research operations run through the existing agent and its Skills. The private Runner connects agent execution to application tasks and preserves native session mappings.

Templates, previews, and paper navigation do not themselves invoke the research model. Sending an agent request, confirming a guide, or running a configured schedule can incur model usage.

## Technology stack

| Layer | Technologies |
| --- | --- |
| Frontend | Vue 3, TypeScript, Vite, Pinia |
| Document viewing | PDF.js; Marked with DOMPurify for Markdown |
| Backend | Python 3.12+, FastAPI, SQLite |
| Semantic search | Qdrant and bge-m3 embeddings |
| Agent execution | Claude Code CLI through a private host Runner |
| Deployment | Docker Compose, a host-side Runner service, and an HTTPS reverse proxy |

## Getting started

Firework currently targets self-hosted deployments. The repository includes configuration from an existing deployment; adapt its paths, network bindings, and HTTPS origin before starting a new instance.

### Prerequisites

- Docker Engine and Docker Compose.
- Python 3.12+ and a host-side virtual environment for the Runner and maintenance tools.
- An installed Claude Code CLI. Configure personal API connections in the Web UI, or retain the primary administrator's existing host configuration.
- Storage for papers, databases, backups, and the approximately 2.3 GB bge-m3 model cache.
- Node.js 24 for local frontend development. Production frontend assets are built inside Docker.

### Installation outline

```sh
git clone https://github.com/FallrainKing/Firework.git
cd Firework
cp .env.example .env
```

Before starting services:

1. Set `RESEARCH_PUBLIC_ORIGIN` in `.env` to your HTTPS origin. Keep secure session cookies enabled for production.
2. Adapt the port bindings in `docker-compose.yml`. The additional `100.64.0.7:8600` binding belongs to the original deployment and must be removed or replaced on another host.
3. Prepare the bge-m3 model cache. Compose defaults to `HF_HUB_OFFLINE=1`; a fresh installation needs an intentional initial download with offline mode disabled.
4. Install and configure the host Runner using the [deployment guide](docs/enviroment.md). Update the working directory, executable paths, and model selection in the service template for your installation. Personal connections are configured under **Model connections** in the user menu. Only the primary administrator's legacy mode reads the existing host configuration; custom connections use isolated environments.
5. Initialize the administrator locally. On a new installation, use the interactive command below; no public registration or default password is provided.

```sh
# Run after preparing the host virtual environment and dependencies.
.venv/bin/python -m app.auth.bootstrap init-admin

# Build and start the application, vector database, and backup service.
docker compose up -d --build
```

Starting Compose alone does not start the host Runner. Both components must be ready for agent tasks to work. The current application requires Runner protocol **7**.

Open your configured HTTPS address and sign in with your administrator account. See the [user guide](docs/usage.md) for importing papers, reading, conversations, and Skills.

For upgrades, back up the identity database and research resources together, check for running tasks, and follow the [deployment](docs/enviroment.md) and [backup and recovery](docs/BACKUP-RESTORE.md) instructions.

## Development

### Frontend

```sh
cd frontend
npm ci
npm run dev
npm test
npm run build
```

The development proxy expects an API at `127.0.0.1:8600`. Adapt the proxy and authentication origin for your development setup; production secure-cookie settings are intended for HTTPS.

### Backend and Runner

```sh
python3.12 -m venv .venv
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pytest
```

Backend execution also requires reachable Qdrant and the embedding model cache. Use isolated data directories for development and tests. See the [development guide](docs/DEVELOPMENT.md) for selecting regression tests and running authenticated, model-free smoke checks.

## Documentation

Most detailed implementation and operations documents are currently in Chinese.

| Document | Contents |
| --- | --- |
| [Documentation index](docs/README.md) | Current usage, architecture, and maintenance references |
| [User guide](docs/usage.md) | Paper import, reading, conversations, and tracking |
| [Architecture](docs/架构.md) | Current deployment, account isolation, data models, and execution flow |
| [Runner configuration](docs/RUNNER-CONFIGURATION.md) | Personal connections, encrypted credentials, budgets, and session binding |
| [Authentication](docs/AUTHENTICATION.md) | Account isolation, login restrictions, and recovery |
| [Deployment](docs/enviroment.md) | Environment setup, operations, and troubleshooting |
| [Development](docs/DEVELOPMENT.md) | Local development, testing, and releases |
| [API](docs/API.md) · [Route inventory](docs/API-ROUTES.md) | API contracts and endpoints |
| [Skill development](docs/SKILLS.md) | ZIP packages, versions, tools, and output contracts |
| [Backup and recovery](docs/BACKUP-RESTORE.md) | Backups and restoration |
| [Status](docs/STATUS.md) · [Roadmap](docs/ROADMAP.md) | Implemented scope and upcoming work |

## Contributing

Bug reports and improvement proposals are welcome through [GitHub Issues](https://github.com/FallrainKing/Firework/issues). For code changes, describe the problem, keep the scope focused, include relevant verification, and update affected documentation. Discuss substantial architectural changes before submitting a pull request.

Never commit credentials, `.env`, private keys, personal papers, runtime data, or backups. Legacy `research-assistant` directory, service, and package identifiers remain in some deployment files for compatibility.

## License

A project-level license has not yet been added. Do not assume an open-source license from the repository's public visibility; third-party components retain their respective licenses.

## External agent integration

Create scoped, expiring API authorization in Settings → External agent access. Download the portable paper-operation Skill to search your library, update metadata and manage PDF annotations from another compatible agent. This gateway does not invoke the server model. Execution profiles now combine versioned Skills, model connections, budgets, roles and narrowed built-in MCP tools. See the [integration design and API](docs/EXTERNAL-AGENT-API.md).


### Research workspace

Firework includes versioned research artifacts, PDF-bound evidence, reviewed knowledge candidates, and a run inspector with durable event replay. An optional isolated Claude terminal uses per-session containers and a model-only relay. See [implementation and operational boundaries](docs/RESEARCH-PLATFORM.md).
