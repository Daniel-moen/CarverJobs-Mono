def test_feedback_status_initially_not_submitted(client):
    resp = client.get("/feedback/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["submitted"] is False
    assert body["eligible"] is True
    assert body["reward_amount"] == 5


def test_feedback_submit_rewards_tokens_once(client):
    first = client.post("/feedback/submit", json={
        "source": "website_popup",
        "rating": 5,
        "liked": "Fast matching flow.",
        "improved": "More filters.",
        "confusing": "",
        "recommend": "yes",
        "anything_else": "Keep going.",
    })

    assert first.status_code == 201
    first_body = first.json()
    assert first_body["submitted"] is True
    assert first_body["reward_granted"] is True
    assert first_body["reward_amount"] == 5
    assert first_body["credits_balance"] == 7

    duplicate = client.post("/feedback/submit", json={
        "source": "whatsapp_message",
        "rating": 4,
        "recommend": "maybe",
    })

    assert duplicate.status_code == 201
    duplicate_body = duplicate.json()
    assert duplicate_body["submitted"] is True
    assert duplicate_body["reward_granted"] is False
    assert duplicate_body["credits_balance"] == 7

    status = client.get("/feedback/status")
    assert status.status_code == 200
    assert status.json()["submitted"] is True


def test_feedback_targeting_can_disable_reward(client):
    settings_resp = client.patch("/admin/feedback/settings", json={
        "enabled": False,
        "target_mode": "off",
        "target_user_keys": [],
    })
    assert settings_resp.status_code == 200
    assert settings_resp.json()["target_mode"] == "off"

    status = client.get("/feedback/status")
    assert status.status_code == 200
    assert status.json()["eligible"] is False

    submit = client.post("/feedback/submit", json={
        "source": "website_popup",
        "rating": 5,
        "recommend": "yes",
    })
    assert submit.status_code == 403


def test_feedback_specific_target_allows_matching_user(client):
    settings_resp = client.patch("/admin/feedback/settings", json={
        "enabled": True,
        "target_mode": "specific",
        "target_user_keys": ["admin"],
    })
    assert settings_resp.status_code == 200

    status = client.get("/feedback/status")
    assert status.status_code == 200
    body = status.json()
    assert body["eligible"] is True
    assert body["force_prompt"] is True
