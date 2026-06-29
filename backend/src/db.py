"""
Supabase persistence for papers (PDF bytes + metadata).

Table ``papers`` (expected columns): id, created_at, paper_title, paper_content (bytea), github_link.
"""
import hashlib
import io
import logging

from src.types import PaperMappingRecord, PaperRecord, UserRecord
from supabase import Client, create_client

from src.config import SUPABASE_URL, SUPABASE_KEY
from src.utils import get_pdf_thumbnail

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

def get_user_by_username_db(username: str) -> UserRecord | None:
    if not is_configured():
        return None
    try:
        supabase = get_supabase_client()
        response = supabase.table("users").select("*").eq("username", username).execute()
        if not response.data or len(response.data) == 0:
            return None
        return UserRecord.model_validate(response.data[0])
    except Exception:
        logger.exception("Supabase get_user_by_username failed username=%s", username)
        return None

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
        response = supabase.storage.from_("papers").upload(
            file=paper_content,
            path=paper_id,
            file_options={
                "content-type": "application/pdf",
                "upsert": "true",
            },
        )

        thumbnail = get_pdf_thumbnail(file_content=paper_content)
        thumbnail_response = supabase.storage.from_("thumbnails").upload(
            file=thumbnail, 
            path=paper_id,
            file_options={
                "content-type": "image/jpeg",
                "upsert": "true",
            },
        )

        logger.info("Supabase uploaded paper and its thumbnail to storage paper_name=%s paper_id=%s", paper_name, paper_id)
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

def get_paper_thumbnail_from_storage(paper_id: str) -> bytes | None:
    if not is_configured():
        logger.warning("Supabase not configured (SUPABASE_URL/SUPABASE_KEY missing); skip get_paper_from_storage paper_id=%s", paper_id)
        return None
    try:
        supabase = get_supabase_client()
        return supabase.storage.from_("thumbnails").download(path=paper_id)
    except Exception as e:
        logger.exception("Supabase get_paper_thumbnail_from_storage failed paper_id=%s; error=%s", paper_id, e)
        return None

def get_file_url(paper_id: str, bucket_name="papers") -> str | None:
    if not is_configured():
        logger.warning("Supabase not configured (SUPABASE_URL/SUPABASE_KEY missing); skip get_file_url paper_id=%s", paper_id)
        return None
    try:
        supabase = get_supabase_client()
        response = supabase.storage.from_(bucket_name).get_public_url(path=paper_id)
        return response
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

def get_content_to_code_matches_by_paper_id(paper_id: str) -> list[PaperMappingRecord]:
    if not is_configured():
        return []
    try:
        supabase = get_supabase_client()
        response = supabase.table("mappings").select('*').eq('paper_id', paper_id).eq('mapping_type', 'content_to_code').execute()
        return [PaperMappingRecord.model_validate(row) for row in response.data]
    except Exception:
        logger.exception("Supabase get_content_to_code_matches failed paper_id=%s", paper_id)
        return []

def get_code_to_content_matches_by_paper_id_and_filepath(paper_id: str, current_path: str) -> list[PaperMappingRecord]:
    if not is_configured():
        return []
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("mappings")
            .select('*')
            .eq('paper_id', paper_id)
            .eq('mapping_type', 'code_to_content')
            .eq('inputs->>filepath', current_path)
            .execute()
        )
        return [PaperMappingRecord.model_validate(row) for row in response.data]
    except Exception:
        logger.exception("Supabase get_code_to_content_matches failed paper_id=%s current_path=%s", paper_id, current_path)

def create_user_db(username: str) -> UserRecord | None:
    if not is_configured():
        return None
    try:
        supabase = get_supabase_client()
        response = supabase.table("users").insert({"username": username}).execute()
        if not response.data or len(response.data) == 0:
            return None
        return UserRecord.model_validate(response.data[0])
    except Exception:
        logger.exception("Supabase create_user_db failed username=%s", username)
        return None

if __name__ == "__main__":
    filepath = "./papers/pretraining.pdf"
    with open(filepath, "rb") as f:
        paper_content = f.read()
    paper_id = "d6d8b95f1981e7d714921baec9ae080cf7dc14f3e1f249b80a7129ba5cf4076d"
    upload_paper_to_storage("Pretraining", paper_id, paper_content)

    paper_content = get_paper_from_storage(paper_id)
    if paper_content is not None:
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(paper_content))
        except Exception as e:
            print(e)
            print("No paper content found")


    thumbnail_content = get_paper_thumbnail_from_storage(paper_id)
    from PIL import Image
    try:
        thumbnail = Image.open(thumbnail_content)
        print(thumbnail.size)
    except Exception as e:
        print("error:", e)