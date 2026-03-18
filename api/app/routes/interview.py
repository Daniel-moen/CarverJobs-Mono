import json
import re
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app import flags, metrics, schemas
from app.error_codes import CRV_3001, CRV_3002, CRV_3003, CRV_3004, CRV_3005, CRV_3006
from app.logger import get_logger
from app.security import require_session
from app.settings import settings

log = get_logger("carver.interview")
router = APIRouter(prefix="/interview", tags=["interview"], dependencies=[Depends(require_session)])
_limiter = Limiter(key_func=get_remote_address)
_http_client = httpx.AsyncClient(timeout=25.0)


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^```", "", raw)
    raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            log.warning("Could not extract JSON from AI response | raw=%r", raw[:200])
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            log.warning("JSON parse failed after regex extract | raw=%r", raw[:200])
            return {}


def _build_messages(system_text: str, history: list, user_message: str, limit: int = 12, onboard: bool = False) -> list:
    """Build an OpenAI-style messages list from conversation history.

    Assistant messages are re-wrapped as JSON so the model sees a consistent
    JSON conversation matching the "Return strict JSON only" system instruction.
    """
    messages = [{"role": "system", "content": system_text}]
    for msg in history[-limit:]:
        if msg.role == "user":
            messages.append({"role": "user", "content": msg.content})
        else:
            if onboard:
                wrapped = json.dumps({"message": msg.content, "done": False, "updates": {}})
            else:
                wrapped = json.dumps({"message": msg.content, "updates": {}})
            messages.append({"role": "assistant", "content": wrapped})
    messages.append({"role": "user", "content": user_message or "Begin."})
    return messages


def _build_interview_system(payload: schemas.InterviewRequest) -> str:
    profile_text = json.dumps(payload.profile or {}, ensure_ascii=True)
    return f"""You are CARVER Interview AI. Ask one concise, practical interview question at a time.
Your goal: learn candidate preferences for superyacht jobs and suggest profile updates.

Current profile:
{profile_text}

Review the conversation history carefully. Do NOT repeat questions or topics already covered.

Return strict JSON only:
{{"message": "your next question or brief acknowledgment + question", "updates": {{"desiredRole": "", "preferredLocations": "", "contractType": "", "rotationPreference": "", "availableFrom": "", "salaryMin": "", "salaryMax": "", "languages": "", "certifications": "", "bio": ""}}}}

Rules:
- Only fill update fields if the user clearly provided that info.
- Keep values short and clean.
- Do not invent personal facts."""


REQUIRED_ONBOARD_FIELDS = [
    "firstName", "lastName", "desiredRole", "yearsExperience",
    "nationality", "currentLocation", "preferredLocations",
    "contractType", "salaryMin", "salaryMax", "certifications", "languages",
]


def _build_onboard_system(payload: schemas.InterviewRequest) -> str:
    profile = payload.profile or {}
    missing = [f for f in REQUIRED_ONBOARD_FIELDS if not str(profile.get(f, "")).strip()]
    all_done = len(missing) == 0
    profile_text = json.dumps(profile, ensure_ascii=True)
    missing_text = ", ".join(missing) if missing else "none — all fields collected!"

    return f"""You are CARVER, a warm and professional onboarding assistant for a superyacht crew platform.
Your sole job: collect every required profile field through natural conversation.

Profile collected so far:
{profile_text}

Still missing: {missing_text}

Review the conversation history carefully. Do NOT re-ask questions already answered.
Ask about fields in this order when missing:
  1. firstName + lastName (ask together: "What's your full name?")
  2. desiredRole (e.g. Chief Stew, Bosun, Engineer, Chef, Captain)
  3. yearsExperience (years in yachting or maritime)
  4. nationality
  5. currentLocation (city / country they're based in now)
  6. preferredLocations (regions or areas they want to work)
  7. contractType (Permanent, Seasonal, Rotational, or Temporary)
  8. salaryMin + salaryMax (ask together: monthly EUR expectations)
  9. certifications (STCW, ENG1, Yachtmaster, etc. — can say "none" if applicable)
  10. languages spoken

Rules:
- ONLY set "done": true when the missing fields list is empty (all 12 fields collected).
- Do NOT set "done": true if any field is still missing.
- One question at a time — keep replies short, warm and conversational.
- Only populate update fields when the user has clearly provided that info.
- Do not invent or assume any facts.
- Keep values short and clean (e.g. nationality: "British", contractType: "Seasonal").
- For salaryMin/salaryMax use numeric strings only (e.g. "4000", "6000").
- If the user wants to skip a field, set it to "unknown" so it counts as filled.

Return strict JSON only:
{{"message": "your conversational reply + next question (or warm wrap-up if done)", "done": {str(all_done).lower()}, "updates": {{"firstName": "", "lastName": "", "desiredRole": "", "yearsExperience": "", "nationality": "", "currentLocation": "", "preferredLocations": "", "contractType": "", "salaryMin": "", "salaryMax": "", "certifications": "", "languages": ""}}}}"""


@router.post("/next", response_model=schemas.InterviewResponse)
@_limiter.limit("20/minute")
async def interview_next(request: Request, payload: schemas.InterviewRequest):
    if not flags.is_enabled("interview"):
        metrics.increment("feature_blocked")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI interview is temporarily disabled.")
    if not settings.OPENAI_API_KEY:
        log.error("Interview requested but OPENAI_API_KEY is not set")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI interview is not available.",
            headers={"X-Error-Code": CRV_3001},
        )

    model = settings.OPENAI_MODEL
    log.info("OpenAI request | model=%s | history_len=%d", model, len(payload.history))

    system_text = _build_interview_system(payload)
    messages = _build_messages(system_text, payload.history, payload.user_message, limit=12)

    _ai_start = time.perf_counter()
    try:
        response = await _http_client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.4,
                "max_tokens": 450,
                "response_format": {"type": "json_object"},
            },
        )
    except httpx.TimeoutException:
        log.error("OpenAI request timed out | model=%s", model)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Request timed out. Please try again.",
            headers={"X-Error-Code": CRV_3002},
        )
    except httpx.HTTPError as exc:
        log.exception("OpenAI request failed (network) | %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Something went wrong. Please try again.",
            headers={"X-Error-Code": CRV_3005},
        ) from exc
    finally:
        metrics.record_ai_response_time(round((time.perf_counter() - _ai_start) * 1000))

    if response.status_code >= 400:
        log.error(
            "OpenAI rejected request | model=%s | status=%d | body=%s",
            model,
            response.status_code,
            response.text[:500],
        )
        if response.status_code == 429:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="AI quota exceeded. Please try again later.",
                headers={"X-Error-Code": CRV_3004},
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Something went wrong. Please try again.",
            headers={"X-Error-Code": CRV_3003},
        )

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        log.error("OpenAI returned no choices | model=%s | response=%s", model, str(data)[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Something went wrong. Please try again.",
            headers={"X-Error-Code": CRV_3006},
        )

    text = ((choices[0].get("message") or {}).get("content") or "").strip()
    log.info("OpenAI raw response | %s", text[:400])

    parsed = _extract_json(text)
    message = (parsed.get("message") or "").strip()
    updates = parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {}
    clean_updates = {
        str(key): str(value).strip()
        for key, value in updates.items()
        if isinstance(key, str) and value is not None and str(value).strip()
    }

    if not message:
        log.warning("OpenAI returned empty message, using fallback")
        message = "Thanks for that! What else can you tell me about your preferences?"

    metrics.increment("interview_turns")
    log.info("Interview turn OK | updates=%s", list(clean_updates.keys()))
    return schemas.InterviewResponse(message=message, updates=clean_updates)


class OnboardResponse(schemas.InterviewResponse):
    done: bool = False


@router.post("/onboard", response_model=OnboardResponse)
@_limiter.limit("20/minute")
async def interview_onboard(request: Request, payload: schemas.InterviewRequest):
    if not flags.is_enabled("onboarding"):
        metrics.increment("feature_blocked")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Onboarding is temporarily disabled.")
    if not settings.OPENAI_API_KEY:
        log.error("Onboard interview requested but OPENAI_API_KEY is not set")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI interview is not available.",
            headers={"X-Error-Code": CRV_3001},
        )

    if not payload.history:
        metrics.increment("onboard_started")

    model = settings.OPENAI_MODEL
    log.info("Onboard OpenAI request | model=%s | history_len=%d", model, len(payload.history))

    system_text = _build_onboard_system(payload)
    messages = _build_messages(system_text, payload.history, payload.user_message, limit=20, onboard=True)

    _ai_start = time.perf_counter()
    try:
        response = await _http_client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.6,
                "max_tokens": 500,
                "response_format": {"type": "json_object"},
            },
        )
    except httpx.TimeoutException:
        log.error("Onboard OpenAI request timed out | model=%s", model)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Request timed out. Please try again.",
            headers={"X-Error-Code": CRV_3002},
        )
    except httpx.HTTPError as exc:
        log.exception("Onboard OpenAI request failed (network) | %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Something went wrong. Please try again.",
            headers={"X-Error-Code": CRV_3005},
        ) from exc
    finally:
        metrics.record_ai_response_time(round((time.perf_counter() - _ai_start) * 1000))

    if response.status_code >= 400:
        log.error(
            "Onboard OpenAI rejected request | model=%s | status=%d | body=%s",
            model,
            response.status_code,
            response.text[:500],
        )
        if response.status_code == 429:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="AI quota exceeded. Please try again later.",
                headers={"X-Error-Code": CRV_3004},
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Something went wrong. Please try again.",
            headers={"X-Error-Code": CRV_3003},
        )

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        log.error("Onboard OpenAI returned no choices | model=%s | response=%s", model, str(data)[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Something went wrong. Please try again.",
            headers={"X-Error-Code": CRV_3006},
        )

    text = ((choices[0].get("message") or {}).get("content") or "").strip()
    log.info("Onboard raw response | %s", text[:400])

    parsed = _extract_json(text)
    message = (parsed.get("message") or "").strip()
    done = bool(parsed.get("done"))
    updates = parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {}
    clean_updates = {
        str(key): str(value).strip()
        for key, value in updates.items()
        if isinstance(key, str) and value is not None and str(value).strip()
    }

    if not message:
        profile = payload.profile or {}
        merged = {**profile, **clean_updates}
        missing = [f for f in REQUIRED_ONBOARD_FIELDS if not str(merged.get(f, "")).strip()]
        fallback_map = {
            "firstName": "Could you tell me your full name?",
            "lastName": "Could you tell me your last name?",
            "desiredRole": "What role are you looking for on a yacht?",
            "yearsExperience": "How many years of experience do you have?",
            "nationality": "What's your nationality?",
            "currentLocation": "Where are you currently based?",
            "preferredLocations": "Which regions would you prefer to work in?",
            "contractType": "Are you looking for permanent, seasonal, rotational, or temporary work?",
            "salaryMin": "What are your monthly salary expectations (EUR)?",
            "salaryMax": "What would be your ideal maximum monthly salary (EUR)?",
            "certifications": "Do you hold any certifications (STCW, ENG1, etc.)?",
            "languages": "What languages do you speak?",
        }
        if missing:
            message = f"Got it, thanks! {fallback_map.get(missing[0], 'Tell me a bit more about yourself.')}"
        else:
            message = "Looks like we have everything — welcome aboard!"
            done = True
        log.warning("OpenAI returned empty message, using fallback | next_missing=%s", missing[:3])

    if done:
        metrics.increment("onboard_completed")
    log.info("Onboard turn OK | done=%s | updates=%s", done, list(clean_updates.keys()))
    return OnboardResponse(message=message, updates=clean_updates, done=done)
