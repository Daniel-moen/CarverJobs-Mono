import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.settings import settings

FEEDBACK_CAMPAIGN = "feedback_2_tokens"
# Token reward for submitting feedback. Set to 0 to disable the reward (feedback
# is still recorded). Raise it if you want to incentivise feedback again.
FEEDBACK_REWARD_TOKENS = 0
TARGET_MODES = {"all", "website", "whatsapp", "specific", "off"}


def _normalise_user_key(user_key: str) -> str:
    return str(user_key or "").strip().lower()


def _parse_targets(raw: str | None) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    seen: set[str] = set()
    targets: list[str] = []
    for item in parsed:
        key = _normalise_user_key(str(item))
        if key and key not in seen:
            seen.add(key)
            targets.append(key)
    return targets


def _targets_json(target_user_keys: list[str]) -> str:
    return json.dumps([_normalise_user_key(k) for k in target_user_keys if _normalise_user_key(k)])


def _user_is_old_enough_for_website_feedback(db: Session, *, user_key: str) -> bool:
    min_age_hours = max(0, int(settings.FEEDBACK_MIN_ACCOUNT_AGE_HOURS))
    if min_age_hours <= 0:
        return True

    normalised_key = _normalise_user_key(user_key)
    if not normalised_key:
        return False

    user_created_at = (
        db.query(models.User.created_at)
        .filter(models.User.email == normalised_key)
        .scalar()
    )
    # Keep non-website identities (e.g. admin tests, phone-based users) compatible.
    if user_created_at is None:
        return True

    if user_created_at.tzinfo is None:
        user_created_at = user_created_at.replace(tzinfo=timezone.utc)
    account_age_seconds = (datetime.now(timezone.utc) - user_created_at).total_seconds()
    return account_age_seconds >= (min_age_hours * 3600)


def get_feedback_setting(db: Session) -> models.FeedbackCampaignSetting:
    setting = (
        db.query(models.FeedbackCampaignSetting)
        .filter(models.FeedbackCampaignSetting.campaign == FEEDBACK_CAMPAIGN)
        .first()
    )
    if setting:
        if setting.target_mode not in TARGET_MODES:
            setting.target_mode = "all"
            db.commit()
        return setting

    setting = models.FeedbackCampaignSetting(
        campaign=FEEDBACK_CAMPAIGN,
        enabled=True,
        target_mode="all",
        target_user_keys_json="[]",
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def serialise_feedback_setting(setting: models.FeedbackCampaignSetting) -> dict:
    return {
        "campaign": setting.campaign,
        "enabled": bool(setting.enabled),
        "target_mode": setting.target_mode if setting.target_mode in TARGET_MODES else "all",
        "target_user_keys": _parse_targets(setting.target_user_keys_json),
        "reward_amount": FEEDBACK_REWARD_TOKENS,
    }


def update_feedback_setting(
    db: Session,
    *,
    enabled: bool,
    target_mode: str,
    target_user_keys: list[str],
) -> models.FeedbackCampaignSetting:
    setting = get_feedback_setting(db)
    setting.enabled = bool(enabled)
    setting.target_mode = target_mode if target_mode in TARGET_MODES else "all"
    setting.target_user_keys_json = _targets_json(target_user_keys)
    db.commit()
    db.refresh(setting)
    return setting


def feedback_is_eligible(
    db: Session,
    *,
    user_key: str,
    source: str,
) -> tuple[bool, models.FeedbackCampaignSetting]:
    setting = get_feedback_setting(db)
    mode = setting.target_mode if setting.target_mode in TARGET_MODES else "all"
    if not setting.enabled or mode == "off":
        return False, setting

    if mode == "all":
        mode_eligible = True
    elif mode == "website":
        mode_eligible = source == "website_popup"
    elif mode == "whatsapp":
        mode_eligible = source == "whatsapp_message"
    elif mode == "specific":
        targets = set(_parse_targets(setting.target_user_keys_json))
        mode_eligible = _normalise_user_key(user_key) in targets
    else:
        mode_eligible = False

    if not mode_eligible:
        return False, setting
    if source == "website_popup" and not _user_is_old_enough_for_website_feedback(db, user_key=user_key):
        return False, setting
    return True, setting
