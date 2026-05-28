"""
Supabase persistence for papers (PDF bytes + metadata).

Table ``papers`` (expected columns): id, created_at, paper_title, paper_content (bytea), github_link.
"""
import hashlib
import io
import logging

from src.types import PaperMappingRecord, PaperRecord
from supabase import Client, create_client

from src.config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

def is_configured() -> bool:
    configured = bool(SUPABASE_URL and SUPABASE_KEY)
    if not configured:
        logger.warning("Supabase not configured (SUPABASE_URL/SUPABASE_KEY missing); skip is_configured")
    return configured

def get_supabase_client() -> Client:
    if not is_configured():
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def upsert_paper(
    paper_record: PaperRecord,
) -> None:
    if not is_configured():
        return
    try:
        supabase = get_supabase_client()
        supabase.table("papers").upsert(paper_record.model_dump(mode="json")).execute()
    except Exception:
        logger.exception("Supabase upsert_paper failed paper_record=%s", paper_record)

def get_paper_record_by_id(paper_id: str) -> PaperRecord | None:
    if not is_configured():
        return None
    try:
        supabase = get_supabase_client()
        rows = supabase.from_("papers").select("*").eq("id", paper_id).execute().data
        if not rows:
            return None
        return PaperRecord.model_validate(rows[0])
    except Exception:
        logger.exception("Supabase get_paper_record_by_id failed paper_id=%s", paper_id)
        return None

def get_all_paper_records() -> list[PaperRecord]:
    if not is_configured():
        return []
    try:
        supabase = get_supabase_client()
        response = supabase.table("papers").select("*").execute()
        rows = response.data
        if not rows:
            return []
        return [PaperRecord.model_validate(row) for row in rows]
    except Exception:
        logger.exception("Supabase get_all_paper_records failed")
        return []

def upload_paper_to_storage(
    paper_name: str, 
    paper_id: str, 
    paper_content: bytes,
    ) -> None:
    if not is_configured():
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

def get_mapping_by_cache_key(cache_key: str) -> PaperMappingRecord | None:
    if not is_configured():
        return None
    try:
        supabase = get_supabase_client()
        response = supabase.table("mappings").select('*').eq('cache_key', cache_key).execute()
        if response.data and len(response.data) > 0:
            return PaperMappingRecord.model_validate(response.data[0])
        return None
    except Exception:
        logger.exception("Supabase get_mapping_by_cache_key failed cache_key=%s", cache_key)
        return None

def upsert_mapping_result(
    mapping_record: PaperMappingRecord
) -> bool:
    """
    Upsert a mapping result into the database.
    """
    if not is_configured():
        return False
    
    try:
        supabase = get_supabase_client()
        supabase.table("mappings").upsert(
            mapping_record.model_dump(mode="json"),
            on_conflict="cache_key,paper_id,mapping_type"
        ).execute()
        return True
    except Exception:
        logger.exception("Supabase upsert_mapping_result failed mapping_record=%s", mapping_record)
        return False

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