# DeepRead

Bridging the gap between academic papers and their implementations. Upload a research PDF (or provide a link); DeepRead locates the paper’s GitHub repository, segments the document with PaperMage, and uses an LLM agent to map key sections to code. The web UI shows the PDF next to the repo: section highlights link paper regions to implementation snippets, and you can select text in the paper or code in the repo to request on-demand mappings. Results are cached in Supabase so repeat visits load quickly.

This project is developed at Boston University.

## Get Started

You need an Anthropic API key and a Supabase project (`SUPABASE_URL`, `SUPABASE_KEY`) for paper storage and mapping cache.

**Docker**

```bash
git clone https://github.com/Farid-Karimli/DeepRead.git
cd DeepRead
cp env.docker.example .env
# Edit .env: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY
docker compose up --build
```

Open http://localhost:8080 for the UI and http://localhost:8000 for the API. Compose starts Redis, the FastAPI server, a Celery worker, and the built frontend.

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
