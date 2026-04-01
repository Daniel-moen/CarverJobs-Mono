import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app import metrics
from app.database import SessionLocal, get_db
from app.logger import get_logger
from app.models import Document
from app.security import require_session
from app.settings import settings

log = get_logger("carver.documents")
_limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/documents", tags=["documents"])

VALID_DOC_TYPES = {"cv", "references", "passport", "stcw", "eng1", "photo"}
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}


def _upload_dir() -> Path:
    path = settings.UPLOAD_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_doc(db: Session, user_key: str, doc_type: str) -> Document | None:
    return (
        db.query(Document)
        .filter(Document.user_key == user_key, Document.doc_type == doc_type)
        .first()
    )


def _scan_document_background(doc_id: int, file_path: Path, doc_type: str) -> None:
    """Run AI document scan in a background task and persist the result."""
    from app.services.document_scanner import scan_document

    try:
        summary = scan_document(file_path, doc_type)
    except Exception:
        log.exception("Background document scan failed | doc_id=%d | doc_type=%s", doc_id, doc_type)
        return

    if not summary:
        return

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.scanned_text = summary
            db.commit()
            log.info("Document scanned | doc_id=%d | doc_type=%s | len=%d", doc_id, doc_type, len(summary))
    except Exception:
        log.exception("Failed to persist scan result | doc_id=%d", doc_id)
        db.rollback()
    finally:
        db.close()


@router.get("")
def list_documents(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    user_key = session["sub"]
    docs = db.query(Document).filter(Document.user_key == user_key).all()
    return {
        d.doc_type: {
            "original_name": d.original_name,
            "uploaded_at": d.created_at.isoformat(),
            "scanned": d.scanned_text is not None,
        }
        for d in docs
    }


@router.post("/{doc_type}", status_code=status.HTTP_200_OK)
@_limiter.limit("20/minute")
async def upload_document(
    request: Request,
    doc_type: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    if doc_type not in VALID_DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid doc_type. Must be one of: {', '.join(VALID_DOC_TYPES)}")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed. Accepted: {', '.join(ALLOWED_EXTENSIONS)}")

    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="MIME type not allowed.")

    contents = await file.read()
    if len(contents) > settings.UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.UPLOAD_MAX_BYTES // (1024*1024)} MB limit.")
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")

    user_key = session["sub"]
    upload_dir = _upload_dir()

    existing = _get_doc(db, user_key, doc_type)
    if existing:
        old_file = upload_dir / existing.stored_name
        old_file.unlink(missing_ok=True)
        existing.original_name = file.filename or "upload"
        existing.stored_name = f"{uuid.uuid4().hex}{suffix}"
        existing.scanned_text = None
        (upload_dir / existing.stored_name).write_bytes(contents)
        db.commit()
        db.refresh(existing)
        metrics.increment("doc_uploads")
        log.info("Document replaced | user=%s | doc_type=%s | size=%d", user_key, doc_type, len(contents))
        background_tasks.add_task(_scan_document_background, existing.id, upload_dir / existing.stored_name, doc_type)
        return {"ok": True, "original_name": existing.original_name}

    stored_name = f"{uuid.uuid4().hex}{suffix}"
    (upload_dir / stored_name).write_bytes(contents)
    doc = Document(
        user_key=user_key,
        doc_type=doc_type,
        original_name=file.filename or "upload",
        stored_name=stored_name,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    metrics.increment("doc_uploads")
    log.info("Document uploaded | user=%s | doc_type=%s | size=%d", user_key, doc_type, len(contents))
    background_tasks.add_task(_scan_document_background, doc.id, upload_dir / stored_name, doc_type)
    return {"ok": True, "original_name": doc.original_name}


@router.delete("/{doc_type}", status_code=status.HTTP_200_OK)
@_limiter.limit("20/minute")
def delete_document(
    request: Request,
    doc_type: str,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    if doc_type not in VALID_DOC_TYPES:
        raise HTTPException(status_code=400, detail="Invalid doc_type.")

    user_key = session["sub"]
    doc = _get_doc(db, user_key, doc_type)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    upload_dir = _upload_dir()
    (upload_dir / doc.stored_name).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
    metrics.increment("doc_deletes")
    log.info("Document deleted | user=%s | doc_type=%s", user_key, doc_type)
    return {"ok": True}


@router.get("/{doc_type}/file")
def download_document(
    doc_type: str,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    if doc_type not in VALID_DOC_TYPES:
        raise HTTPException(status_code=400, detail="Invalid doc_type.")

    user_key = session["sub"]
    doc = _get_doc(db, user_key, doc_type)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    upload_dir = _upload_dir()
    file_path = (upload_dir / doc.stored_name).resolve()
    if not str(file_path).startswith(str(upload_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path.")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on server.")

    metrics.increment("doc_downloads")
    log.info("Document downloaded | user=%s | doc_type=%s", user_key, doc_type)
    return FileResponse(
        path=str(file_path),
        filename=doc.original_name,
        media_type="application/octet-stream",
    )
