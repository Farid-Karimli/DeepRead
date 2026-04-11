import hashlib
import io
import os

from fastapi import FastAPI, File, HTTPException, UploadFile, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import pypdf
import asyncio

from src.agent import Agent
from src.celery_tasks import analyze_paper_task, celery, test_task
from src.db import get_file_url, upload_paper_to_storage
from src.paper_analysis_cache import get_cached_result, iter_cached_results, set_cached_result
from src.utils import download_file as download_file_from_url

app = FastAPI()


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5178",
        "http://127.0.0.1:5178",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_whitespace(text: str) -> str:
    lines = text.split("\n")
    text = "\n".join(lines)
    return " ".join(text.split())


def _paper_bytes_to_text(raw: bytes, filename: str | None = None) -> str:
    """
    Plain text: UTF-8 (with replacement if needed).
    PDF: extract text via pypdf (not OCR; scanned PDFs may be empty).
    """
    if raw.startswith(b"%PDF-"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        parts: list[str] = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
        extracted = "\n\n".join(parts).strip()
        if not extracted:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not extract text from this PDF (it may be scanned or image-only). "
                    "Try a text-based PDF or upload a .txt export."
                ),
            )
        return extracted

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")

@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

@app.get("/tasks/{task_id}")
def task_status(task_id):
    task = celery.AsyncResult(task_id)
    response = {"status": task.status}
    if task.ready():
        response["result"] = task.result
    if task.status == "FAILURE":
        exc = task.result
        response["error"] = str(exc) if exc is not None else "Unknown error"
    return response

##########################################
##### Test Tasks ########################
##########################################

@app.get("/test")
def test():
    task = test_task.delay()
    return {"task_id": task.id}

@app.get("/debug-env")
async def debug_env():
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    db_url = os.getenv("SUPABASE_URL")
    db_key = os.getenv("SUPABASE_KEY")
    if anthropic_key and db_url and db_key:
        # Just show the first 4 characters to confirm it's there
        return {"status": "Loaded", "prefix": f"{anthropic_key[:4]}...", "db_url": f"{db_url[:4]}...", "db_key": f"{db_key[:4]}..."}
    return {"status": "Not Found"}

@app.get("/test-claude-code")
def test_claude_code():
    agent = Agent()
    result = asyncio.run(agent._test_claude_code())
    return {"result": result}

##########################################
##### Paper Content Upload #######################
##########################################


def _paper_list_item(paper_id: str, result: dict) -> dict:
    """Lightweight row for the home page (full result available via GET /papers/{id})."""
    github = result.get("github_repo_url")
    title = result.get("paper_title")
    code_result = result.get("code_result") or {}
    sections = code_result.get("sections") if isinstance(code_result, dict) else None
    n_sections = len(sections) if isinstance(sections, list) else 0
    label = None
    if isinstance(title, str) and title.strip():
        label = title.strip()
    elif n_sections and isinstance(sections[0], dict):
        label = sections[0].get("section_name")
    return {
        "paper_id": paper_id,
        "paper_title": title if isinstance(title, str) else None,
        "github_repo_url": github,
        "section_count": n_sections,
        "label": label,
    }


@app.get("/papers")
def list_papers():
    rows = [_paper_list_item(pid, res) for pid, res in iter_cached_results()]
    rows.sort(key=lambda r: r["paper_id"])
    return {"papers": rows}


@app.get("/papers/{paper_id}")
def get_paper_by_id(paper_id: str):
    cached_result = get_cached_result(paper_id)
    url = get_file_url(paper_id) # Raw file bytes for viewing
    if url is None:
        raise HTTPException(status_code=404, detail="Unknown paper_id or file not found")

    if cached_result is None:
        raise HTTPException(status_code=404, detail="Unknown paper_id or cache expired")
    return {"paper_id": paper_id, "result": cached_result, "file_url": url}


@app.post("/analyze")
def analyze_paper(file: UploadFile = File(...)): 
    if not file.file:
        raw = download_file(file.link)
    else:
        raw = file.file.read()
    paper_id = hashlib.sha256(raw).hexdigest()
    filename = file.filename

    try:
        upload_paper_to_storage(paper_name=filename, paper_id=paper_id, paper_content=raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    cached = get_cached_result(paper_id)
    if cached is not None:
        return {"paper_id": paper_id, "status": "complete", "result": cached}

    paper_content = _paper_bytes_to_text(raw, filename)
    paper_content = _normalize_whitespace(paper_content)

    task = analyze_paper_task.delay(
        paper_content=paper_content,
        paper_id=paper_id,
        original_filename=file.filename,
    )
    return {"paper_id": paper_id, "status": "pending", "task_id": task.id}

@app.get("/download_file")
def download_file(link: str) -> Response:
    return Response(content=download_file_from_url(link), media_type="application/pdf")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("src.server:app", host="0.0.0.0", port=port)