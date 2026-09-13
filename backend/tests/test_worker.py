import copy
import hashlib
import shutil
from pathlib import Path

import pytest
from editmaxxing.app import create_app
from editmaxxing.config import Settings
from editmaxxing.editing import canonicalize_plan, clips_for_take, compile_draft
from editmaxxing.models import Plan
from editmaxxing.provider import FixtureProvider
from fastapi.testclient import TestClient


@pytest.fixture
def workspace(tmp_path, monkeypatch):
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
        Settings(storage_root=tmp_path / "data", worker_enabled=False, enable_fixtures=True, part_size=1000)
    )
    with TestClient(app) as client:
        created = client.post("/api/v1/projects", json={"name": "Worker regression"}).json()
        pid = created["project_id"]
        client.headers["Authorization"] = "Bearer " + created["project_token"]
        yield client, app, pid


def seed(workspace, *, hook=False, original=b"immutable original"):
    client, app, pid = workspace
    request = {
        "source_id": "body",
        "role": "body",
        "duration_ms": 160000,
        "fingerprint": hashlib.sha256(original).hexdigest(),
        "timing": {"duration_ms": 160000},
    }
    assert client.post(f"/api/v1/projects/{pid}/sources", json=request).status_code == 201
    words = [
        {
            "id": f"w{i}",
            "source_id": "body",
            "text": f"Sentence{i}.",
            "start_ms": start,
            "end_ms": start + 29000,
        }
        for i, start in enumerate((1000, 35000, 69000))
    ]
    takes = [
        {
            "id": f"t{i}",
            "line_id": f"l{i}",
            "word_ids": [w["id"]],
            "role": "body",
            "selected": True,
            "score": 100 - i * 20,
            "reason": "Complete sentence",
            "emphasis_word_ids": [],
        }
        for i, w in enumerate(words)
    ]
    with app.state.service.store.tx() as db:
        p = app.state.service.require(db, pid)
        s = p["sources"]["body"]
        s.update(
            words=copy.deepcopy(words),
            audio_path="canonical.wav",
            raw_audio_path="uploaded.wav",
            audio_sha256="b" * 64,
            audio_timing={"duration_ms": 160000},
            video_state="ready",
            editing_path="source.mp4",
            fixture=True,
            metrics={"silences": []},
        )
        p["words"] = words
        p["takes"] = {t["id"]: t for t in takes}
        p["analysis"] = {"body_analysis": {"source_id": "body", "editorial": {"takes": takes}}}
        p["plan"] = compile_draft(words, {"takes": takes}, p["sources"], dead_space_enabled=False)
        p["plan"]["revision"] = 1
        if hook:
            hword = {"id": "wh", "source_id": "body", "text": "Hook.", "start_ms": 120000, "end_ms": 140000}
            ht = {
                "id": "ht",
                "line_id": "hl",
                "word_ids": ["wh"],
                "role": "hook",
                "selected": True,
                "score": 90,
                "reason": "Recorded hook",
                "emphasis_word_ids": [],
            }
            p["words"].append(hword)
            p["takes"]["ht"] = ht
            hclips = clips_for_take(ht, p["words"], p["sources"], dead_space_enabled=False)
            p["hooks"] = [
                {
                    "id": "h",
                    "take_id": "ht",
                    "proposed_text": "Hook",
                    "clips": hclips,
                }
            ]
            p["titles"] = [{"id": "title", "text": "Title", "missing_slots": []}]
            p["plan"].update(
                clips=hclips + p["plan"]["clips"],
                selected_hook_id="h",
                selected_visual_title_id="title",
                hook_overlay={
                    "text": "Creator title",
                    "position": {"x": 0.4, "y": 0.2},
                    "hold_ms": 3500,
                    "fade_ms": 300,
                },
            )
            p["plan"]["caption_edits"] = [
                {
                    "id": "manual",
                    "clip_id": p["plan"]["clips"][1]["id"],
                    "source_start_ms": 1000,
                    "source_end_ms": 2000,
                    "words": [{"word_id": None, "text": "Creator correction"}],
                    "replaces_word_ids": ["w0"],
                }
            ]
            p["plan"] = canonicalize_plan(p["plan"], p["words"], p["sources"], p["takes"])
        app.state.service.store.save(db, pid, p)
    return p


def test_cancel_between_checkpoint_and_analysis_publish_preserves_project(workspace, monkeypatch):
    client, app, pid = workspace
    seed(workspace)
    with app.state.service.store.tx() as db:
        p = app.state.service.require(db, pid)
        p.update(plan=Plan().model_dump(), takes={}, analysis={})
        app.state.service.store.save(db, pid, p)
    jid = client.post(f"/api/v1/projects/{pid}/analysis").json()["job_id"]
    checkpoint = app.state.worker.checkpoint

    def cancel_after_checkpoint(job, stage=None, progress=None):
        checkpoint(job, stage, progress)
        if stage == "plan":
            assert client.post(f"/api/v1/jobs/{jid}/cancel").status_code == 202

    monkeypatch.setattr(app.state.worker, "checkpoint", cancel_after_checkpoint)
    app.state.worker.run_once()
    result = client.get(f"/api/v1/jobs/{jid}").json()
    assert result["state"] == "cancelled"
    p = client.get(f"/api/v1/projects/{pid}").json()
    assert p["plan"]["revision"] == 0 and p["plan"]["clips"] == []
    assert p["analysis"] and len(p["hooks"]) == 4
    assert p["recommendations"]["status"] == "ready"


def test_rank_snapshot_retains_caption_title_and_reserves_hook_duration(workspace):
    client, app, pid = workspace
    p = seed(workspace, hook=True)
    baseline = copy.deepcopy(p["plan"])
    response = client.post(
        f"/api/v1/projects/{pid}/rank",
        json={
            "base_revision": 1,
            "target_duration_ms": 90000,
            "selected_hook_id": "h",
            "dead_space_enabled": False,
        },
    )
    assert response.status_code == 202, response.text
    jid = response.json()["job_id"]
    changed = copy.deepcopy(baseline)
    changed["hook_overlay"]["text"] = "A concurrent title"
    saved = client.put(f"/api/v1/projects/{pid}/plan", json={"base_revision": 1, "plan": changed})
    assert saved.status_code == 200, saved.text
    app.state.worker.run_once()
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["state"] == "succeeded", job
    proposed = job["result"]["proposal"]
    assert proposed["base_revision"] == 1
    assert proposed["plan"]["hook_overlay"] == baseline["hook_overlay"]
    assert proposed["plan"]["selected_visual_title_id"] == "title"
    assert proposed["plan"]["caption_edits"] == baseline["caption_edits"]
    assert proposed["plan"]["duration_ms"] <= 90000
    assert len(proposed["plan"]["dropped_lines"]) == 1
    assert client.get(f"/api/v1/projects/{pid}").json()["plan"] == saved.json()
    assert (
        client.put(
            f"/api/v1/projects/{pid}/plan",
            json={"base_revision": 1, "proposal_id": proposed["id"], "plan": proposed["plan"]},
        ).status_code
        == 409
    )


def test_verified_original_retry_uses_retained_bytes_and_verification_time(workspace, monkeypatch):
    client, app, pid = workspace
    payload = b"immutable original"
    seed(workspace, original=payload)
    prefix = f"/api/v1/projects/{pid}/sources/body/video/uploads"
    upload = client.post(
        prefix, json={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    ).json()
    route = prefix + "/" + upload["upload_id"]
    sha = hashlib.sha256(payload).hexdigest()
    assert (
        client.put(route + "/parts/0", content=payload, headers={"X-Content-SHA256": sha}).status_code == 200
    )
    manifest = {"parts": [{"part": 0, "sha256": sha}]}
    first = client.post(route + "/complete", json=manifest).json()["job_id"]

    def fail(*args):
        raise ValueError("Synthetic processor interruption")

    monkeypatch.setattr("editmaxxing.media.normalize_video", fail)
    app.state.worker.run_once()
    assert client.get(f"/api/v1/jobs/{first}").json()["state"] == "failed"
    with app.state.service.store.tx() as db:
        s = app.state.service.require(db, pid)["sources"]["body"]
    original = Path(s["original_path"])
    verified_at, inode = s["storage"]["verified_at"], original.stat().st_ino
    shutil.rmtree(app.state.service.part_path(pid, "body", upload["upload_id"], 0).parent)

    def succeed(input_path, output_path, *args):
        Path(output_path).write_bytes(b"editing derivative")
        return {"duration_ms": 160000}

    monkeypatch.setattr("editmaxxing.media.normalize_video", succeed)
    second = client.post(route + "/complete", json=manifest).json()["job_id"]
    app.state.worker.run_once()
    assert client.get(f"/api/v1/jobs/{second}").json()["state"] == "succeeded"
    assert original.read_bytes() == payload and original.stat().st_ino == inode
    assert (
        client.get(f"/api/v1/projects/{pid}").json()["sources"]["body"]["storage"]["verified_at"]
        == verified_at
    )


def test_feedback_cache_survives_title_edit_and_invalidates_opening_trim(workspace, monkeypatch):
    client, app, pid = workspace
    seed(workspace, hook=True)
    counts = {"metrics": 0, "provider": 0}

    def measure(path, start_ms, end_ms):
        counts["metrics"] += 1
        return {
            "duration_ms": end_ms - start_ms,
            "rms_dbfs": -20,
            "speech_rms_dbfs": -19,
            "pause_fraction": 0.1,
            "start_ms": start_ms,
        }

    original_feedback = FixtureProvider.feedback

    def feedback(self, context):
        counts["provider"] += 1
        return original_feedback(self, context)

    monkeypatch.setattr("editmaxxing.media.audio_metrics", measure)
    monkeypatch.setattr(FixtureProvider, "feedback", feedback)
    with app.state.service.store.tx() as db:
        app.state.service.store.enqueue(db, pid, "feedback", {"body_revision": 1})
    app.state.worker.run_once()
    assert counts == {"metrics": 2, "provider": 1}
    current = client.get(f"/api/v1/projects/{pid}").json()["plan"]
    current["hook_overlay"]["text"] = "An edited title"
    saved = client.put(f"/api/v1/projects/{pid}/plan", json={"base_revision": 1, "plan": current})
    assert saved.status_code == 200, saved.text
    app.state.worker.run_once()
    assert counts == {"metrics": 2, "provider": 1}
    current = saved.json()
    current["clips"][1]["source_start_ms"] += 50
    assert (
        client.put(f"/api/v1/projects/{pid}/plan", json={"base_revision": 2, "plan": current}).status_code
        == 200
    )
    app.state.worker.run_once()
    assert counts == {"metrics": 3, "provider": 2}
    result = client.get(f"/api/v1/projects/{pid}").json()["feedback"][-1]
    assert result["body_revision"] == 3 and result["hook_take_id"] == "ht" and result["stale"] is False


def test_visual_review_returns_cached_revision_bound_proposal(workspace, monkeypatch):
    client, app, pid = workspace
    project = seed(workspace)
    before = copy.deepcopy(project["plan"])
    with app.state.service.store.tx() as db:
        p = app.state.service.require(db, pid)
        p["sources"]["body"].update(video_state="ready", editing_path="source.mp4")
        p["sources"]["body"]["storage"]["original_verified"] = True
        app.state.service.store.save(db, pid, p)
    calls = {"frames": 0, "provider": 0}

    def frames(path, boundary, duration_ms, output_dir):
        calls["frames"] += 1
        return {
            "source_id": "body",
            "timestamp_ms": boundary["timestamp_ms"],
            "path": "frame.jpg",
            "boundary_id": boundary["id"],
            "frame_timestamps_ms": [boundary["timestamp_ms"]] * 8,
        }

    review = FixtureProvider.review_boundaries

    def visually_review(self, boundaries, frames):
        calls["provider"] += 1
        assert len(frames) == len(boundaries) == 6
        return review(self, boundaries, frames)

    monkeypatch.setattr("editmaxxing.media.boundary_contact_sheet", frames)
    monkeypatch.setattr(FixtureProvider, "review_boundaries", visually_review)
    for _ in range(2):
        response = client.post(
            f"/api/v1/projects/{pid}/visual-review", json={"base_revision": 1, "source_id": "body"}
        )
        assert response.status_code == 202, response.text
        app.state.worker.run_once()
        job = client.get("/api/v1/jobs/" + response.json()["job_id"]).json()
        assert job["state"] == "succeeded", job
        assert job["result"]["proposal"]["base_revision"] == 1
        assert job["result"]["proposal"]["kind"] == "visual_review"
        assert client.get(f"/api/v1/projects/{pid}").json()["plan"] == before
    assert calls == {"frames": 6, "provider": 1}


def test_visual_review_batches_every_boundary_and_reuses_results(workspace, monkeypatch):
    client, app, pid = workspace
    seed(workspace)
    with app.state.service.store.tx() as db:
        p = app.state.service.require(db, pid)
        p["sources"]["body"]["storage"]["original_verified"] = True
        app.state.service.store.save(db, pid, p)
    monkeypatch.setattr("editmaxxing.boundaries.BATCH_SIZE", 2)
    calls = []
    original = FixtureProvider.review_boundaries

    def review(self, boundaries, frames):
        calls.append([b["id"] for b in boundaries])
        return original(self, boundaries, frames)

    monkeypatch.setattr(FixtureProvider, "review_boundaries", review)
    for _ in range(2):
        response = client.post(
            f"/api/v1/projects/{pid}/visual-review", json={"base_revision": 1, "source_id": "body"}
        )
        app.state.worker.run_once()
        job = client.get("/api/v1/jobs/" + response.json()["job_id"]).json()
        assert job["state"] == "succeeded", job
    assert len(calls) == 3 and len({b for batch in calls for b in batch}) == 6
    project = client.get(f"/api/v1/projects/{pid}").json()
    record = next(iter(project["boundary_reviews"].values()))
    assert len(record["frames"]) == len(record["evidence"]) == 6
    assert record["elapsed_seconds"] >= 0
