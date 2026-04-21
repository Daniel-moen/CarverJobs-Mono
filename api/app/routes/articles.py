"""
Articles API — SEO blog content.

Public (no auth):
  GET  /articles              — list published articles (newest first).
  GET  /articles/{slug}       — single published article.

Agent-authenticated (bearer token AGENT_API_TOKEN):
  POST   /agent/articles          — create or upsert (by slug).
  DELETE /agent/articles/{slug}   — delete permanently.

The body is stored as a validated JSON list of structured blocks
(`p`, `h2`, `ul`). The frontend renders them as escaped text, never
as raw HTML, so content pushed here cannot inject script into visitors.
"""

from __future__ import annotations

import hmac
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_codes import CRV_2004, CRV_5005
from app.logger import get_logger
from app.models import Article
from app.settings import settings

log = get_logger("carver.articles")
_limiter = Limiter(key_func=get_remote_address)

public_router = APIRouter(prefix="/articles", tags=["articles"])
agent_router = APIRouter(prefix="/agent/articles", tags=["articles"])


# ── Limits & validation ─────────────────────────────────────────────────────

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_BLOCK_TYPES = {"p", "h2", "ul"}

_MAX_TITLE = 200
_MAX_DESCRIPTION = 400
_MAX_BLOCK_TEXT = 4000
_MAX_LIST_ITEM = 500
_MAX_LIST_ITEMS = 20
_MAX_BLOCKS = 200
_MAX_KEYWORDS = 20
_MAX_KEYWORD_LEN = 80


class Block(BaseModel):
    """One block of article body. Matches the frontend renderer exactly."""

    type: Literal["p", "h2", "ul"]
    text: str | None = None
    items: list[str] | None = None

    @field_validator("text")
    @classmethod
    def _text_len(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > _MAX_BLOCK_TEXT:
            raise ValueError(f"block text too long (max {_MAX_BLOCK_TEXT} chars)")
        return v

    @field_validator("items")
    @classmethod
    def _items_valid(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > _MAX_LIST_ITEMS:
            raise ValueError(f"too many list items (max {_MAX_LIST_ITEMS})")
        cleaned: list[str] = []
        for item in v:
            if not isinstance(item, str):
                raise ValueError("list items must be strings")
            s = item.strip()
            if not s:
                raise ValueError("list items must not be empty")
            if len(s) > _MAX_LIST_ITEM:
                raise ValueError(f"list item too long (max {_MAX_LIST_ITEM} chars)")
            cleaned.append(s)
        return cleaned


class ArticleIn(BaseModel):
    slug: str
    title: str
    description: str
    date: str
    read_minutes: int = Field(ge=1, le=60, default=3)
    keywords: list[str] = Field(default_factory=list)
    body: list[Block]
    published: bool = True

    @field_validator("slug")
    @classmethod
    def _slug_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_PATTERN.match(v) or len(v) > 120:
            raise ValueError(
                "slug must be lowercase letters, digits and single hyphens (max 120 chars)"
            )
        return v

    @field_validator("title")
    @classmethod
    def _title_ok(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        if len(v) > _MAX_TITLE:
            raise ValueError(f"title too long (max {_MAX_TITLE} chars)")
        return v

    @field_validator("description")
    @classmethod
    def _description_ok(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("description must not be empty")
        if len(v) > _MAX_DESCRIPTION:
            raise ValueError(f"description too long (max {_MAX_DESCRIPTION} chars)")
        return v

    @field_validator("date")
    @classmethod
    def _date_ok(cls, v: str) -> str:
        v = v.strip()
        if not _ISO_DATE_PATTERN.match(v):
            raise ValueError("date must be an ISO date (YYYY-MM-DD)")
        return v

    @field_validator("keywords")
    @classmethod
    def _keywords_ok(cls, v: list[str]) -> list[str]:
        if len(v) > _MAX_KEYWORDS:
            raise ValueError(f"too many keywords (max {_MAX_KEYWORDS})")
        cleaned: list[str] = []
        for k in v:
            if not isinstance(k, str):
                raise ValueError("keywords must be strings")
            s = k.strip()
            if not s:
                continue
            if len(s) > _MAX_KEYWORD_LEN:
                raise ValueError(f"keyword too long (max {_MAX_KEYWORD_LEN} chars)")
            cleaned.append(s)
        return cleaned

    @field_validator("body")
    @classmethod
    def _body_ok(cls, v: list[Block]) -> list[Block]:
        if not v:
            raise ValueError("body must contain at least one block")
        if len(v) > _MAX_BLOCKS:
            raise ValueError(f"too many blocks (max {_MAX_BLOCKS})")
        for block in v:
            if block.type in ("p", "h2"):
                if not block.text:
                    raise ValueError(f"{block.type} block requires 'text'")
            elif block.type == "ul":
                if not block.items:
                    raise ValueError("ul block requires non-empty 'items'")
        return v


# ── Auth helper ─────────────────────────────────────────────────────────────

def _require_agent_token(request: Request) -> None:
    """Validate the bearer token against AGENT_API_TOKEN (timing-safe)."""
    if not settings.AGENT_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent API is not configured (set AGENT_API_TOKEN).",
            headers={"X-Error-Code": CRV_5005},
        )

    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""

    if not token or not hmac.compare_digest(token, settings.AGENT_API_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing agent token.",
            headers={"X-Error-Code": CRV_2004},
        )


# ── Serialisation ───────────────────────────────────────────────────────────

def _serialise(row: Article) -> dict:
    try:
        keywords = json.loads(row.keywords_json or "[]")
    except (ValueError, TypeError):
        keywords = []
    try:
        body = json.loads(row.body_json or "[]")
    except (ValueError, TypeError):
        body = []
    return {
        "slug": row.slug,
        "title": row.title,
        "description": row.description,
        "date": row.date,
        "read_minutes": row.read_minutes,
        "keywords": keywords,
        "body": body,
        "published": bool(row.published),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ── Public endpoints ────────────────────────────────────────────────────────

@public_router.get("")
@_limiter.limit("60/minute")
def list_articles(request: Request, db: Session = Depends(get_db)):
    rows = (
        db.query(Article)
        .filter(Article.published.is_(True))
        .order_by(Article.date.desc(), Article.id.desc())
        .limit(200)
        .all()
    )
    return {"ok": True, "articles": [_serialise(r) for r in rows]}


@public_router.get("/{slug}")
@_limiter.limit("60/minute")
def get_article(slug: str, request: Request, db: Session = Depends(get_db)):
    slug = slug.strip().lower()
    if not _SLUG_PATTERN.match(slug):
        raise HTTPException(status_code=404, detail="Article not found.")
    row = (
        db.query(Article)
        .filter(Article.slug == slug, Article.published.is_(True))
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Article not found.")
    return {"ok": True, "article": _serialise(row)}


# ── Agent endpoints ─────────────────────────────────────────────────────────

@agent_router.post("", dependencies=[Depends(_require_agent_token)])
@_limiter.limit("30/minute")
def upsert_article(
    payload: ArticleIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create or update an article, keyed by slug."""
    body_json = json.dumps([b.model_dump(exclude_none=True) for b in payload.body])
    keywords_json = json.dumps(payload.keywords)

    row = db.query(Article).filter(Article.slug == payload.slug).first()
    created = row is None
    if row is None:
        row = Article(slug=payload.slug)
        db.add(row)

    row.title = payload.title
    row.description = payload.description
    row.date = payload.date
    row.read_minutes = payload.read_minutes
    row.keywords_json = keywords_json
    row.body_json = body_json
    row.published = payload.published

    db.commit()
    db.refresh(row)
    log.info(
        "Article %s | slug=%s | published=%s",
        "created" if created else "updated",
        row.slug,
        row.published,
    )
    return {
        "ok": True,
        "created": created,
        "article": _serialise(row),
    }


@agent_router.delete("/{slug}", dependencies=[Depends(_require_agent_token)])
@_limiter.limit("30/minute")
def delete_article(slug: str, request: Request, db: Session = Depends(get_db)):
    slug = slug.strip().lower()
    if not _SLUG_PATTERN.match(slug):
        raise HTTPException(status_code=404, detail="Article not found.")
    row = db.query(Article).filter(Article.slug == slug).first()
    if not row:
        raise HTTPException(status_code=404, detail="Article not found.")
    db.delete(row)
    db.commit()
    log.info("Article deleted | slug=%s", slug)
    return {"ok": True, "deleted": slug}
