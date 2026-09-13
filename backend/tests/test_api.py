import copy
import hashlib
import json
import time
import wave

import pytest
from editmaxxing.app import create_app
from editmaxxing.config import Settings
from editmaxxing.models import Plan
from fastapi.testclient import TestClient


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "editmaxxing.media.boundary_contact_sheet",
        lambda path, b, duration, output: {
            "path": str(tmp_path / "sheet.jpg"),
            "boundary_id": b["id"],
            "source_id": b["source_id"],
            "timestamp_ms": b["timestamp_ms"],
            "frame_timestamps_ms": [b["timestamp_ms"]] * 8,
        },
    )
    app = create_app(
        Settings(
            storage_root=tmp_path / "data",
            worker_enabled=False,
            enable_fixtures=True,
            part_size=8,
            openai_api_key="",
        )
    )
    with TestClient(app) as client:
        result = client.post("/api/v1/projects", json={"name": "Integration"}).json()
        client.headers["Authorization"] = "Bearer " + result["project_token"]
        yield client, app, result["project_id"]


def source(client, pid, sid="body", role="body", content=b"original bytes", scripts=None):
    body = {
        "source_id": sid,
        "role": role,
        "duration_ms": 12000,
        "fingerprint": hashlib.sha256(content).hexdigest(),
        "timing": {"duration_ms": 12000},
        "hook_scripts": scripts or [],
    }
    r = client.post(f"/api/v1/projects/{pid}/sources", json=body)
    assert r.status_code == 201, r.text
    return body


def audio(client, pid, sid, tmp_path):
    path = tmp_path / f"{sid}.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000 * 12)
    payload = path.read_bytes()
    r = client.put(
        f"/api/v1/projects/{pid}/sources/{sid}/audio",
        content=payload,
        headers={
            "X-Content-SHA256": hashlib.sha256(payload).hexdigest(),
            "X-Timing-Manifest": json.dumps({"duration_ms": 12000}),
        },
    )
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def ready_video(app, pid, sid="body"):
    with app.state.service.store.tx() as db:
        p = app.state.service.require(db, pid)
        p["sources"][sid].update(video_state="ready", editing_path="fixture-video.mp4")
        p["sources"][sid]["storage"]["original_verified"] = True
        app.state.service.store.save(db, pid, p)


def fixture_analyzed(lab, tmp_path):
    client, app, pid = lab
    source(client, pid)
    client.post(f"/api/v1/projects/{pid}/sources/body/fixture")
    ready_video(app, pid)
    jid = audio(client, pid, "body", tmp_path)
    app.state.worker.run_once()
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["state"] == "succeeded", job
    return client.get(f"/api/v1/projects/{pid}").json()


def test_authorization_validation_and_source_identity(lab):
    client, _app, pid = lab
    assert client.get(f"/api/v1/projects/{pid}", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/api/v1/projects", json={"target_duration_ms": 3}).status_code == 422
    body = source(client, pid)
    assert client.post(f"/api/v1/projects/{pid}/sources", json=body).status_code == 201
    body["fingerprint"] = "b" * 64
    assert client.post(f"/api/v1/projects/{pid}/sources", json=body).status_code == 409


def test_upload_acknowledgement_retry_size_and_manifest(lab):
    c, app, pid = lab
    payload = b"original bytes"
    source(c, pid, content=payload)
    prefix = f"/api/v1/projects/{pid}/sources/body/video/uploads"
    upload = c.post(
        prefix, json={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    ).json()
    route = f"{prefix}/{upload['upload_id']}"
    part = payload[:8]
    headers = {"X-Content-SHA256": hashlib.sha256(part).hexdigest()}
    assert c.put(route + "/parts/0", content=part, headers=headers).status_code == 200
    assert c.put(route + "/parts/0", content=part, headers=headers).status_code == 200
    changed = b"12345678"
    assert (
        c.put(
            route + "/parts/0",
            content=changed,
            headers={"X-Content-SHA256": hashlib.sha256(changed).hexdigest()},
        ).status_code
        == 409
    )
    assert len(c.get(route).json()["parts"]) == 1
    assert (
        c.post(
            route + "/complete", json={"parts": [{"part": 0, "sha256": headers["X-Content-SHA256"]}]}
        ).status_code
        == 422
    )
    assert (
        c.put(
            route + "/parts/1", content=b"x", headers={"X-Content-SHA256": hashlib.sha256(b"x").hexdigest()}
        ).status_code
        == 422
    )
    part = payload[8:]
    sha = hashlib.sha256(part).hexdigest()
    assert c.put(route + "/parts/1", content=part, headers={"X-Content-SHA256": sha}).status_code == 200
    ack = c.get(route).json()["parts"]
    req = {"parts": [{"part": x["part"], "sha256": x["sha256"]} for x in ack]}
    response = c.post(route + "/complete", json=req)
    assert response.status_code == 202
    assert c.post(route + "/complete", json=req).json() == response.json()
    # Actual whole-file validation accepts bytes then ffprobe reports invalid media.
    app.state.worker.run_once()
    job = c.get("/api/v1/jobs/" + response.json()["job_id"]).json()
    assert job["state"] == "failed"
    assert c.get(f"/api/v1/projects/{pid}").json()["sources"]["body"]["storage"]["original_verified"]


def test_reviewed_plan_and_revision_conflict(lab, tmp_path):
    c, app, pid = lab
    project = fixture_analyzed(lab, tmp_path)
    assert project["plan"]["clips"] and len(project["hooks"]) == 4
    assert project["sources"]["body"]["video_state"] == "ready"
    assert project["boundary_reviews"]
    plan = project["plan"]
    original = copy.deepcopy(plan)
    plan["clips"].reverse()
    saved = c.put(f"/api/v1/projects/{pid}/plan", json={"base_revision": 1, "plan": plan})
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert (
        c.put(f"/api/v1/projects/{pid}/plan", json={"base_revision": 1, "plan": original}).status_code == 409
    )
    with app.state.service.store.tx() as db:
        p = app.state.service.require(db, pid)
        p["sources"]["body"]["video_state"] = "pending"
        app.state.service.store.save(db, pid, p)
    r = c.post(
        f"/api/v1/projects/{pid}/renders",
        json={"plan_revision": 2, "kind": "draft", "combinations": [{"id": "body"}]},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "media_pending"


def test_ai_finishing_during_manual_edit_produces_proposal(lab, tmp_path):
    c, app, pid = lab
    source(c, pid)
    c.post(f"/api/v1/projects/{pid}/sources/body/fixture")
    ready_video(app, pid)
    jid = audio(c, pid, "body", tmp_path)
    edit = Plan().model_dump()
    edit["audio"]["normalization_enabled"] = False
    r = c.put(f"/api/v1/projects/{pid}/plan", json={"base_revision": 0, "plan": edit})
    assert r.status_code == 200
    app.state.worker.run_once()
    job = c.get("/api/v1/jobs/" + jid).json()
    assert job["state"] == "succeeded", job
    project = c.get(f"/api/v1/projects/{pid}").json()
    assert project["plan"]["revision"] == 1 and not project["plan"]["clips"]
    assert not project["plan"]["audio"]["normalization_enabled"]
    proposal = project["proposals"][0]
    assert proposal["base_revision"] == 0
    r = c.put(
        f"/api/v1/projects/{pid}/plan",
        json={"base_revision": 0, "plan": proposal["plan"], "proposal_id": proposal["id"]},
    )
    assert r.status_code == 409


def test_hooks_attach_to_current_body_and_render_captures_snapshot(lab, tmp_path):
    c, app, pid = lab
    project = fixture_analyzed(lab, tmp_path)
    scripts = [{"hook_id": h["id"], "text": h["proposed_text"]} for h in project["hooks"]]
    source(c, pid, "hooks", "hooks", scripts=scripts)
    c.post(f"/api/v1/projects/{pid}/sources/hooks/fixture")
    ready_video(app, pid, "hooks")
    jid = audio(c, pid, "hooks", tmp_path)
    plan = project["plan"]
    plan["clips"].reverse()
    saved = c.put(f"/api/v1/projects/{pid}/plan", json={"base_revision": 1, "plan": plan}).json()
    app.state.worker.run_once()
    job = c.get("/api/v1/jobs/" + jid).json()
    assert job["state"] == "succeeded", job
    project = c.get(f"/api/v1/projects/{pid}").json()
    assert project["plan"] == saved
    assert all(h["take_id"] for h in project["hooks"])
    hook = project["hooks"][0]
    reviewed_clips = hook["candidates"][0]["clips"]
    selected = c.put(f"/api/v1/projects/{pid}/hooks/{hook['id']}", json={"take_id": hook["take_id"]})
    assert selected.status_code == 200
    assert selected.json()["clips"] == reviewed_clips
    # Stand-in paths only isolate snapshot capture, ffmpeg output is tested by media/E2E tests.
    with app.state.service.store.tx() as db:
        p = app.state.service.require(db, pid)
        for s in p["sources"].values():
            s["video_state"] = "ready"
            s["storage"]["original_verified"] = True
        app.state.service.store.save(db, pid, p)
    req = {
        "plan_revision": 2,
        "kind": "draft",
        "combinations": [{"id": "one", "hook_id": project["hooks"][0]["id"], "use_title": False}],
    }
    r = c.post(f"/api/v1/projects/{pid}/renders", json=req)
    assert r.status_code == 202, r.text
    with app.state.service.store.tx() as db:
        snapshot = app.state.service.store.job(db, r.json()["job_id"])["payload"]
    captured = snapshot["combinations"][0]["plan"]
    assert captured["clips"][0]["role"] == "hook"
    assert [x for x in captured["clips"] if x["role"] == "body"] == saved["clips"]
    saved["clips"].reverse()
    c.put(f"/api/v1/projects/{pid}/plan", json={"base_revision": 2, "plan": saved})
    assert snapshot["plan_revision"] == 2
    assert captured["clips"][1:] != saved["clips"]


def test_cancellation_restart_expiry_and_delete(lab):
    c, app, pid = lab
    with app.state.service.store.tx() as db:
        j = app.state.service.store.enqueue(db, pid, "rank", {})
    r = c.post(f"/api/v1/jobs/{j['id']}/cancel")
    assert r.status_code == 202
    assert not app.state.worker.run_once()
    source(c, pid)
    r = c.delete(f"/api/v1/projects/{pid}")
    assert r.status_code == 202
    assert c.get(f"/api/v1/projects/{pid}").status_code == 410
    assert c.post(f"/api/v1/projects/{pid}/sources", json={"source_id": "more"}).status_code == 422
    app.state.worker.run_once()
    assert c.get("/api/v1/jobs/" + r.json()["job_id"]).json()["result"]["deleted"]
    assert not app.state.service.store.directory(pid).exists()


def test_restart_marks_interrupted_work_retryable(lab):
    c, app, pid = lab
    with app.state.service.store.tx() as db:
        j = app.state.service.store.enqueue(db, pid, "analyze", {})
        j["state"] = "running"
        app.state.service.store.put_job(db, j)
    app.state.worker.start()
    app.state.worker.close()
    job = c.get("/api/v1/jobs/" + j["id"]).json()
    assert (
        job["state"] == "failed" and job["error"]["code"] == "worker_restarted" and job["error"]["retryable"]
    )


def test_expired_project_and_signed_media_access(lab, tmp_path):
    c, app, pid = lab
    directory = app.state.service.store.directory(pid)
    directory.mkdir(parents=True)
    path = directory / "clip.mp4"
    path.write_bytes(b"test")
    url = app.state.service.signed_url(pid, "clip.mp4", time.time() + 60)["url"]
    assert c.get(url).status_code == 200
    assert c.get(url.replace("signature=", "signature=bad")).status_code == 403
    with app.state.service.store.tx() as db:
        db.execute("UPDATE projects SET expires=? WHERE id=?", (time.time() - 1, pid))
    assert c.get(url).status_code == 410
    app.state.worker.cleanup()
    app.state.worker.run_once()
    assert not directory.exists()


def test_audio_analysis_waits_for_video_and_resumes_same_job(lab, tmp_path, monkeypatch):
    from editmaxxing.provider import FixtureProvider
    from editmaxxing.worker import Worker

    c, app, pid = lab
    payload = b"original bytes"
    source(c, pid, content=payload)
    c.post(f"/api/v1/projects/{pid}/sources/body/fixture")
    count = {"analysis": 0, "review": 0}
    original = FixtureProvider.analyze_body
    original_review = FixtureProvider.review_boundaries

    def analyze(self, *args, **kwargs):
        count["analysis"] += 1
        return original(self, *args, **kwargs)

    def review(self, boundaries, frames):
        count["review"] += 1
        assert len(boundaries) == len(frames) == 6
        result = original_review(self, boundaries, frames)
        for decision, boundary in zip(result.decisions, boundaries):
            decision.timestamp_ms = boundary["min_ms"]
        return result

    monkeypatch.setattr(FixtureProvider, "analyze_body", analyze)
    monkeypatch.setattr(FixtureProvider, "review_boundaries", review)
    jid = audio(c, pid, "body", tmp_path)
    app.state.worker.run_once()
    job = c.get(f"/api/v1/jobs/{jid}").json()
    assert job["state"] == "queued" and job["stage"] == "waiting_video"
    state = c.get(f"/api/v1/projects/{pid}").json()
    assert state["words"] and state["analysis"] and state["plan"]["clips"] == []
    assert count == {"analysis": 1, "review": 0}
    assert not app.state.worker.run_once()
    assert c.post(f"/api/v1/projects/{pid}/analysis").json()["job_id"] == jid
    app.state.worker = Worker(app.state.service)
    assert not app.state.worker.run_once()

    prefix = f"/api/v1/projects/{pid}/sources/body/video/uploads"
    upload = c.post(
        prefix, json={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    ).json()
    route = prefix + "/" + upload["upload_id"]
    parts = []
    for number, start in enumerate(range(0, len(payload), 8)):
        part = payload[start : start + 8]
        sha = hashlib.sha256(part).hexdigest()
        assert (
            c.put(route + f"/parts/{number}", content=part, headers={"X-Content-SHA256": sha}).status_code
            == 200
        )
        parts.append({"part": number, "sha256": sha})
    c.post(route + "/complete", json={"parts": parts})

    def normalize(input_path, output_path, *args):
        output_path.write_bytes(b"normalized test media")
        return {"duration_ms": 12000}

    monkeypatch.setattr("editmaxxing.media.normalize_video", normalize)
    app.state.worker.run_once()
    assert c.get(f"/api/v1/jobs/{jid}").json()["stage"] == "analyze"
    app.state.worker.run_once()
    assert c.get(f"/api/v1/jobs/{jid}").json()["state"] == "succeeded"
    state = c.get(f"/api/v1/projects/{pid}").json()
    assert state["plan"]["clips"] and state["plan"]["captions"]
    evidence = next(iter(state["boundary_reviews"].values()))["evidence"]
    assert any(e["applied_ms"] != e["candidate_ms"] for e in evidence)
    assert state["plan"]["duration_ms"] == sum(
        c["source_end_ms"] - c["source_start_ms"] for c in state["plan"]["clips"]
    )
    assert count == {"analysis": 1, "review": 1}
    retry = c.post(f"/api/v1/projects/{pid}/analysis").json()["job_id"]
    app.state.worker.run_once()
    assert c.get(f"/api/v1/jobs/{retry}").json()["state"] == "succeeded"
    assert count == {"analysis": 1, "review": 1}


def test_waiting_video_job_can_be_cancelled(lab, tmp_path):
    c, app, pid = lab
    source(c, pid)
    c.post(f"/api/v1/projects/{pid}/sources/body/fixture")
    jid = audio(c, pid, "body", tmp_path)
    app.state.worker.run_once()
    assert c.post(f"/api/v1/jobs/{jid}/cancel").status_code == 202
    assert not app.state.worker.run_once()
    assert c.get(f"/api/v1/jobs/{jid}").json()["state"] == "cancelled"
