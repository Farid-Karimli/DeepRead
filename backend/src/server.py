import hashlib
import io
import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, Response, Form, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
import uvicorn
import asyncio

from src.agent import Agent
from src.celery_tasks import (
    analyze_paper_task, 
    celery, 
    test_task, 
    process_pdf_task, 
    map_content_to_code_task, 
    map_code_to_content_task
)
from src.db import (get_file_url, 
    upload_paper_to_storage, 
    get_mapping_by_cache_key, 
    get_paper_record_by_id, 
    get_all_paper_records, 
    get_content_to_code_matches_by_paper_id, 
    get_code_to_content_matches_by_paper_id_and_filepath,
    get_user_by_username_db,
    create_user_db
)

from src.utils import download_file as download_file_from_url, get_file_content, get_repo_tree
from src.types import PaperRecord, PaperContentBox, UserRecord

logger = logging.getLogger(__name__)

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

###################################
##### Users #######################
###################################

@app.get('/user')
def get_user_by_username(username: str) -> dict:
    user = get_user_by_username_db(username)
    if user is None:
        logger.warning(f"Username {username} not found, creating new user...")
        user = create_user_db(username)
        if user is None:
            raise HTTPException(status_code=500, detail="Failed to create user")
    return user.model_dump(mode="json")

###################################
##### Paper Content Upload ########
###################################


def _paper_list_item(paper: PaperRecord) -> dict:
    """Lightweight row for the home page (full result available via GET /papers/{id})."""
    code_result = paper.analysis_result.code_result if paper.analysis_result else None
    match_count = 0
    if code_result is not None:
        if code_result.matches:
            match_count = len(code_result.matches)
        elif code_result.sections:
            match_count = len(code_result.sections)
    return {
        "paper_id": paper.id,
        "paper_title": paper.paper_title,
        "github_repo_url": paper.github_link,
        "section_count": match_count,
        "label": paper.paper_title,
    }


@app.get("/papers")
def list_papers():
    results = get_all_paper_records()
    rows = [_paper_list_item(paper) for paper in results]
    return {"papers": rows}


@app.get("/papers/{paper_id}")
def get_paper_by_id(paper_id: str):
    """
        Gets the paper record from the database.
        Also returns the public storage URL for the raw file.
    """

    paper_record: PaperRecord | None = get_paper_record_by_id(paper_id)
    url = get_file_url(paper_id) # Raw file bytes for viewing

    if paper_record is None:
        raise HTTPException(status_code=404, detail="Unknown paper_id or file not found")

    return {"paper_id": paper_id, "analysis_result": paper_record.analysis_result, "papermage_result": paper_record.papermage_result, "file_url": url}


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

    paper_record: PaperRecord | None = get_paper_record_by_id(paper_id)
    if paper_record is not None:
        result = {
            'analysis': paper_record.analysis_result,
            'processed': paper_record.papermage_result
        }
        return {"paper_id": paper_id, "status": "SUCCESS", "result": result}

    paper_content = _paper_bytes_to_text(raw, filename)
    paper_content = _normalize_whitespace(paper_content)

    task = analyze_paper_task.delay(
        paper_content=paper_content,
        paper_raw=raw,
        paper_id=paper_id,
        original_filename=file.filename,
    )
    return {"paper_id": paper_id, "status": "PENDING", "task_id": task.id}

@app.get("/download_file")
def download_file(link: str) -> Response:
    return Response(content=download_file_from_url(link), media_type="application/pdf")

@app.post("/process_pdf")
def process_pdf(file: UploadFile = File(...)):
    if not file.file:
        raw = download_file(file.link)
    else:
        raw = file.file.read()
    task = process_pdf_task.delay(
        file_raw=raw
    )
    return {"task_id": task.id}

##########################################
##### Ad-Hoc Mapping #######################
##########################################

@app.get("/get_content_to_code_matches")
def get_content_to_code_matches(paper_id: str):
    matches = get_content_to_code_matches_by_paper_id(paper_id)
    return {"matches": [match.model_dump(mode="json") for match in matches]}

@app.get("/get_code_to_content_matches")
def get_code_to_content_matches(paper_id: str, current_path: str):
    matches = get_code_to_content_matches_by_paper_id_and_filepath(paper_id, current_path)
    return {"matches": [match.model_dump(mode="json") for match in matches]}

@app.post("/map_content_to_code")
def map_content_to_code(
    content: str = Form(...),
    repo_url: str = Form(...),
    context: str = Form(...),
    paper_id: str = Form(...),
    box: str = Form(...),
    page_number: int = Form(...),
    user_id: int = Form(...),
):
    try:
        parsed_box = PaperContentBox.model_validate_json(box)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid box payload: {exc}")

    cache_key = hashlib.sha256(
        f"{content}/0{repo_url}/0{context}".encode("utf-8")
    ).hexdigest()

    db_record = get_mapping_by_cache_key(cache_key=cache_key)

    if db_record:
        logger.info(f"MAP CONTENT TO CODE: Mapping already exists for cache key {cache_key}, returning...")
        return {"status": "SUCCESS", "result": db_record.outputs}

    task = map_content_to_code_task.delay(
        content=content,
        repo_url=repo_url,
        context=context,
        cache_key=cache_key,
        paper_id=paper_id,
        box=parsed_box.model_dump(),
        page_number=page_number,
        user_id=user_id,
    )
    return {"task_id": task.id, "status": "PENDING"}

@app.post("/map_code_to_content")
def map_code_to_content(
    code: str = Form(...),
    paper_id: str = Form(...),
    start: int = Form(...),
    end: int = Form(...),
    filepath: str = Form(...),
    user_id: int = Form(...),
):
    cache_key = hashlib.sha256(
        f"{code}/0{paper_id}".encode("utf-8")
    ).hexdigest()

    db_record = get_mapping_by_cache_key(cache_key=cache_key)

    if db_record:
        logger.info(f"MAP CODE TO CONTENT: Mapping already exists for cache key {cache_key}, returning...")
        return {"status": "SUCCESS", "result": db_record.outputs}

    task = map_code_to_content_task.delay(
        code=code,
        paper_id=paper_id,
        cache_key=cache_key, 
        start=start,
        end=end,
        filepath=filepath,
        user_id=user_id,
    )
    return {"task_id": task.id}

##########################################
##### Repository Content #######################
##########################################

@app.get('/repos/tree')
def repo_tree(url: str) -> JSONResponse:
    tree = get_repo_tree(url)
    return JSONResponse(content=tree)

@app.get('/repos/file')
def repo_file(github_blob_url: str) -> PlainTextResponse:
    content = get_file_content(github_blob_url)
    return PlainTextResponse(content=content)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("src.server:app", host="0.0.0.0", port=port)
