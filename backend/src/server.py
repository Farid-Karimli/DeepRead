import hashlib
import io
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import pypdf
import asyncio

from src.agent import Agent
from src.celery_tasks import analyze_paper_task, celery, test_task
from src.paper_analysis_cache import get_cached_result, set_cached_result

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
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        # Just show the first 4 characters to confirm it's there
        return {"status": "Loaded", "prefix": f"{key[:4]}..."}
    return {"status": "Not Found"}

@app.get("/test-claude-code")
def test_claude_code():
    agent = Agent()
    result = asyncio.run(agent._test_claude_code())
    return {"result": result}

##########################################
##### Paper Content Upload #######################
##########################################

@app.post("/analyze")
def analyze_paper(file: UploadFile = File(...)):
    raw = file.file.read()
    paper_id = hashlib.sha256(raw).hexdigest()

    cached = get_cached_result(paper_id)
    if cached is not None:
        return {"paper_id": paper_id, "status": "complete", "result": cached}

    paper_content = _paper_bytes_to_text(raw, file.filename)
    paper_content = _normalize_whitespace(paper_content)

    task = analyze_paper_task.delay(
        paper_content=paper_content,
        paper_id=paper_id,
        original_filename=file.filename,
    )
    return {"paper_id": paper_id, "status": "pending", "task_id": task.id}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("src.server:app", host="0.0.0.0", port=port)