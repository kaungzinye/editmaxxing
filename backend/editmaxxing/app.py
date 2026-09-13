"""Versioned API for the endpoint lab and production editor."""

import asyncio
import hashlib
import hmac
import os
import re
import shutil
import sqlite3
import tempfile
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from .config import Settings
from .models import (
    CompleteUpload,
    ProjectCreate,
    Rank,
    RenderRequest,
    SavePlan,
    SourceCreate,
    Templates,
    Timing,
    UploadCreate,
    VisualReview,
)
from .service import Problem, Service
from .worker import Worker


def create_app(settings=None):
    settings = settings or Settings()
    service = Service(settings)
    worker = Worker(service)

    @asynccontextmanager
    async def lifespan(app):
        if settings.worker_enabled:
            worker.start()
        yield
        worker.close()

    app = FastAPI(title="editmaxxing API", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    app.state.worker = worker
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Content-SHA256", "X-Timing-Manifest"],
        expose_headers=["Content-Length", "Content-Range", "Accept-Ranges"],
    )
    rates = defaultdict(deque)

    @app.middleware("http")
    async def rate_limit(request, call_next):
        if request.method in ("POST", "PUT"):
            # Railway runs one worker. The peer address comes from ASGI, with proxy trust set at launch.
            key = (
                request.client.host if request.client else "local",
                "projects" if request.url.path == "/api/v1/projects" else "write",
            )
            limit = 30 if key[1] == "projects" else 600
            bucket = rates[key]
            current = time.monotonic()
            while bucket and bucket[0] < current - 60:
                bucket.popleft()
            if len(bucket) >= limit:
                return JSONResponse(
                    Problem("rate_limit", "Request rate exceeds this minute’s allowance.", 429, True).body(),
                    429,
                    headers={"Retry-After": "60"},
                )
            bucket.append(current)
            if len(rates) > 10000:
                for stale in [k for k, v in rates.items() if not v or v[-1] < current - 60]:
                    del rates[stale]
        return await call_next(request)

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse(exc.body(), exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        messages = [".".join(str(x) for x in err["loc"]) + ": " + err["msg"] for err in exc.errors()]
        return JSONResponse(Problem("invalid_request", "; ".join(messages)).body(), 422)

    @app.exception_handler(ValueError)
    async def value_handler(request, exc):
        return JSONResponse(Problem("invalid_plan", str(exc)).body(), 422)

    def token(request):
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or len(auth) < 10:
            raise Problem("unauthorized", "Use the project bearer token.", 401)
        return auth[7:]

    def get_project(pid, request, allow_deleted=False):
        with service.store.tx() as db:
            return service.require(db, pid, token(request), allow_deleted=allow_deleted)

    def sha_header(request):
        value = request.headers.get("x-content-sha256", "")
        if not re.fullmatch("[a-f0-9]{64}", value):
            raise Problem(
                "checksum_required", "Send X-Content-SHA256 with the lowercase SHA-256 of these bytes."
            )
        return value

    async def receive(request, limit):
        length = request.headers.get("content-length")
        if length and (not re.fullmatch(r"[0-9]{1,20}", length) or int(length) > limit):
            raise Problem("byte_limit", "Upload exceeds its byte limit.", 413)
        folder = service.store.root / "incoming"
        folder.mkdir(exist_ok=True)
        reservation = service.reserve_incoming(int(length) if length else limit)
        path = None
        size = 0
        hasher = hashlib.sha256()
        try:
            fd, name = tempfile.mkstemp(dir=folder)
            path = Path(name)
            with os.fdopen(fd, "wb") as file:
                deadline = time.monotonic() + settings.upload_timeout_seconds
                async with asyncio.timeout(settings.upload_timeout_seconds):
                    async for chunk in request.stream():
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                        size += len(chunk)
                        service.write_incoming(reservation, file, chunk)
                        hasher.update(chunk)
                    if time.monotonic() >= deadline:
                        raise TimeoutError
                os.fsync(file.fileno())
            if size == 0:
                raise Problem("empty_upload", "Upload contains no bytes.")
            if length and size != int(length):
                raise Problem("byte_count", "Upload bytes must match Content-Length.")
            if hasher.hexdigest() != sha_header(request):
                raise Problem("checksum_mismatch", "Uploaded bytes do not match X-Content-SHA256.")
            return path, hasher.hexdigest(), size
        except TimeoutError:
            if path is not None:
                path.unlink(missing_ok=True)
            raise Problem(
                "upload_timeout", "Upload exceeded its time limit. Retry this upload.", 408, True
            ) from None
        except BaseException:
            if path is not None:
                path.unlink(missing_ok=True)
            raise
        finally:
            service.release_incoming(reservation)

    @app.get("/healthz")
    @app.get("/api/v1/healthz")
    def health():
        healthy = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
        healthy = healthy and (
            not settings.worker_enabled or bool(worker.thread and worker.thread.is_alive())
        )
        try:
            with service.store.tx() as db:
                db.execute("SELECT 1")
        except sqlite3.Error:
            healthy = False
        return JSONResponse(
            {
                "status": "ok" if healthy else "unavailable",
                "worker": (
                    "manual"
                    if not settings.worker_enabled
                    else "running"
                    if worker.thread and worker.thread.is_alive()
                    else "stopped"
                ),
                "provider_configured": bool(settings.openai_api_key),
                "editor_model": settings.editor_model,
                "storage_policy": "processing",
                "retention_hours": settings.retention_hours,
            },
            200 if healthy else 503,
        )

    @app.post("/api/v1/projects", status_code=201)
    def create_project(body: ProjectCreate):
        return service.create_project(body)

    @app.get("/api/v1/projects/{pid}")
    def project(pid: str, request: Request):
        return service.public_project(get_project(pid, request))

    @app.post("/api/v1/projects/{pid}/sources", status_code=201)
    def source(pid: str, body: SourceCreate, request: Request):
        return service.register(pid, token(request), body)

    @app.put("/api/v1/projects/{pid}/sources/{sid}/audio", status_code=202)
    async def audio(pid: str, sid: str, request: Request):
        p = get_project(pid, request)
        service.source(p, sid)
        try:
            timing = Timing.model_validate_json(request.headers.get("x-timing-manifest", ""))
        except ValidationError:
            raise Problem(
                "timing_required", "Send a valid X-Timing-Manifest JSON extraction mapping."
            ) from None
        sha_header(request)
        path, sha, size = await receive(request, settings.max_audio_bytes)
        try:
            return service.accept_audio(pid, token(request), sid, path, sha, size, timing)
        finally:
            path.unlink(missing_ok=True)

    @app.post("/api/v1/projects/{pid}/sources/{sid}/video/uploads", status_code=201)
    def create_upload(pid: str, sid: str, body: UploadCreate, request: Request):
        return service.create_upload(pid, token(request), sid, body)

    @app.get("/api/v1/projects/{pid}/sources/{sid}/video/uploads/{upload_id}")
    def get_upload(pid: str, sid: str, upload_id: str, request: Request):
        return service.upload(get_project(pid, request), sid, upload_id)

    @app.put("/api/v1/projects/{pid}/sources/{sid}/video/uploads/{upload_id}/parts/{part}")
    async def put_part(pid: str, sid: str, upload_id: str, part: int, request: Request):
        upload = service.upload(get_project(pid, request), sid, upload_id)
        if part < 0 or part * upload["part_size"] >= upload["size_bytes"]:
            raise Problem("part_number", "Part number is outside this upload.")
        sha_header(request)
        path, sha, size = await receive(request, upload["part_size"])
        try:
            return service.acknowledge_part(pid, token(request), sid, upload_id, part, path, sha, size)
        finally:
            path.unlink(missing_ok=True)

    @app.post("/api/v1/projects/{pid}/sources/{sid}/video/uploads/{upload_id}/complete", status_code=202)
    def complete(pid: str, sid: str, upload_id: str, body: CompleteUpload, request: Request):
        return service.complete_upload(pid, token(request), sid, upload_id, body)

    @app.post("/api/v1/projects/{pid}/analysis", status_code=202)
    def analysis(pid: str, request: Request, source_id: str | None = None):
        return service.retry_analysis(pid, token(request), source_id)

    @app.put("/api/v1/projects/{pid}/plan")
    def plan(pid: str, body: SavePlan, request: Request):
        return service.save_plan(pid, token(request), body)

    @app.post("/api/v1/projects/{pid}/rank", status_code=202)
    def rank(pid: str, body: Rank, request: Request):
        return service.rank(pid, token(request), body)

    @app.post("/api/v1/projects/{pid}/renders", status_code=202)
    def render(pid: str, body: RenderRequest, request: Request):
        return service.queue_render(pid, token(request), body)

    @app.post("/api/v1/projects/{pid}/visual-review", status_code=202)
    def visual_review(pid: str, body: VisualReview, request: Request):
        return service.visual_review(pid, token(request), body)

    @app.put("/api/v1/projects/{pid}/templates")
    def templates(pid: str, body: Templates, request: Request):
        return service.set_templates(pid, token(request), body)

    @app.put("/api/v1/projects/{pid}/hooks/{hook_id}")
    def update_hook(pid: str, hook_id: str, body: dict, request: Request):
        from .editing import clips_for_take

        if set(body) - {"proposed_text", "take_id"}:
            raise Problem("invalid_hook", "Hook edits accept proposed_text and take_id.")
        if not body or ("take_id" in body and not isinstance(body["take_id"], str)):
            raise Problem("invalid_hook", "Supply hook text or a recorded take ID.")
        with service.store.tx() as db:
            p = service.require(db, pid, token(request))
            hook = next((h for h in p["hooks"] if h["id"] == hook_id), None)
            if hook is None:
                raise Problem("hook_missing", "Hook does not exist.", 404)
            if "proposed_text" in body:
                if not isinstance(body["proposed_text"], str) or not 1 <= len(body["proposed_text"]) <= 2000:
                    raise Problem("invalid_hook", "Hook text needs 1 to 2000 characters.")
                hook["proposed_text"] = body["proposed_text"]
            if "take_id" in body:
                take = p["takes"].get(body["take_id"])
                if not take or not any(c["take_id"] == take["id"] for c in hook["candidates"]):
                    raise Problem("invalid_hook", "Choose one of this hook’s recorded candidates.")
                hook["take_id"] = take["id"]
                hook["clips"] = clips_for_take(take, p["words"], p["sources"])
            service.store.save(db, pid, p)
            service.store.enqueue(db, pid, "feedback", {"body_revision": p["plan"]["revision"]})
            return hook

    @app.post("/api/v1/projects/{pid}/sources/{sid}/fixture")
    def fixture(pid: str, sid: str, request: Request):
        if not settings.enable_fixtures:
            raise Problem("fixtures_disabled", "Fixture analysis requires ENABLE_FIXTURES=true.", 404)
        with service.store.tx() as db:
            p = service.require(db, pid, token(request))
            s = service.source(p, sid)
            if s.get("audio_sha256"):
                raise Problem("source_conflict", "Select fixture analysis before uploading audio.", 409)
            s["fixture"] = True
            service.store.save(db, pid, p)
        return {
            "source_id": sid,
            "fixture": True,
            "description": "Synthetic transcript and editorial choices; real media processing.",
        }

    @app.get("/api/v1/jobs/{jid}")
    def job(jid: str, request: Request):
        with service.store.tx() as db:
            record = service.store.job(db, jid)
            if record is None:
                raise Problem("job_missing", "Job does not exist.", 404)
            p = service.require(
                db, record["project_id"], token(request), allow_deleted=record["kind"] == "delete"
            )
            return service.public_job(record, p)

    @app.post("/api/v1/jobs/{jid}/cancel", status_code=202)
    def cancel(jid: str, request: Request):
        with service.store.tx() as db:
            record = service.store.job(db, jid)
            if record is None:
                raise Problem("job_missing", "Job does not exist.", 404)
            service.require(db, record["project_id"], token(request))
            if record["kind"] == "delete":
                raise Problem("deletion_pending", "Project deletion completes through its deletion job.", 409)
            if record["state"] in ("running", "queued"):
                record.update(
                    state="cancelled",
                    error={
                        "code": "cancelled",
                        "message": "The creator cancelled this job.",
                        "retryable": True,
                    },
                )
                service.store.put_job(db, record)
        return {"job_id": jid, "state": record["state"]}

    @app.delete("/api/v1/projects/{pid}", status_code=202)
    def delete(pid: str, request: Request):
        return service.delete_project(pid, token(request))

    @app.get("/api/v1/projects/{pid}/sources/{sid}/dependencies")
    def dependencies(pid: str, sid: str, request: Request):
        p = get_project(pid, request)
        service.source(p, sid)
        revisions = [
            int(k)
            for k, v in p.get("revisions", {}).items()
            if any(c["source_id"] == sid for c in v["clips"])
        ]
        return {
            "source_id": sid,
            "current_clip_ids": [c["id"] for c in p["plan"]["clips"] if c["source_id"] == sid],
            "saved_revisions": revisions,
            "hook_ids": [
                h["id"] for h in p["hooks"] if any(c.get("source_id") == sid for c in h["candidates"])
            ],
        }

    @app.delete("/api/v1/projects/{pid}/sources/{sid}", status_code=202)
    def delete_source(pid: str, sid: str, request: Request, confirm: bool = False):
        if not confirm:
            raise Problem(
                "confirmation_required",
                "Inspect source dependencies and submit confirm=true for explicit original deletion.",
                409,
            )
        with service.store.tx() as db:
            p = service.require(db, pid, token(request))
            s = service.source(p, sid)
            if any(c["source_id"] == sid for c in p["plan"]["clips"]):
                raise Problem(
                    "source_in_use",
                    "Remove this recording from the current edit before deleting its original.",
                    409,
                )
            if any(
                h.get("take_id") in p["takes"] and p["takes"][h["take_id"]].get("source_id") == sid
                for h in p["hooks"]
            ):
                raise Problem("source_in_use", "This recording supplies a selected hook take.", 409)
            active = db.execute(
                "SELECT data FROM jobs WHERE project_id=? AND state IN ('queued','running')", (pid,)
            ).fetchall()
            if active:
                raise Problem(
                    "work_pending", "Finish or cancel project work before deleting an original.", 409, True
                )
            s["deleted"] = True
            paths = [s.get(key) for key in ("raw_audio_path", "audio_path", "original_path", "editing_path")]
            s["audio_state"] = "deleted"
            s["video_state"] = "deleted"
            s["storage"]["original_verified"] = False
            service.store.save(db, pid, p)
            for raw in paths:
                if raw:
                    Path(raw).unlink(missing_ok=True)
            for folder in ("audio", "originals", "editing", "uploads"):
                shutil.rmtree(service.store.directory(pid) / folder / sid, ignore_errors=True)
        return {"source_id": sid, "deleted": True}

    @app.get("/api/v1/media/{pid}/{relative:path}")
    def media(pid: str, relative: str, expires: int, signature: str):
        expected = hmac.new(
            service.store.signing_key, f"{pid}/{relative}:{expires}".encode(), hashlib.sha256
        ).hexdigest()
        if (
            expires <= time.time()
            or not re.fullmatch(r"[a-f0-9]{64}", signature)
            or not hmac.compare_digest(signature, expected)
        ):
            raise Problem("media_expired", "Refresh the project for a valid media URL.", 403)
        with service.store.tx() as db:
            p = service.require(db, pid)
        root = service.store.directory(pid).resolve()
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise Problem("media_missing", "Media is unavailable.", 404)
        for s in p["sources"].values():
            if s.get("deleted") and s["source_id"] in path.parts:
                raise Problem("source_deleted", "The original recording is deleted.", 410)
        return FileResponse(path, media_type="video/mp4" if path.suffix == ".mp4" else None)

    return app


app = create_app()
