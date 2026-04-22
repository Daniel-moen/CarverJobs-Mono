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

import hmac
import html
import json
import re
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
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
# Aligned: JSON list and HTML index must return the same published-article set.
_MAX_PUBLIC_LIST = 500


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


def _normalise_article_slug(slug: str) -> str | None:
    s = slug.strip().lower()
    return s if _SLUG_PATTERN.match(s) else None


def _published_article_query(db: Session):
    """Published rows, newest first (shared ordering for list, SSR, sitemap)."""
    return (
        db.query(Article)
        .filter(Article.published.is_(True))
        .order_by(Article.date.desc(), Article.id.desc())
    )


def _get_published_article_or_none(db: Session, slug: str) -> Article | None:
    norm = _normalise_article_slug(slug)
    if norm is None:
        return None
    return (
        db.query(Article)
        .filter(Article.slug == norm, Article.published.is_(True))
        .first()
    )


def _article_keyword_set(row: Article) -> set[str]:
    try:
        return {
            k.lower()
            for k in json.loads(row.keywords_json or "[]")
            if isinstance(k, str)
        }
    except (ValueError, TypeError):
        return set()


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


def _json_ld_date_modified(article: dict) -> str:
    """Last-modified calendar date for JSON-LD and meta; prefers DB `updated_at` over editorial `date`."""
    updated = article.get("updated_at")
    if updated and isinstance(updated, str) and len(updated) >= 10 and updated[4] == "-" and updated[7] == "-":
        return updated[:10]
    return article.get("date") or ""


# ── SSR helpers ─────────────────────────────────────────────────────────────
#
# All author-controlled text is HTML-escaped before being inlined, and the
# JSON-LD payload has every "</" sequence escaped so it cannot break out of
# the <script> element. The SSR page loads no third-party JS and carries a
# strict Content-Security-Policy via nginx.

def _site_origin() -> str:
    base = (settings.FRONTEND_BASE_URL or "").strip().rstrip("/")
    if not base or base.startswith("http://localhost"):
        return "https://jobcarver.co"
    return base


def _esc(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _pick_related(current: Article, candidates: list[Article], k: int = 4) -> list[Article]:
    """Pick up to `k` related articles for internal linking.

    Scoring:
      1. Higher keyword overlap (Jaccard-style: shared keyword count).
      2. Tie-break on newer `date`, then newer `id`.
    Articles with zero overlap still appear (padded from most-recent) so
    every detail page has at least a couple of internal links, which is
    important for crawl depth and SEO.
    """
    current_kw = _article_keyword_set(current)

    scored: list[tuple[int, str, int, Article]] = []
    for row in candidates:
        if row.slug == current.slug:
            continue
        kw = _article_keyword_set(row)
        score = len(current_kw & kw)
        scored.append((score, row.date or "", row.id or 0, row))

    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [row for _, _, _, row in scored[:k]]


def _render_related_section(related: list[Article]) -> str:
    if not related:
        return ""
    items: list[str] = []
    for row in related:
        href = f"/articles/{row.slug}"
        items.append(
            f'<li><a href="{_esc(href)}">{_esc(row.title)}</a>'
            f'<span class="related-desc">{_esc(row.description)}</span></li>'
        )
    inner = "\n            ".join(items)
    return f"""
        <aside class="related" aria-label="Related articles">
          <h2>More reading</h2>
          <ul>
            {inner}
          </ul>
        </aside>"""


def _render_article_html(article: dict, related: list[Article] | None = None) -> str:
    """Return a fully server-rendered HTML page for a single article.

    The page is self-contained (no third-party scripts, no SPA hydration)
    so crawlers and social previewers receive the article body and meta
    tags in the initial response.
    """
    origin = _site_origin()
    slug = article["slug"]
    canonical = f"{origin}/articles/{slug}"
    full_title_plain = f"{article['title']} — Carver"
    title_html = _esc(full_title_plain)
    description_html = _esc(article["description"])
    headline_html = _esc(article["title"])
    date_html = _esc(article["date"])
    date_modified_plain = _json_ld_date_modified(article)
    date_modified_html = _esc(date_modified_plain) if date_modified_plain else date_html
    try:
        read_minutes = int(article.get("read_minutes") or 3)
    except (TypeError, ValueError):
        read_minutes = 3
    keywords_raw = [k for k in (article.get("keywords") or []) if isinstance(k, str)]
    keywords_html = _esc(", ".join(keywords_raw))

    body_parts: list[str] = []
    for block in article.get("body") or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "h2" and block.get("text"):
            body_parts.append(f"<h2>{_esc(block['text'])}</h2>")
        elif btype == "p" and block.get("text"):
            body_parts.append(f"<p>{_esc(block['text'])}</p>")
        elif btype == "ul" and isinstance(block.get("items"), list):
            items = "".join(
                f"<li>{_esc(item)}</li>" for item in block["items"] if isinstance(item, str)
            )
            if items:
                body_parts.append(f"<ul>{items}</ul>")
    body_html = "\n          ".join(body_parts)
    related_html = _render_related_section(related or [])

    json_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article["title"],
        "description": article["description"],
        "datePublished": article["date"],
        "dateModified": date_modified_plain or article["date"],
        "author": {"@type": "Organization", "name": "Carver"},
        "publisher": {"@type": "Organization", "name": "Carver"},
        "mainEntityOfPage": canonical,
        "keywords": ", ".join(keywords_raw),
    }
    # Prevent </script> breakout inside the JSON-LD block.
    json_ld_safe = json.dumps(json_ld, ensure_ascii=True).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <title>{title_html}</title>
    <meta name="description" content="{description_html}" />
    <meta name="keywords" content="{keywords_html}" />
    <meta name="author" content="Carver" />
    <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />
    <meta name="theme-color" content="#05080c" />
    <meta name="color-scheme" content="dark" />
    <link rel="canonical" href="{_esc(canonical)}" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <meta property="og:type" content="article" />
    <meta property="og:site_name" content="Carver" />
    <meta property="og:title" content="{title_html}" />
    <meta property="og:description" content="{description_html}" />
    <meta property="og:url" content="{_esc(canonical)}" />
    <meta property="og:image" content="{_esc(origin)}/og-image.svg" />
    <meta property="og:locale" content="en_GB" />
    <meta property="article:published_time" content="{date_html}" />
    <meta property="article:modified_time" content="{date_modified_html}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{title_html}" />
    <meta name="twitter:description" content="{description_html}" />
    <meta name="twitter:image" content="{_esc(origin)}/og-image.svg" />
    <script type="application/ld+json">{json_ld_safe}</script>
    <style>
      :root {{ --bg:#05080c; --text:#e8e6e1; --muted:#8a8378; --brass:#d4b97a; --border:rgba(255,255,255,0.06); }}
      *,*::before,*::after {{ box-sizing: border-box; }}
      html,body {{ margin:0; padding:0; background:var(--bg); color:var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; -webkit-font-smoothing: antialiased; }}
      a {{ color: var(--brass); }}
      .nav {{ max-width:1280px; margin:0 auto; padding:1rem 1.5rem; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); }}
      .brand {{ text-decoration:none; color:var(--text); font-weight:600; letter-spacing:0.04em; font-size: 0.9rem; }}
      .nav-links a {{ margin-left:1rem; color:var(--muted); text-decoration:none; font-size:0.85rem; }}
      .nav-links a:hover {{ color: var(--text); }}
      main {{ max-width:720px; margin:0 auto; padding:3rem 1.5rem 5rem; }}
      .crumbs {{ font-size:0.72rem; letter-spacing:0.14em; text-transform:uppercase; color:var(--muted); margin:0 0 1.5rem; }}
      .crumbs a {{ color:inherit; text-decoration:none; border-bottom:1px dashed rgba(255,255,255,0.18); }}
      h1 {{ font-family: Georgia, "Times New Roman", serif; font-weight:300; font-size:clamp(1.9rem, 4.5vw, 2.75rem); line-height:1.08; letter-spacing:-0.02em; margin:0; color:var(--text); }}
      .lede {{ color:var(--muted); font-size:1.05rem; line-height:1.6; margin:1.25rem 0 0; }}
      .body {{ margin-top:2.25rem; line-height:1.7; }}
      .body h2 {{ font-family: Georgia, "Times New Roman", serif; font-weight:400; font-size:1.3rem; margin:2.25rem 0 0.75rem; color:var(--text); }}
      .body p {{ margin:0 0 1.1rem; color:var(--muted); }}
      .body ul {{ padding-left:1.2rem; color:var(--muted); margin:0 0 1.25rem; }}
      .body li {{ margin: 0.35rem 0; }}
      .related {{ margin-top:3rem; padding-top:1.5rem; border-top:1px solid var(--border); }}
      .related h2 {{ font-family: Georgia, "Times New Roman", serif; font-weight:400; font-size:1.15rem; margin:0 0 1rem; color:var(--text); letter-spacing:0.01em; }}
      .related ul {{ list-style:none; padding:0; margin:0; display:grid; gap:0.75rem; }}
      .related li {{ border:1px solid var(--border); border-radius:10px; padding:0.9rem 1rem; }}
      .related a {{ display:block; color:var(--text); text-decoration:none; font-weight:500; font-size:0.98rem; }}
      .related a:hover {{ color: var(--brass); }}
      .related-desc {{ display:block; margin-top:0.3rem; color:var(--muted); font-size:0.85rem; line-height:1.5; font-weight:normal; }}
      .foot {{ margin-top:2rem; padding-top:1.5rem; border-top:1px solid var(--border); }}
      .back {{ color:var(--muted); font-size:0.85rem; text-decoration:none; border-bottom:1px dashed rgba(255,255,255,0.18); }}
      .back:hover {{ color: var(--text); }}
    </style>
  </head>
  <body>
    <nav class="nav" aria-label="Primary">
      <a class="brand" href="/">CARVER</a>
      <div class="nav-links">
        <a href="/">Home</a>
        <a href="/articles">Articles</a>
      </div>
    </nav>
    <main>
      <article itemscope itemtype="https://schema.org/Article">
        <p class="crumbs">
          <a href="/articles">Articles</a> &middot;
          <time datetime="{date_html}" itemprop="datePublished">{date_html}</time> &middot;
          <span>{read_minutes} min read</span>
        </p>
        <h1 itemprop="headline">{headline_html}</h1>
        <p class="lede" itemprop="description">{description_html}</p>
        <div class="body" itemprop="articleBody">
          {body_html}
        </div>{related_html}
        <footer class="foot">
          <a class="back" href="/articles">&larr; All articles</a>
        </footer>
      </article>
    </main>
  </body>
</html>
"""


def _render_articles_list_html(rows: list[Article]) -> str:
    """Return a fully server-rendered HTML index of published articles.

    Every link appears in the initial HTML (no JS required), so crawlers
    and "View Page Source" both see the full article list and can reach
    each detail page at minimum crawl depth.
    """
    origin = _site_origin()
    canonical = f"{origin}/articles"
    title_html = _esc("Articles — Carver")
    description_html = _esc(
        "Guides and stories for superyacht crew — CV tips, season timelines, "
        "and how Carver matches you to live roles over WhatsApp."
    )

    if rows:
        cards: list[str] = []
        for row in rows:
            href = _esc(f"/articles/{row.slug}")
            title = _esc(row.title)
            desc = _esc(row.description)
            date = _esc(row.date or "")
            try:
                read_minutes = int(row.read_minutes or 3)
            except (TypeError, ValueError):
                read_minutes = 3
            cards.append(
                f'<li class="card">'
                f'<a href="{href}">'
                f'<p class="meta"><time datetime="{date}">{date}</time>'
                f' &middot; <span>{read_minutes} min read</span></p>'
                f'<h2>{title}</h2>'
                f'<p class="desc">{desc}</p>'
                f'<span class="cta">Read article &rarr;</span>'
                f'</a></li>'
            )
        list_html = "\n        ".join(cards)
        body_block = f'<ul class="list" aria-label="Articles">\n        {list_html}\n      </ul>'
    else:
        body_block = (
            '<p class="empty">No articles have been published yet. '
            'Please check back soon.</p>'
        )

    json_ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Carver journal",
        "description": "Articles for superyacht crew.",
        "url": canonical,
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "url": f"{origin}/articles/{row.slug}",
                    "name": row.title,
                }
                for i, row in enumerate(rows)
            ],
        },
    }
    json_ld_safe = json.dumps(json_ld, ensure_ascii=True).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <title>{title_html}</title>
    <meta name="description" content="{description_html}" />
    <meta name="author" content="Carver" />
    <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />
    <meta name="theme-color" content="#05080c" />
    <meta name="color-scheme" content="dark" />
    <link rel="canonical" href="{_esc(canonical)}" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Carver" />
    <meta property="og:title" content="{title_html}" />
    <meta property="og:description" content="{description_html}" />
    <meta property="og:url" content="{_esc(canonical)}" />
    <meta property="og:image" content="{_esc(origin)}/og-image.svg" />
    <meta property="og:locale" content="en_GB" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{title_html}" />
    <meta name="twitter:description" content="{description_html}" />
    <meta name="twitter:image" content="{_esc(origin)}/og-image.svg" />
    <script type="application/ld+json">{json_ld_safe}</script>
    <style>
      :root {{ --bg:#05080c; --text:#e8e6e1; --muted:#8a8378; --brass:#d4b97a; --border:rgba(255,255,255,0.06); }}
      *,*::before,*::after {{ box-sizing: border-box; }}
      html,body {{ margin:0; padding:0; background:var(--bg); color:var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; -webkit-font-smoothing: antialiased; }}
      a {{ color: var(--brass); }}
      .nav {{ max-width:1280px; margin:0 auto; padding:1rem 1.5rem; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); }}
      .brand {{ text-decoration:none; color:var(--text); font-weight:600; letter-spacing:0.04em; font-size: 0.9rem; }}
      .nav-links a {{ margin-left:1rem; color:var(--muted); text-decoration:none; font-size:0.85rem; }}
      .nav-links a:hover {{ color: var(--text); }}
      main {{ max-width:760px; margin:0 auto; padding:3rem 1.5rem 5rem; }}
      .eyebrow {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.72rem; letter-spacing:0.14em; text-transform:uppercase; color:var(--brass); margin:0; }}
      h1 {{ margin:0.75rem 0 0; font-family: Georgia, "Times New Roman", serif; font-weight:300; font-size:clamp(2rem, 4vw, 2.75rem); line-height:1.05; letter-spacing:-0.025em; color:var(--text); }}
      .lede {{ margin:1.25rem 0 0; color:var(--muted); font-size:1rem; line-height:1.6; max-width:36rem; }}
      .list {{ list-style:none; margin:2.5rem 0 0; padding:0; display:grid; gap:1rem; }}
      .card {{ border:1px solid var(--border); border-radius:14px; transition: border-color 0.2s ease, background 0.2s ease; }}
      .card:hover {{ border-color: rgba(212,185,122,0.35); background: rgba(212,185,122,0.04); }}
      .card a {{ display:block; padding:1.25rem 1.4rem 1.4rem; text-decoration:none; color:inherit; }}
      .meta {{ margin:0 0 0.4rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:11px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted); }}
      .card h2 {{ margin:0; font-family: Georgia, "Times New Roman", serif; font-weight:400; font-size:1.35rem; line-height:1.25; letter-spacing:-0.015em; color:var(--text); }}
      .card .desc {{ margin:0.6rem 0 0.9rem; color:var(--muted); font-size:0.95rem; line-height:1.55; }}
      .cta {{ font-size:12.5px; color: var(--brass); letter-spacing:0.02em; }}
      .empty {{ color: var(--muted); font-size:1rem; }}
    </style>
  </head>
  <body>
    <nav class="nav" aria-label="Primary">
      <a class="brand" href="/">CARVER</a>
      <div class="nav-links">
        <a href="/">Home</a>
        <a href="/articles">Articles</a>
      </div>
    </nav>
    <main>
      <p class="eyebrow">Carver journal</p>
      <h1>Articles for superyacht crew</h1>
      <p class="lede">Short guides on landing berths, staying match-ready between seasons, and how Carver's WhatsApp bot actually works.</p>
      {body_block}
    </main>
  </body>
</html>
"""


def _render_articles_sitemap(rows: list[Article]) -> str:
    origin = _site_origin()
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for row in rows:
        loc = f"{origin}/articles/{row.slug}"
        lastmod = row.date or ""
        try:
            if row.updated_at is not None:
                lastmod = row.updated_at.date().isoformat()
        except AttributeError:
            pass
        parts.append("  <url>")
        parts.append(f"    <loc>{html.escape(loc)}</loc>")
        if lastmod:
            parts.append(f"    <lastmod>{html.escape(lastmod)}</lastmod>")
        parts.append("    <changefreq>monthly</changefreq>")
        parts.append("    <priority>0.7</priority>")
        parts.append("  </url>")
    parts.append("</urlset>")
    parts.append("")
    return "\n".join(parts)


# ── Public endpoints ────────────────────────────────────────────────────────
#
# Route registration order matters: `/sitemap.xml` and `/{slug}/page.html`
# must be registered before the generic `/{slug}` route so Starlette picks
# the more specific match first.

@public_router.get("")
@_limiter.limit("60/minute")
def list_articles(request: Request, db: Session = Depends(get_db)):
    rows = (
        db.query(Article)
        .filter(Article.published.is_(True))
        .order_by(Article.date.desc(), Article.id.desc())
        .limit(_MAX_PUBLIC_LIST)
        .all()
    )
    return {"ok": True, "articles": [_serialise(r) for r in rows]}


@public_router.get("/list.html", include_in_schema=False)
@_limiter.limit("60/minute")
def articles_list_page(request: Request, db: Session = Depends(get_db)):
    """SSR HTML index of published articles. Proxied from `/articles` by nginx."""
    rows = (
        db.query(Article)
        .filter(Article.published.is_(True))
        .order_by(Article.date.desc(), Article.id.desc())
        .limit(_MAX_PUBLIC_LIST)
        .all()
    )
    body = _render_articles_list_html(rows)
    return HTMLResponse(content=body)


@public_router.get("/sitemap.xml", include_in_schema=False)
@_limiter.limit("60/minute")
def articles_sitemap(request: Request, db: Session = Depends(get_db)):
    rows = _published_article_query(db).limit(2000).all()
    xml = _render_articles_sitemap(rows)
    return Response(content=xml, media_type="application/xml")


@public_router.get("/{slug}/page.html", include_in_schema=False)
@_limiter.limit("60/minute")
def article_page(slug: str, request: Request, db: Session = Depends(get_db)):
    row = _get_published_article_or_none(db, slug)
    if not row:
        raise HTTPException(status_code=404, detail="Article not found.")

    # Fetch a recent pool (excluding the current article) and pick related
    # entries in Python — cheap at this volume and avoids coupling ranking
    # to the storage layer.
    pool = (
        _published_article_query(db)
        .filter(Article.slug != row.slug)
        .limit(100)
        .all()
    )
    related = _pick_related(row, pool, k=4)

    body = _render_article_html(_serialise(row), related=related)
    return HTMLResponse(content=body)


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
    request: Request,
    payload: ArticleIn = Body(...),
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
