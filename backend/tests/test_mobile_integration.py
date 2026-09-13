import copy

import pytest
from editmaxxing.models import Editorial, PairAssessment
from editmaxxing.provider import FixtureProvider, ProviderError, fixture_words, validate_editorial
from test_api import audio, fixture_analyzed, ready_video, source
from test_api import lab as api_lab

lab = api_lab


def drain(app):
    for _ in range(40):
        if not app.state.worker.run_once():
            return
    raise AssertionError("Queue did not settle")


def hook_source(lab, tmp_path, hook, sid, action_start=None):
    c, app, pid = lab
    scripts = [
        {
            "hook_id": hook["id"],
            "text": hook["proposed_text"],
            "capture_revision": hook["capture_revision"],
            "action_start_ms": action_start,
        }
    ]
    source(c, pid, sid, "hooks", scripts=scripts)
    c.post(f"/api/v1/projects/{pid}/sources/{sid}/fixture")
    ready_video(app, pid, sid)
    audio(c, pid, sid, tmp_path)
    drain(app)
    return c.get(f"/api/v1/projects/{pid}").json()


def request_for(p, hook_ids=None, title_ids=None):
    hook_ids = hook_ids or [p["hooks"][0]["id"]]
    title_ids = title_ids or [p["titles"][0]["id"]]
    return {
        "request_id": "render_mobile",
        "kind": "draft",
        "plan_revision": p["plan"]["revision"],
        "combinations": [
            {"id": f"{h}--{t}", "hook_id": h, "visual_title_id": t} for h in hook_ids for t in title_ids
        ],
    }


def test_recommendations_publish_before_video_and_preserve_creator_edits(lab, tmp_path):
    c, app, pid = lab
    source(c, pid)
    c.post(f"/api/v1/projects/{pid}/sources/body/fixture")
    jid = audio(c, pid, "body", tmp_path)
    app.state.worker.run_once()
    p = c.get(f"/api/v1/projects/{pid}").json()
    assert c.get(f"/api/v1/jobs/{jid}").json()["stage"] == "waiting_video"
    assert p["recommendations"]["status"] == "ready"
    assert len(p["hooks"]) == len(p["titles"]) == 4
    assert p["plan"]["clips"] == []
    h, t = p["hooks"][0], p["titles"][0]
    assert (
        c.put(
            f"/api/v1/projects/{pid}/hooks/{h['id']}",
            json={"proposed_text": "Hear the opening clearly", "base_revision": 1},
        ).status_code
        == 200
    )
    assert (
        c.put(
            f"/api/v1/projects/{pid}/titles/{t['id']}", json={"text": "A creator title", "base_revision": 1}
        ).status_code
        == 200
    )
    # Canonical IDs support hook registration during body upload.
    edited = c.get(f"/api/v1/projects/{pid}").json()["hooks"][0]
    source(
        c,
        pid,
        "early",
        "hooks",
        scripts=[{"hook_id": h["id"], "text": edited["proposed_text"], "capture_revision": 2}],
    )
    ready_video(app, pid)
    with app.state.service.store.tx() as db:
        waiting = app.state.service.store.job(db, jid)
        waiting["stage"] = "queued"
        app.state.service.store.put_job(db, waiting)
    drain(app)
    current = c.get(f"/api/v1/projects/{pid}").json()
    assert current["hooks"][0]["proposed_text"] == edited["proposed_text"]
    assert current["hooks"][0]["generated_text"] == h["proposed_text"]
    assert current["titles"][0]["text"] == "A creator title"
    assert current["titles"][0]["rationale_revision"] == 1
    assert current["plan"]["clips"]


def test_two_spoken_three_titles_snapshot_identity_and_idempotent_render(lab, tmp_path, monkeypatch):
    c, app, pid = lab
    p = fixture_analyzed(lab, tmp_path)
    for i, hook in enumerate(p["hooks"][:2]):
        p = hook_source(lab, tmp_path, hook, f"hooks{i}")
    request = request_for(p, [h["id"] for h in p["hooks"][:2]], [t["id"] for t in p["titles"][:3]])
    response = c.post(f"/api/v1/projects/{pid}/renders", json=request)
    assert response.status_code == 202, response.text
    result = response.json()
    assert len(result["inputs"]) == 6
    assert c.post(f"/api/v1/projects/{pid}/renders", json=request).json() == result
    changed = copy.deepcopy(request)
    changed["kind"] = "export"
    assert c.post(f"/api/v1/projects/{pid}/renders", json=changed).status_code == 409
    tid = p["titles"][0]["id"]
    assert (
        c.put(
            f"/api/v1/projects/{pid}/titles/{tid}", json={"base_revision": 1, "text": "Changed during render"}
        ).status_code
        == 200
    )
    monkeypatch.setattr("editmaxxing.media.render_plan", lambda *args: {"fixture": True})
    drain(app)
    completed = c.get(f"/api/v1/jobs/{result['job_id']}").json()
    assert completed["state"] == "succeeded", completed
    outputs = c.get(f"/api/v1/projects/{pid}").json()["outputs"]
    assert len(outputs) == 6
    assert all(o["render_job_id"] == result["job_id"] and o["title_revision"] == 1 for o in outputs)
    assert {o["input_hash"] for o in outputs} == {i["input_hash"] for i in result["inputs"]}
    with app.state.service.store.tx() as db:
        job = app.state.service.store.job(db, result["job_id"])
    assert all(x["plan"]["hook_overlay"]["hold_ms"] == 4000 for x in job["payload"]["combinations"])


def test_retake_selection_and_script_revision_gate(lab, tmp_path):
    c, _app, pid = lab
    p = fixture_analyzed(lab, tmp_path)
    p = hook_source(lab, tmp_path, p["hooks"][0], "take1")
    h = p["hooks"][0]
    first = h["take_id"]
    p = hook_source(lab, tmp_path, h, "take2")
    h = p["hooks"][0]
    assert h["take_id"] == first
    candidate = next(c for c in h["candidates"] if c["source_id"] == "take2")
    selected = c.put(f"/api/v1/projects/{pid}/hooks/{h['id']}", json={"take_id": candidate["take_id"]})
    assert selected.json()["take_id"] == candidate["take_id"]
    edited = c.put(
        f"/api/v1/projects/{pid}/hooks/{h['id']}",
        json={"proposed_text": "Hear this clearly", "base_revision": 1},
    )
    assert edited.json()["capture_revision"] == 2
    assert edited.json()["take_id"] is None
    assert (
        c.put(f"/api/v1/projects/{pid}/hooks/{h['id']}", json={"take_id": first}).json()["error"]["code"]
        == "capture_stale"
    )
    assert c.post(f"/api/v1/projects/{pid}/renders", json=request_for(p)).status_code == 409
    assert (
        c.put(
            f"/api/v1/projects/{pid}/hooks/{h['id']}",
            json={"proposed_text": "Other words", "base_revision": 1},
        ).status_code
        == 409
    )


def test_physical_action_survives_boundary_review_and_snapshot(lab, tmp_path, monkeypatch):
    c, app, pid = lab
    p = fixture_analyzed(lab, tmp_path)
    h = p["hooks"][0]
    h = c.put(f"/api/v1/projects/{pid}/hooks/{h['id']}", json={"action_enabled": True}).json()
    original = FixtureProvider.review_boundaries

    def move_start(self, boundaries, frames):
        result = original(self, boundaries, frames)
        for decision in result.decisions:
            boundary = next(b for b in boundaries if b["id"] == decision.boundary_id)
            if boundary["side"] == "start":
                decision.timestamp_ms += 120
        return result

    monkeypatch.setattr(FixtureProvider, "review_boundaries", move_start)
    p = hook_source(lab, tmp_path, h, "physical", action_start=0)
    assert p["hooks"][0]["clips"][0]["source_start_ms"] == 0
    r = c.post(f"/api/v1/projects/{pid}/renders", json=request_for(p))
    assert r.status_code == 202, r.text
    with app.state.service.store.tx() as db:
        job = app.state.service.store.job(db, r.json()["job_id"])
    assert job["payload"]["combinations"][0]["plan"]["clips"][0]["source_start_ms"] == 0


def test_pair_semantics_and_concurrent_revision_change(lab, tmp_path, monkeypatch):
    c, _app, pid = lab
    p = fixture_analyzed(lab, tmp_path)
    p = hook_source(lab, tmp_path, p["hooks"][0], "hooks")
    request = request_for(p)
    monkeypatch.setattr(
        FixtureProvider,
        "assess_pair",
        lambda *args: PairAssessment(
            supported=True, contradictory=True, repetitive=False, reason="Contradiction"
        ),
    )
    response = c.post(f"/api/v1/projects/{pid}/renders", json=request)
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_pair"

    def concurrent_edit(self, context):
        c.put(
            f"/api/v1/projects/{pid}/titles/{p['titles'][0]['id']}",
            json={"text": "Edited title", "base_revision": 1},
        )
        return PairAssessment(supported=True, contradictory=False, repetitive=False, reason="Supported")

    monkeypatch.setattr(FixtureProvider, "assess_pair", concurrent_edit)
    assert c.post(f"/api/v1/projects/{pid}/renders", json=request).status_code == 409


def test_short_sets_and_evidence_validation():
    words = fixture_words("body")
    editorial = FixtureProvider().analyze(words, [])
    limited = Editorial(
        **{
            **editorial.model_dump(),
            "hooks": [],
            "titles": [],
            "short_set_reason": "Limited distinct evidence",
        }
    )
    assert validate_editorial(limited, words, []).hooks == []
    limited.short_set_reason = ""
    with pytest.raises(ProviderError, match="reason"):
        validate_editorial(limited, words, [])
    editorial.hooks[0].evidence_word_ids = ["foreign"]
    with pytest.raises(ProviderError, match="unavailable"):
        validate_editorial(editorial, words, [])


def test_cancelled_job_retry_uses_separate_identity(lab, tmp_path):
    c, app, pid = lab
    source(c, pid)
    c.post(f"/api/v1/projects/{pid}/sources/body/fixture")
    jid = audio(c, pid, "body", tmp_path)
    c.post(f"/api/v1/jobs/{jid}/cancel")
    retry = c.post(f"/api/v1/jobs/{jid}/retry")
    assert retry.status_code == 202
    assert retry.json()["job_id"] != jid
    assert c.get(f"/api/v1/jobs/{jid}").json()["state"] == "cancelled"
    ready_video(app, pid)
    drain(app)
    assert c.get(f"/api/v1/jobs/{retry.json()['job_id']}").json()["state"] == "succeeded"
