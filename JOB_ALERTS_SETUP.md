# Turn on WhatsApp job alerts (the win-back loop)

The retention loop in `api/app/services/job_alerts.py` runs on two channels:

| Who | Channel | Needs a template? | Cost |
| --- | --- | --- | --- |
| Messaged us in the last 23h | Free-form interactive message, naming the actual jobs | **No** | R0 |
| Dormant (outside the 24h window) | Meta-approved template | **Yes** | ~R0.40–R1/send |

**The free-form half is already live** — no setup, it works the moment WhatsApp
credentials exist. The steps below switch on the second half, which is what
reactivates users who have gone quiet. That's the higher-leverage one: dormant
users get "N new jobs match your profile", reply *match*, hit the paywall teaser,
and buy.

Nothing needs backfilling when you do it. Dormant users are skipped without a
timestamp being written, so the first sweep after you set the env var reaches
them all. Each sweep logs how many are waiting (`needs_template=N`).

## The other free loops (already on, no setup)

Job alerts only cover users who have a profile with a desired role. Three other
sweeps handle everyone else, all free-form inside the 24h window:

| Loop | Who | When |
| --- | --- | --- |
| Quality pulse | Just got match results | 10 min after |
| Apply follow-up | Has a match run with results | ~18h after the run |
| Win-back stage 1 | Stopped mid-onboarding | 3h of silence |
| Win-back stage 2 | No match run at all | 20h of silence (last chance) |

No user gets two proactive messages within 6h, whichever loops are due — the
spacing is enforced across all of them in `services/proactive.py`.

## 1. Create the template (5 min)

Meta Business Manager → WhatsApp Manager → Message templates → Create template:

- **Category:** Marketing
- **Name:** `job_alert_v1`
- **Language:** English
- **Body:**

  > Hi {{1}}, {{2}} new yacht jobs matching your profile just landed on CARVER. Reply *match* and I'll rank them against your profile. 🛥️

- **Sample values:** `{{1}}` = Daniel, `{{2}}` = 4

Approval usually takes minutes to a few hours.

## 2. Configure Railway (1 min)

On the `api` service, add:

```
WHATSAPP_JOB_ALERT_TEMPLATE=job_alert_v1
WHATSAPP_JOB_ALERT_LANGUAGE=en
```

Optional tuning (defaults shown):

```
JOB_ALERT_MIN_INTERVAL_HOURS=72    # min gap per user
JOB_ALERT_CHECK_INTERVAL_HOURS=24  # sweep frequency
```

Redeploy. The loop sweeps within 24h (first sweep 5 min after boot), alerts only
users in `chat` mode with a desired role, only about jobs < 7 days old, capped
at 50 sends per sweep. A user inside the 24h window is always sent free-form,
even once the template exists — never pay for a send that's free.

An alert is also held back for 6h after a "did you apply?" follow-up, so the two
proactive loops can't land on the same person in one afternoon.

## Cost

Marketing template sends are paid per message (~R0.40–R1 each depending on
Meta's current ZA rate). At 38 users, a full sweep costs pocket change.
Free-form sends inside the service window are free at any volume.

## What happens after they reply

Reply *match* → match run → if they're out of tokens they now get the
**paywall teaser** (real matching job counts + locked positions + Buy Tokens
button) instead of a flat "you need a token" refusal.
