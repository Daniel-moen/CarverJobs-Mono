"""
AI job reviewer — uses ChatGPT to determine whether a raw post is a genuine
yacht crew job posting and, if so, extract structured fields that map directly
to the Job model.

All OpenAI calls are delegated to app.services.ai_client so that timeout,
retry, and error-logging config lives in one place.
"""
import json

from app.logger import get_logger
from app.services.ai_client import AIClientError, call_openai

log = get_logger("carver.ai_reviewer")

_SYSTEM_PROMPT = """You are a strict yacht industry job listing analyst. You receive text from a Facebook post in a yacht crew jobs group.

Your job:
1. Decide if this post is a GENUINE, SPECIFIC hiring post for ONE clearly defined crew position on a real yacht.
2. If it IS a legitimate job, extract every available detail into the JSON schema below.

You must be STRICT. Only high-quality, specific job postings should pass. When in doubt, reject.

Return ONLY a JSON object. No markdown, no explanation, nothing else.

REJECT (return {"is_job": false}) for ALL of these:
- Crew SEEKING work (e.g. "Seeking a deckhand position", "Looking for work", "Available immediately", "I am an experienced chef looking to join a crew", "Please consider me", "Looking to contribute my skills")
- Written in first person where the author is describing THEMSELVES and their availability
- Posts that say "seeking", "looking for a position", "available for hire", "open to opportunities", "hoping to find work"
- Questions, general discussions, tips, news, equipment/service sales, visa advice
- Training course advertisements or school promotions
- Introductions where someone is presenting their CV/resume publicly
- MULTI-ROLE RECRUITMENT BLASTS: posts listing 3 or more different roles (e.g. "Chef, Stewardess, Deckhand, Engineer") — these are agency spam building candidate databases, NOT real specific job offers
- VAGUE AGENCY NETWORKING: agency posts that say they are "expanding their network", "building a crew pool", or "seeking crew for multiple vessels" without naming a specific vessel or offering a specific single position
- Posts with NO concrete details — a real job must include at minimum: a specific single role, AND at least TWO of these: vessel name/length, specific start date, salary range, specific port/location, or direct contact info (email/phone)
- Generic recruitment ads that could apply to any yacht, any season, any role — these are marketing, not job offers
- Posts where requirements are extremely vague (e.g. only "experience preferred" and "team-oriented attitude") with no mention of specific certifications, years of experience, or technical skills
- Posts that list a size RANGE of yachts (e.g. "30–50m yachts", "40–60m vessels") instead of a specific vessel — real jobs are for a specific yacht, not a category

ACCEPT (return is_job: true) ONLY when ALL of these are true:
- A yacht, captain, management company, or crewing agency is OFFERING a SINGLE specific open position
- The post clearly states ONE role that needs to be FILLED, e.g. "We are looking for a chef", "Deckhand needed", "Hiring a stewardess"
- There is a clear employer/vessel side making the offer
- The post contains enough specific detail to be actionable (not just a vague call for resumes)
- The post refers to a specific yacht or a specific program — not a generic "various opportunities"

If NOT a hiring post:
{"is_job": false}

If it IS a hiring post:
{
  "is_job": true,
  "title": "concise job title, max 100 chars, e.g. 'Experienced Seasonal Stewardess – 50m Motor Yacht'",
  "role": "specific crew role, e.g. Stewardess, Chief Engineer, Captain, Chef, Bosun",
  "yacht": "vessel name if mentioned, else 'Private Yacht' or 'Charter Yacht'",
  "yacht_type": "Motor Yacht | Sailing Yacht | Superyacht | Catamaran | Expedition Yacht | null",
  "yacht_length_m": 50,
  "vessel_flag": "flag state e.g. Malta, Cayman Islands, or null",
  "vessel_itinerary": "e.g. Mediterranean Summer 2026 or null",
  "department": "Interior | Deck | Engineering | Galley | Management | null",
  "rank_level": "Senior | Junior | Entry Level | null",
  "location": "base port or region e.g. Mediterranean, Fort Lauderdale, Palma de Mallorca",
  "start_date": "e.g. ASAP, April 2026, April–October 2026, or null",
  "contract_type": "Seasonal | Permanent | Rotational | Temporary | null",
  "rotation": "rotation pattern e.g. 2:1, 28/28 days, or null",
  "season": "e.g. Mediterranean Summer 2026, Winter Caribbean or null",
  "salary_currency": "EUR | USD | GBP | null",
  "salary_min": null,
  "salary_max": null,
  "experience_required_years": null,
  "minimum_license": "e.g. STCW, OOW 500gt, MCA Deck Officer 3000gt, or null",
  "certifications_required": "comma-separated list of required certificates or null",
  "languages_required": "e.g. English required, Italian preferred or null",
  "description": "Clean 2–3 sentence professional summary of the position",
  "responsibilities": "Key responsibilities as a concise paragraph, or null",
  "requirements": "Key requirements as a concise paragraph, or null",
  "benefits": "Any benefits mentioned (accommodation, travel, etc.) or null",
  "contact_email": "email address extracted verbatim or null",
  "recruiter_name": "contact/recruiter name or null",
  "recruiter_agency": "agency or company name or null",
  "urgent_hire": false,
  "visa_support": false,
  "accommodation": "Onboard | Shoreside | null",
  "travel_reimbursement": false
}"""

_NORMALISE_PROMPT = """You are a yacht industry data normaliser. You receive text scraped from a yacht crew job board website.

Your job:
1. First, verify the text actually contains a real, specific yacht crew job listing. Scrapers sometimes pick up navigation text, ads, expired placeholders, error pages, login prompts, or other non-job content.
2. If it IS a real job listing, extract and normalise every available detail into the JSON schema below.

Return ONLY a JSON object. No markdown, no explanation, nothing else.

If the text is NOT a real job listing (garbage, navigation, ads, empty/placeholder content, expired listing, or no identifiable crew role):
{"is_job": false}

If it IS a real job listing:
{
  "is_job": true,
  "title": "concise job title, max 100 chars",
  "role": "specific crew role, e.g. Stewardess, Chief Engineer, Captain, Chef, Bosun",
  "yacht": "vessel name if mentioned, else 'Private Yacht' or 'Charter Yacht'",
  "yacht_type": "Motor Yacht | Sailing Yacht | Superyacht | Catamaran | Expedition Yacht | null",
  "yacht_length_m": null,
  "vessel_flag": "flag state or null",
  "vessel_itinerary": "e.g. Mediterranean Summer 2026 or null",
  "department": "Interior | Deck | Engineering | Galley | Management | null",
  "rank_level": "Senior | Junior | Entry Level | null",
  "location": "base port or region",
  "start_date": "e.g. ASAP, April 2026, or null",
  "contract_type": "Seasonal | Permanent | Rotational | Temporary | null",
  "rotation": "rotation pattern or null",
  "season": "e.g. Mediterranean Summer 2026 or null",
  "salary_currency": "EUR | USD | GBP | null",
  "salary_min": null,
  "salary_max": null,
  "experience_required_years": null,
  "minimum_license": "e.g. STCW, OOW 500gt, or null",
  "certifications_required": "comma-separated list or null",
  "languages_required": "e.g. English required, Italian preferred or null",
  "description": "Clean 2–3 sentence professional summary of the position",
  "responsibilities": "Key responsibilities as a concise paragraph, or null",
  "requirements": "Key requirements as a concise paragraph, or null",
  "benefits": "Any benefits mentioned or null",
  "contact_email": "email address extracted verbatim or null",
  "recruiter_name": "contact/recruiter name or null",
  "recruiter_agency": "agency or company name or null",
  "urgent_hire": false,
  "visa_support": false,
  "accommodation": "Onboard | Shoreside | null",
  "travel_reimbursement": false
}"""


def review_post(
    post_text: str,
    post_url: str,
    api_key: str,
    model: str,
    *,
    trusted_source: bool = False,
) -> dict | None:
    """
    Send a raw post to ChatGPT for classification and structured extraction.

    Args:
        post_text:      Raw text of the post or listing.
        post_url:       URL of the post/listing (used for logging).
        api_key:        OpenAI API key.
        model:          OpenAI model name.
        trusted_source: If True (e.g. Dockwalk, WorkOnAYacht), use a lighter
                        normalisation prompt instead of the full strict classifier.
                        Still validates that the content is actually a job — rejects
                        garbage, navigation text, ads, and expired placeholders.

    Returns:
        A dict of job fields (matching the Job model) if the post is a job offer.
        None if the post is not a job offer or if the AI call fails.
    """
    if not api_key:
        log.warning("OPENAI_API_KEY not set — skipping AI review for %s", post_url)
        return None

    text = (post_text or "").strip()
    if not text:
        log.debug("Empty post text — skipping AI review for %s", post_url)
        return None

    if not trusted_source:
        # Cheap pre-filter: reject obvious "seeking work" posts before spending AI tokens
        _lower = text.lower()
        _SEEKER_PHRASES = (
            "seeking a position", "seeking position", "looking for a position",
            "looking for work", "looking for employment", "seeking employment",
            "available for work", "available immediately for", "open to opportunities",
            "hoping to find", "would love to join", "looking to join a crew",
            "looking to contribute", "seeking to contribute", "please consider me",
            "i am available", "i'm available", "my cv", "my resume", "attach my cv",
            "seeking long-term", "seeking a long-term", "seeking an opportunity",
        )
        if any(phrase in _lower for phrase in _SEEKER_PHRASES):
            log.debug("Pre-filter: crew-seeking post rejected | url=%s", post_url)
            return None

        # Pre-filter: reject agency recruitment blasts listing many roles
        _AGENCY_SPAM_PHRASES = (
            "expanding its crew network", "expanding our crew network",
            "building our crew pool", "building a crew pool",
            "growing our network", "register with us",
            "join our crew database", "add to our database",
        )
        if any(phrase in _lower for phrase in _AGENCY_SPAM_PHRASES):
            log.debug("Pre-filter: agency spam rejected | url=%s", post_url)
            return None

    # Truncate to avoid excessive token usage (~3000 chars ≈ ~750 tokens)
    if len(text) > 3000:
        text = text[:3000] + "\n[truncated]"

    system_prompt = _NORMALISE_PROMPT if trusted_source else _SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Post URL: {post_url}\n\nPost text:\n{text}"},
    ]

    try:
        content = call_openai(
            api_key=api_key,
            messages=messages,
            model=model,
            max_tokens=1200,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(content)

        if not parsed.get("is_job"):
            log.debug("AI: not a job posting | trusted=%s | url=%s", trusted_source, post_url)
            return None

        parsed.pop("is_job", None)
        log.info(
            "AI: job confirmed | role=%r | title=%r | url=%s",
            parsed.get("role"),
            parsed.get("title"),
            post_url,
        )
        return parsed

    except json.JSONDecodeError as exc:
        log.error("AI: could not parse JSON response | error=%s | url=%s", exc, post_url)
        return None
    except AIClientError as exc:
        log.error("AI: call failed | code=%s | error=%s | url=%s", exc.crv_code, exc, post_url)
        return None
    except Exception as exc:
        log.error("AI: unexpected error | error=%s | url=%s", exc, post_url)
        return None
