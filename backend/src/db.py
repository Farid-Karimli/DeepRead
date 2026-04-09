"""
Supabase persistence for papers (PDF bytes + metadata).

Table ``papers`` (expected columns): id, created_at, paper_title, paper_content (bytea), github_link.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from supabase import Client, create_client

from src.config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

class Paper(BaseModel):
    id: str
    paper_title: str
    github_link: str
    paper_content: bytes
    created_at: datetime


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def get_supabase_client() -> Client:
    if not is_configured():
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _bytea_hex_payload(raw: bytes) -> str:
    """PostgREST / Supabase JSON encoding for PostgreSQL bytea."""
    return "\\x" + raw.hex()

# Deprecated
def save_paper_upload_bytes(paper_id: str, paper_content: bytes) -> None:
    """
    Persist raw upload bytes. New rows get empty title/link until the worker finishes.

    If a row already exists (e.g. cache hit / re-upload), only ``paper_content`` is updated
    so metadata from a completed analysis is preserved.
    """
    if not is_configured():
        logger.warning("Supabase not configured (SUPABASE_URL/SUPABASE_KEY missing); skip save_paper_upload_bytes paper_id=%s", paper_id)
        return
    try:
        supabase = get_supabase_client()
        hex_payload = _bytea_hex_payload(paper_content)
        existing = (
            supabase.from_("papers").select("id").eq("id", paper_id).limit(1).execute().data
        )
        if existing:
            supabase.from_("papers").update({"paper_content": hex_payload}).eq(
                "id", paper_id
            ).execute()
            logger.info("Supabase updated paper_content paper_id=%s", paper_id)
        else:
            supabase.from_("papers").insert(
                {
                    "id": paper_id,
                    "paper_content": hex_payload,
                    "paper_title": "",
                    "github_link": "",
                }
            ).execute()
            logger.info("Supabase inserted paper paper_id=%s", paper_id)
    except Exception:
        logger.exception("Supabase save_paper_upload_bytes failed paper_id=%s", paper_id)


def update_paper_metadata(
    paper_id: str,
    paper_title: str | None,
    github_link: str | None,
) -> None:
    """Set title and repo link after the agent finishes (Redis cache is written separately)."""
    if not is_configured():
        logger.warning("Supabase not configured (SUPABASE_URL/SUPABASE_KEY missing); skip update_paper_metadata paper_id=%s", paper_id)
        return
    try:
        supabase = get_supabase_client()
        supabase.from_("papers").update(
            {
                "paper_title": (paper_title or "").strip(),
                "github_link": (github_link or "").strip(),
            }
        ).eq("id", paper_id).execute()
        logger.info("Supabase updated metadata paper_id=%s title=%r github_link=%r", paper_id, paper_title, github_link)
    except Exception:
        logger.exception("Supabase update_paper_metadata failed paper_id=%s", paper_id)


def get_paper_row(paper_id: str) -> dict[str, Any] | None:
    if not is_configured():
        return None
    try:
        supabase = get_supabase_client()
        rows = supabase.from_("papers").select("*").eq("id", paper_id).execute().data
        if not rows:
            return None
        return rows[0]
    except Exception:
        logger.exception("Supabase get_paper_row failed paper_id=%s", paper_id)
        return None

def upload_paper_to_storage(paper_name: str, paper_id: str, paper_content: bytes) -> None:
    if not is_configured():
        logger.warning("Supabase not configured (SUPABASE_URL/SUPABASE_KEY missing); skip upload_paper_to_storage paper_name=%s paper_id=%s", paper_name, paper_id)
        return
    try:
        supabase = get_supabase_client()
        supabase.storage.from_("papers").upload(
            file=paper_content,
            path=paper_id,
            file_options={
                "content-type": "application/pdf",
                "upsert": "true",
            },
        )
        logger.info("Supabase uploaded paper to storage paper_name=%s paper_id=%s", paper_name, paper_id)
    except Exception as e:
        logger.exception("Supabase upload_paper_to_storage failed paper_name=%s paper_id=%s", paper_name, paper_id)
        print(f"Supabase upload_paper_to_storage failed paper_name={paper_name} paper_id={paper_id}")
        print(e)

def get_paper_from_storage(paper_id: str) -> bytes | None:
    if not is_configured():
        logger.warning("Supabase not configured (SUPABASE_URL/SUPABASE_KEY missing); skip get_paper_from_storage paper_id=%s", paper_id)
        return None
    try:
        supabase = get_supabase_client()
        return supabase.storage.from_("papers").download(path=paper_id)
    except Exception:
        logger.exception("Supabase get_paper_from_storage failed paper_id=%s", paper_id)
        return None

def get_file_url(paper_id: str) -> str | None:
    if not is_configured():
        logger.warning("Supabase not configured (SUPABASE_URL/SUPABASE_KEY missing); skip get_file_url paper_id=%s", paper_id)
        return None
    try:
        supabase = get_supabase_client()
        return supabase.storage.from_("papers").get_public_url(path=paper_id)
    except Exception:
        logger.exception("Supabase get_file_url failed paper_id=%s", paper_id)



if __name__ == "__main__":
    filepath = "/Users/faridkarimli/Desktop/Programming/PhD/DeepRead/backend/papers/controlnext.pdf"
    with open(filepath, "rb") as f:
        paper_content = f.read()
    paper_id = hashlib.sha256(paper_content).hexdigest()
    upload_paper_to_storage("ControlNext", paper_id, paper_content)

    paper_content = get_paper_from_storage(paper_id)
    if paper_content is not None:
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(paper_content))
            print(reader.pages[0].extract_text())
        except Exception as e:
            print(e)
            print("No paper content found")