import asyncio
import hashlib
import time

import httpx
import pytest
from editmaxxing.config import Settings
from editmaxxing.service import Problem, Service
from pydantic import ValidationError
from test_api import fixture_analyzed, source
from test_api import lab as api_lab

lab = api_lab


def test_invalid_hook_take_and_signed_url_are_client_errors(lab, tmp_path):
    client, _app, pid = lab
    project = fixture_analyzed(lab, tmp_path)
    hook = project["hooks"][0]
    for value in ([], {}, None, 3):
        response = client.put(f"/api/v1/projects/{pid}/hooks/{hook['id']}", json={"take_id": value})
        assert response.status_code == 422
    assert (
        client.get(
            f"/api/v1/media/{pid}/clip.mp4",
            params={"expires": int(time.time() + 60), "signature": "é"},
        ).status_code
        == 403
    )


def test_upload_reservations_bound_parallel_storage_and_release(tmp_path):
    service = Service(Settings(storage_root=tmp_path, worker_enabled=False, max_incoming_uploads=2))
    used = sum(p.stat().st_size for p in tmp_path.rglob("*") if p.is_file())
    service.settings.storage_quota_bytes = used + 12
    first = service.reserve_incoming(8)
    with pytest.raises(Problem, match="Processing storage is full"):
        service.reserve_incoming(5)
    with (tmp_path / "incoming.bin").open("wb") as file:
        service.write_incoming(first, file, b"1234")
        with pytest.raises(Problem, match="declared byte limit"):
            service.write_incoming(first, file, b"12345")
    second = service.reserve_incoming(4)
    with pytest.raises(Problem, match="capacity is busy"):
        service.reserve_incoming(1)
    service.release_incoming(first)
    service.release_incoming(second)
    assert service.reserve_incoming(8)


@pytest.mark.parametrize("block_event_loop", [False, True])
def test_slow_upload_releases_capacity_and_temporary_file(lab, block_event_loop):
    _client, app, pid = lab
    source(_client, pid)
    app.state.service.settings.upload_timeout_seconds = 0.01

    async def slow():
        yield b"a"
        if block_event_loop:
            time.sleep(0.03)  # noqa: ASYNC251 - exercises delayed timeout callbacks
        else:
            await asyncio.sleep(0.03)
        yield b"b"

    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            return await c.put(
                f"/api/v1/projects/{pid}/sources/body/audio",
                content=slow(),
                headers={
                    "Authorization": _client.headers["Authorization"],
                    "X-Timing-Manifest": '{"duration_ms":12000}',
                    "X-Content-SHA256": hashlib.sha256(b"ab").hexdigest(),
                },
            )

    response = asyncio.run(send())
    assert response.status_code == 408, response.text
    assert response.json()["error"]["retryable"]
    assert not app.state.service.incoming_uploads
    assert not list((app.state.service.store.root / "incoming").iterdir())


def test_late_templates_fill_four_variants_without_overwriting_plan(lab, tmp_path):
    client, app, pid = lab
    project = fixture_analyzed(lab, tmp_path)
    plan = project["plan"]
    hook = project["hooks"][0]
    client.put(f"/api/v1/projects/{pid}/hooks/{hook['id']}", json={"proposed_text": "Creator's hook"})
    templates = [{"id": f"t{i}", "pattern": "Focus on {topic}", "slots": ["topic"]} for i in range(4)]
    templates[0] = {"id": "t0", "pattern": "Clear audio", "slots": []}
    response = client.put(f"/api/v1/projects/{pid}/templates", json={"templates": templates})
    assert response.status_code == 200
    assert len(response.json()["job_ids"]) == 1
    interim = client.get(f"/api/v1/projects/{pid}").json()
    assert all(len(h["visual_titles"]) == 4 for h in interim["hooks"])
    assert all(t["missing_slots"] == ["topic"] for h in interim["hooks"] for t in h["visual_titles"][1:])
    # The hook edit queues feedback ahead of analysis.
    while app.state.worker.run_once():
        pass
    final = client.get(f"/api/v1/projects/{pid}").json()
    job = client.get("/api/v1/jobs/" + response.json()["job_ids"][0]).json()
    assert job["state"] == "succeeded", job
    assert final["plan"] == plan
    assert final["hooks"][0]["proposed_text"] == "Creator's hook"
    assert all(len(h["visual_titles"]) == 4 for h in final["hooks"])
    assert all(h["visual_titles"][0]["ready"] for h in final["hooks"])
    assert all(t["missing_slots"] == ["topic"] for h in final["hooks"] for t in h["visual_titles"][1:])


def test_public_metadata_excludes_server_paths(lab):
    client, app, pid = lab
    source(client, pid)
    service = app.state.service
    with service.store.tx() as db:
        p = service.require(db, pid)
    p["sources"]["body"]["audio_metadata"] = {"path": "/internal/audio.wav", "duration_ms": 12000}
    p["sources"]["body"]["video_metadata"] = {"path": "/internal/original.mp4"}
    p["outputs"] = [{"relative_path": "out.mp4", "metadata": {"path": "/internal/out.mp4"}}]
    result = service.public_project(p)
    assert "path" not in result["sources"]["body"]["audio_metadata"]
    assert "path" not in result["sources"]["body"]["video_metadata"]
    assert "path" not in result["outputs"][0]["metadata"]
    assert p["sources"]["body"]["audio_metadata"]["path"] == "/internal/audio.wav"
    job = {"kind": "render", "result": {"outputs": p["outputs"]}}
    assert "path" not in service.public_job(job, p)["result"]["outputs"][0]["metadata"]


def test_visual_review_requires_current_video_and_captures_plan(lab, tmp_path):
    client, app, pid = lab
    project = fixture_analyzed(lab, tmp_path)
    route = f"/api/v1/projects/{pid}/visual-review"
    body = {"source_id": "body", "base_revision": project["plan"]["revision"]}
    with app.state.service.store.tx() as db:
        p = app.state.service.require(db, pid)
        p["sources"]["body"]["video_state"] = "pending"
        app.state.service.store.save(db, pid, p)
    assert client.post(route, json=body).status_code == 409
    with app.state.service.store.tx() as db:
        p = app.state.service.require(db, pid)
        p["sources"]["body"]["video_state"] = "ready"
        p["sources"]["body"]["storage"]["original_verified"] = True
        app.state.service.store.save(db, pid, p)
    response = client.post(route, json=body)
    assert response.status_code == 202
    assert client.post(route, json=body).json() == response.json()
    with app.state.service.store.tx() as db:
        job = app.state.service.store.job(db, response.json()["job_id"])
    assert job["payload"]["base_plan"] == project["plan"]
    assert client.post(route, json={**body, "base_revision": 0}).status_code == 409


def test_config_limits_require_positive_values(tmp_path):
    for field in ("part_size", "max_incoming_uploads", "upload_timeout_seconds", "storage_quota_bytes"):
        with pytest.raises(ValidationError):
            Settings(storage_root=tmp_path, **{field: 0})
