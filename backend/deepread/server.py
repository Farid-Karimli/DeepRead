import hashlib
import io
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import pypdf

from deepread.celery_tasks import analyze_paper_task, celery, test_task

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

##########################################
##### Paper Content Upload #######################
##########################################

@app.post("/analyze")
def analyze_paper(file: UploadFile = File(...)):
    raw = file.file.read()
    # Stable id for caching: same bytes => same key (filename alone can collide).
    paper_id = hashlib.sha256(raw).hexdigest()
    paper_content = _paper_bytes_to_text(raw, file.filename)
    paper_content = _normalize_whitespace(paper_content)

    task = analyze_paper_task.delay(
        paper_content=paper_content,
        paper_id=paper_id,
        original_filename=file.filename,
    )
    return {"task_id": task.id, "paper_id": paper_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)