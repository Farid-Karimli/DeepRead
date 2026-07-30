# DeepRead

Bridging the gap between academic papers and their implementations. Upload a research PDF (or provide a link); DeepRead locates the paper’s GitHub repository, segments the document with PaperMage, and uses an LLM agent to map key sections to code. The web UI shows the PDF next to the repo: section highlights link paper regions to implementation snippets, and you can select text in the paper or code in the repo to request on-demand mappings. Results are cached in Supabase so repeat visits load quickly.

This project is developed at Boston University.

## Get Started

You need an Anthropic API key and a Supabase project (`SUPABASE_URL`,
`SUPABASE_SECRET_KEY`) for paper storage and mapping cache.

**Docker Compose (single VM)**

Install Docker Engine with the Compose plugin on a Linux VM. The stack runs the
frontend/reverse proxy, FastAPI server, Celery worker, and Redis on that VM and
publishes only one port. Anthropic and Supabase remain external managed
services, so their credentials are required.

```bash
git clone https://github.com/Farid-Karimli/DeepRead.git
cd DeepRead
cp env.docker.example .env
# Edit .env: ANTHROPIC_API_KEY, SUPABASE_URL, and SUPABASE_SECRET_KEY
docker compose up --build -d
docker compose ps
```

Open `http://VM_IP:8080`. API requests use the same public origin under
`/api`, while the API and Redis ports remain private to the VM's Docker
network. To use another public port, change `APP_PORT` in `.env`; also allow
that TCP port in the VM firewall/security group.

Useful operations:

```bash
docker compose logs -f
docker compose restart
git pull && docker compose up --build -d
docker compose down
```

`docker compose down` preserves the Redis and worker cache volumes. Add `-v`
only when you intentionally want to erase them. Apply the SQL migrations in
`supabase/migrations/` to the configured Supabase project before first use.

**Local development**

Requires [uv](https://docs.astral.sh/uv/), Node.js, and Redis on port 6379.

```bash
git clone https://github.com/Farid-Karimli/DeepRead.git
cd DeepRead
cp env.docker.example .env
# Add Supabase keys; REDIS_URL defaults to redis://localhost:6379/0

cd backend && uv sync
cd ../frontend && npm install
cd .. && make up
```

UI at http://localhost:5173, API at http://localhost:8000. Use `make down`, `make status`, and `make logs` to manage processes.

For Cloud Run deployment, see `deploycommands.md`.

## Roadmap

### Matching Engine

Code-to-content matching pipeline.

- [**DONE**] v0.1: Reranking query from `prompt` → `content` in `agent:map_content_to_code`
- [**DONE**] v0.5: Add few-shot instructions for content type and span calibration in prompt
- [**DONE**]v0.7: Search a map of codebase symbols, definitions and calls, not local codebase files.
  - Create a Repo Map with per-file annotations (classes, methods, definitions, calls, etc.)
  - Planner agent: Identify relevant files and suggest tree-sitter code symbol hints (references, search terms) - powered by a single Anthropic API call (with the repo map supplied in the prompt), not a Search / ReadFile crawl through the Claude Code harness.
- [IN PROGRESS] v0.8-v0.9: Search Planner + Resolver
  - Resolver agent, 2 types: menu and guided-crawl.
    - Menu (v0.8): Pinpoint specific symbols and line ranges for finding matches, informed by the Search Planner's output as hints. This is powered by a single API call to Claude, with snippets of the repo map supplied in the prompt. No crawling and no custom tools.
    - Guided-crawl (v0.9): Crawl the codebase to find matches, guided by the Search Planner's output as hints. This is powered by a custom agentic-harness with custom tools for reading codebase files, symbols and calls.
- v1.0: Past Memory
  - Retrieve and reuse previously discovered code snippets, search scopes and matches.
  - Decide best way to surface memory to the agent (e.g., through prompt context)

Optimize for model cost and performance.

### AI Matches 

- v1.0: Scalable Search
  - Plan and enable parallel search for large papers and codebases. Integrate best working techniques from the Matching Engine.

### UI

- [IN PROGRESS] Copilot Chat in the bottom right corner of the page: Ask further questions about the paper, code, or matches.
