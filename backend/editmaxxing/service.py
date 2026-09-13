"""Durable project operations and revision ownership."""

import copy
import hashlib
import hmac
import json
import os
import secrets
import shutil
import time
from pathlib import Path

from .config import Settings
from .models import Plan
from .store import Store, digest, uid


class Problem(Exception):
    def __init__(self, code, message, status=422, retryable=False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable
        super().__init__(message)

    def body(self):
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}}


class Service:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.storage_root)
        self.incoming_uploads = {}

    def require(self, db, pid, token=None, allow_deleted=False):
        row, project = self.store.project(db, pid)
        if row is None or (token is not None and not hmac.compare_digest(row["token_hash"], digest(token))):
            raise Problem("unauthorized", "Project authorization is required.", 401)
        if not allow_deleted and (row["deleted"] or row["expires"] <= time.time()):
            raise Problem(
                "project_gone", "The project is deleted or its processing retention has expired.", 410
            )
        return project

    def source(self, project, sid):
        source = project["sources"].get(sid)
        if source is None or source.get("deleted"):
            raise Problem("source_missing", "Register this source before uploading media.", 404)
        return source

    def check_revision(self, project, revision):
        if project["plan"]["revision"] != revision:
            raise Problem(
                "revision_conflict",
                f"Saved plan revision is {project['plan']['revision']}; review it before applying this edit.",
                409,
            )

    def create_project(self, request):
        pid, token = uid("p"), secrets.token_urlsafe(32)
        expires = time.time() + self.settings.retention_hours * 3600
        project = {
            "project_id": pid,
            "name": request.name,
            "created_at": time.time(),
            "expires_at": expires,
            "sources": {},
            "words": [],
            "analysis": {},
            "boundary_reviews": {},
            "takes": {},
            "hooks": [],
            "titles": [],
            "recommendations": {"status": "pending", "short_set_reason": ""},
            "pair_assessments": {},
            "render_requests": {},
            "templates": [],
            "proposals": [],
            "feedback": [],
            "outputs": [],
            "revisions": {},
            "plan": Plan(target_duration_ms=request.target_duration_ms).model_dump(),
        }
        with self.store.tx() as db:
            self.check_quota(0)
            db.execute(
                "INSERT INTO projects VALUES(?,?,?,0,?)", (pid, digest(token), expires, json.dumps(project))
            )
        return {"project_id": pid, "project_token": token, "expires_at": expires}

    def check_quota(self, additional):
        with self.store.lock:
            used = 0
            for path in self.store.root.rglob("*"):
                try:
                    if path.is_file():
                        used += path.stat().st_size
                except FileNotFoundError:
                    continue
            reserved = sum(self.incoming_uploads.values())
            if used + reserved + additional > self.settings.storage_quota_bytes:
                raise Problem(
                    "storage_quota", "Processing storage is full. Retry after project cleanup.", 507, True
                )
            if shutil.disk_usage(self.store.root).free < reserved + additional + 64 * 1024**2:
                raise Problem("disk_full", "Processing storage has insufficient free space.", 507, True)

    def reserve_incoming(self, size):
        with self.store.lock:
            if len(self.incoming_uploads) >= self.settings.max_incoming_uploads:
                raise Problem("uploads_busy", "Upload capacity is busy. Retry this upload.", 429, True)
            self.check_quota(size)
            reservation = uid("incoming")
            self.incoming_uploads[reservation] = size
            return reservation

    def write_incoming(self, reservation, file, chunk):
        with self.store.lock:
            if len(chunk) > self.incoming_uploads[reservation]:
                raise Problem("byte_limit", "Upload exceeds its declared byte limit.", 413)
            file.write(chunk)
            file.flush()
            self.incoming_uploads[reservation] -= len(chunk)

    def release_incoming(self, reservation):
        with self.store.lock:
            self.incoming_uploads.pop(reservation, None)

    def register(self, pid, token, request):
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            existing = p["sources"].get(request.source_id)
            registered = request.model_dump()
            if existing:
                if existing["registration"] == registered and not existing.get("deleted"):
                    return {"source_id": request.source_id}
                raise Problem(
                    "source_conflict",
                    "Source IDs identify immutable recordings. Register a new source ID.",
                    409,
                )
            if len(p["sources"]) >= 20:
                raise Problem("source_limit", "A project supports up to twenty source recordings.", 413)
            if request.role == "hooks" and request.duration_ms > self.settings.max_hook_duration_ms:
                raise Problem("duration_limit", "Hook recording exceeds the configured duration limit.")
            if (request.role == "hooks") != bool(request.hook_scripts):
                raise Problem(
                    "invalid_hooks", "Hook recordings require scripts; body recordings use no scripts."
                )
            if request.timing.duration_ms != request.duration_ms:
                raise Problem(
                    "timing_mismatch", "Source timing duration must equal canonical source duration."
                )
            hook_ids = {h["id"] for h in p["hooks"]}
            if len({s.hook_id for s in request.hook_scripts}) != len(request.hook_scripts):
                raise Problem("invalid_hooks", "Hook scripts must identify distinct hooks.")
            if any(s.hook_id not in hook_ids for s in request.hook_scripts):
                raise Problem("invalid_hooks", "Hook scripts must reference this project’s hook suggestions.")
            for script in request.hook_scripts:
                hook = next(h for h in p["hooks"] if h["id"] == script.hook_id)
                if (
                    script.capture_revision != hook["capture_revision"]
                    or script.text != hook["proposed_text"]
                ):
                    raise Problem(
                        "capture_stale", "Refresh capture instructions before registering this take.", 409
                    )
                if hook["action_enabled"] != (script.action_start_ms is not None):
                    raise Problem("invalid_action", "Confirm an action start for an enabled physical hook.")
                if script.action_start_ms is not None and script.action_start_ms >= request.duration_ms:
                    raise Problem("invalid_action", "Action start must be within the recording.")
            p["sources"][request.source_id] = dict(
                **registered,
                registration=registered,
                uploads={},
                audio_state="pending",
                video_state="pending",
                fixture=False,
                storage={
                    "copy_kind": "processing",
                    "expires_at": p["expires_at"],
                    "restore_capable": False,
                    "original_verified": False,
                },
            )
            self.store.save(db, pid, p)
        return {"source_id": request.source_id}

    def create_upload(self, pid, token, sid, request):
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            source = self.source(p, sid)
            if request.size_bytes > self.settings.max_video_bytes:
                raise Problem("byte_limit", "Original exceeds the configured byte limit.", 413)
            if request.sha256 != source["fingerprint"]:
                raise Problem(
                    "fingerprint_mismatch",
                    "The original SHA-256 must equal the registered source fingerprint.",
                )
            for upload in source["uploads"].values():
                if (
                    upload["sha256"] == request.sha256
                    and upload["size_bytes"] == request.size_bytes
                    and upload["expires_at"] > time.time()
                ):
                    return copy.deepcopy(upload)
            self.check_quota(request.size_bytes * 2)
            upload = {
                "upload_id": uid("up"),
                "size_bytes": request.size_bytes,
                "sha256": request.sha256,
                "part_size": self.settings.part_size,
                "parts": [],
                "state": "uploading",
                "expires_at": min(p["expires_at"], time.time() + self.settings.upload_hours * 3600),
            }
            source["uploads"][upload["upload_id"]] = upload
            self.store.save(db, pid, p)
            return copy.deepcopy(upload)

    def upload(self, p, sid, upload_id):
        source = self.source(p, sid)
        upload = source["uploads"].get(upload_id)
        if upload is None:
            raise Problem("upload_missing", "Upload session does not exist.", 404)
        if upload["expires_at"] <= time.time():
            raise Problem(
                "upload_expired", "Upload resume window has expired. Create another upload session.", 410
            )
        return upload

    def part_path(self, pid, sid, upload_id, part):
        return self.store.directory(pid) / "uploads" / sid / upload_id / f"{part}.part"

    def acknowledge_part(self, pid, token, sid, upload_id, part, path, sha, size):
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            upload = self.upload(p, sid, upload_id)
            existing = next((x for x in upload["parts"] if x["part"] == part), None)
            if existing:
                if existing["sha256"] == sha and existing["size_bytes"] == size:
                    return existing
                raise Problem("part_conflict", "This part number contains different bytes.", 409)
            if upload["state"] != "uploading":
                raise Problem("upload_closed", "This upload is already finalizing.", 409)
            expected = min(upload["part_size"], upload["size_bytes"] - part * upload["part_size"])
            if expected <= 0 or size != expected:
                raise Problem("part_size", "Part size or part number does not match the upload manifest.")
            destination = self.part_path(pid, sid, upload_id, part)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, destination)
            acknowledgement = {"part": part, "sha256": sha, "size_bytes": size}
            upload["parts"].append(acknowledgement)
            upload["parts"].sort(key=lambda x: x["part"])
            self.store.save(db, pid, p)
            return acknowledgement

    def complete_upload(self, pid, token, sid, upload_id, request):
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            upload = self.upload(p, sid, upload_id)
            count = (upload["size_bytes"] + upload["part_size"] - 1) // upload["part_size"]
            expected = [{"part": v["part"], "sha256": v["sha256"]} for v in upload["parts"]]
            if len(expected) != count or expected != [v.model_dump() for v in request.parts]:
                raise Problem("parts_mismatch", "Submit all acknowledged parts in ascending order.")
            if upload.get("job_id"):
                job = self.store.job(db, upload["job_id"])
                if job and job["state"] in ("queued", "running", "succeeded"):
                    return {"job_id": job["id"]}
            upload["state"] = "verifying"
            job = self.store.enqueue(db, pid, "normalize", {"source_id": sid, "upload_id": upload_id})
            upload["job_id"] = job["id"]
            self.source(p, sid)["video_state"] = "verifying"
            self.store.save(db, pid, p)
            return {"job_id": job["id"]}

    def accept_audio(self, pid, token, sid, path, sha, size, timing):
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            source = self.source(p, sid)
            if source.get("audio_sha256"):
                if source["audio_sha256"] != sha or source["audio_timing"] != timing.model_dump():
                    raise Problem(
                        "audio_conflict", "This source has different immutable audio or timing.", 409
                    )
            else:
                destination = self.store.directory(pid) / "audio" / sid / "uploaded.audio"
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, destination)
                source.update(
                    audio_sha256=sha,
                    audio_size_bytes=size,
                    raw_audio_path=str(destination),
                    audio_timing=timing.model_dump(),
                    audio_state="uploaded",
                )
            active = self.active_job(db, pid, "analyze", sid)
            if active:
                return {"job_id": active["id"]}
            job = self.store.enqueue(
                db,
                pid,
                "analyze",
                {
                    "source_id": sid,
                    "base_revision": p["plan"]["revision"],
                    "base_plan": copy.deepcopy(p["plan"]),
                },
            )
            self.store.save(db, pid, p)
            return {"job_id": job["id"]}

    def active_job(self, db, pid, kind, sid=None):
        rows = db.execute(
            "SELECT data FROM jobs WHERE project_id=? AND state IN ('queued','running')", (pid,)
        )
        for row in rows:
            job = json.loads(row[0])
            if job["kind"] == kind and (sid is None or job["payload"].get("source_id") == sid):
                return job

    def retry_analysis(self, pid, token, sid=None):
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            candidates = [
                s
                for s in p["sources"].values()
                if s.get("raw_audio_path") and not s.get("deleted") and (sid is None or s["source_id"] == sid)
            ]
            if not candidates:
                raise Problem("audio_pending", "Upload source audio before analysis.", 409, True)
            jobs = []
            for source in candidates:
                job = self.active_job(db, pid, "analyze", source["source_id"]) or self.store.enqueue(
                    db,
                    pid,
                    "analyze",
                    {
                        "source_id": source["source_id"],
                        "base_revision": p["plan"]["revision"],
                        "base_plan": copy.deepcopy(p["plan"]),
                    },
                )
                jobs.append(job["id"])
            return {"job_id": jobs[0], "job_ids": jobs}

    def save_plan(self, pid, token, request):
        from .editing import canonicalize_plan

        with self.store.tx() as db:
            p = self.require(db, pid, token)
            self.check_revision(p, request.base_revision)
            if request.proposal_id:
                proposal = next((x for x in p["proposals"] if x["id"] == request.proposal_id), None)
                if proposal is None or proposal["base_revision"] != request.base_revision:
                    raise Problem(
                        "proposal_conflict", "Review a proposal against its captured base revision.", 409
                    )
            plan = request.plan.model_dump()
            self.validate_selection(p, plan)
            plan = canonicalize_plan(plan, p["words"], p["sources"], p["takes"])
            plan["revision"] = request.base_revision + 1
            p["revisions"][str(p["plan"]["revision"])] = p["plan"]
            p["plan"] = plan
            for f in p["feedback"]:
                f["stale"] = f["body_revision"] != plan["revision"]
            self.store.save(db, pid, p)
            if p["hooks"]:
                self.store.enqueue(db, pid, "feedback", {"body_revision": plan["revision"]})
            return plan

    def validate_selection(self, p, plan):
        hook_id = plan["selected_hook_id"]
        hook_clips = [c for c in plan["clips"] if c["role"] == "hook"]
        if hook_id is None:
            if hook_clips or plan["selected_visual_title_id"] is not None:
                raise Problem("invalid_selection", "Hook clips and titles require a selected spoken hook.")
            return
        hook = next((h for h in p["hooks"] if h["id"] == hook_id), None)
        if hook is None:
            raise Problem("invalid_selection", "Selected hook belongs to another project.")
        if plan["selected_visual_title_id"] and not any(
            t["id"] == plan["selected_visual_title_id"] for t in p["titles"]
        ):
            raise Problem("invalid_selection", "Visual title must belong to this project.")
        if hook_clips and (
            not hook.get("take_id") or any(c["take_id"] != hook["take_id"] for c in hook_clips)
        ):
            raise Problem("invalid_selection", "Leading clips must reference the selected hook take.")
        if hook_clips and plan["clips"][: len(hook_clips)] != hook_clips:
            raise Problem("invalid_selection", "Spoken hook clips must lead the shared body.")

    def rank(self, pid, token, request):
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            self.check_revision(p, request.base_revision)
            if not p["analysis"]:
                raise Problem("analysis_pending", "Source analysis is required before ranking.", 409, True)
            if request.selected_hook_id and not any(h["id"] == request.selected_hook_id for h in p["hooks"]):
                raise Problem("invalid_selection", "Selected hook does not exist.")
            job = self.store.enqueue(
                db, pid, "rank", {**request.model_dump(), "base_plan": copy.deepcopy(p["plan"])}
            )
            return {"job_id": job["id"]}

    def queue_render(self, pid, token, request):
        from .editing import assemble_combination
        from .recommendations import assess_pairs, check_capture

        def existing_request(project):
            if request.request_id and request.request_id in project["render_requests"]:
                record = project["render_requests"][request.request_id]
                if record["request"] != request.model_dump():
                    raise Problem(
                        "request_conflict", "A render request ID identifies one immutable request.", 409
                    )
                return record["response"]
            return None

        with self.store.tx() as db:
            p = self.require(db, pid, token)
            existing = existing_request(p)
            if existing:
                return existing
        checked = assess_pairs(self, pid, token, request)
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            existing = existing_request(p)
            if existing:
                return existing
            self.check_revision(p, request.plan_revision)
            if len({c.id for c in request.combinations}) != len(request.combinations):
                raise Problem("duplicate_combination", "Combination IDs must be unique.")
            outputs = []
            for combination in request.combinations:
                hook = next((h for h in p["hooks"] if h["id"] == combination.hook_id), None)
                if combination.hook_id and (hook is None or hook.get("take_id") is None):
                    raise Problem(
                        "hook_pending", "Select a matched recorded hook before rendering.", 409, True
                    )
                title = next(
                    (t for t in p["titles"] if t["id"] == combination.visual_title_id),
                    None,
                )
                if hook:
                    check_capture(p, hook)
                if combination.id in checked and checked[combination.id] != (
                    hook["text_revision"] if hook else None,
                    title["text_revision"] if title else None,
                ):
                    raise Problem(
                        "revision_conflict",
                        "Recommendations changed during pair validation. Retry rendering.",
                        409,
                    )
                if combination.visual_title_id and title is None:
                    raise Problem("invalid_selection", "Visual title must belong to this project.")
                if combination.use_title and title and title["missing_slots"] and combination.overlay is None:
                    saved_override = (
                        p["plan"]["selected_visual_title_id"] == title["id"]
                        and p["plan"]["hook_overlay"] is not None
                    )
                    if not saved_override:
                        raise Problem(
                            "title_incomplete",
                            "Fill the visual title’s missing slots or supply a creator overlay.",
                        )
                plan = assemble_combination(
                    p["plan"], hook, title, combination.model_dump(), p["words"], p["sources"], p["takes"]
                )
                if not plan["clips"]:
                    raise Problem("empty_plan", "Add source clips before rendering.")
                for clip in plan["clips"]:
                    source = self.source(p, clip["source_id"])
                    if source["video_state"] != "ready" or not source["storage"]["original_verified"]:
                        raise Problem(
                            "media_pending",
                            f"Source {clip['source_id']} needs verified, normalized video.",
                            409,
                            True,
                        )
                outputs.append(
                    {
                        "combination_id": combination.id,
                        "plan": plan,
                        "hook_take_id": (hook or {}).get("take_id"),
                        "hook_revision": (hook or {}).get("capture_revision"),
                        "title_revision": (title or {}).get("text_revision"),
                        "input_hash": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
                    }
                )
            required_sources = {clip["source_id"] for output in outputs for clip in output["plan"]["clips"]}
            snapshot = {
                "plan_revision": request.plan_revision,
                "kind": request.kind,
                "combinations": outputs,
                "sources": {sid: copy.deepcopy(p["sources"][sid]) for sid in required_sources},
            }
            job = self.store.enqueue(db, pid, "render", snapshot)
            response = {
                "job_id": job["id"],
                "inputs": [{k: v for k, v in output.items() if k != "plan"} for output in outputs],
            }
            if request.request_id:
                p["render_requests"][request.request_id] = {
                    "request": request.model_dump(),
                    "response": response,
                }
                self.store.save(db, pid, p)
            return response

    def visual_review(self, pid, token, request):
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            self.check_revision(p, request.base_revision)
            source = self.source(p, request.source_id)
            if source["role"] != "body":
                raise Problem("invalid_source", "Visual review requires a body recording.")
            if source["video_state"] != "ready" or not source["storage"]["original_verified"]:
                raise Problem("media_pending", "Visual review requires verified normalized video.", 409, True)
            if not any(word["source_id"] == request.source_id for word in p["words"]):
                raise Problem("analysis_pending", "Visual review requires the source transcript.", 409, True)
            active = self.active_job(db, pid, "visual", request.source_id)
            if active and active["payload"]["base_revision"] == request.base_revision:
                return {"job_id": active["id"]}
            job = self.store.enqueue(
                db,
                pid,
                "visual",
                {
                    "source_id": request.source_id,
                    "base_revision": request.base_revision,
                    "base_plan": copy.deepcopy(p["plan"]),
                },
            )
            return {"job_id": job["id"]}

    def signed_url(self, pid, relative, expires_at):
        expires = int(min(expires_at, time.time() + self.settings.signed_url_seconds))
        value = f"{pid}/{relative}:{expires}"
        sig = hmac.new(self.store.signing_key, value.encode(), hashlib.sha256).hexdigest()
        return {
            "url": f"{self.settings.public_base_url.rstrip('/')}/api/v1/media/{pid}/{relative}?expires={expires}&signature={sig}",
            "expires_at": expires,
        }

    def public_project(self, p):
        result = copy.deepcopy(p)
        result.pop("revisions", None)
        result.pop("render_requests", None)
        result.pop("pair_assessments", None)
        for s in result["sources"].values():
            for name in ("audio_metadata", "video_metadata"):
                if isinstance(s.get(name), dict):
                    s[name].pop("path", None)
            for name in ("raw_audio_path", "audio_path", "editing_path", "original_path"):
                path = s.pop(name, None)
                if path and Path(path).is_file():
                    rel = str(Path(path).relative_to(self.store.directory(p["project_id"])))
                    s[name.replace("_path", "_media")] = self.signed_url(
                        p["project_id"], rel, p["expires_at"]
                    )
            s.pop("registration", None)
        for output in result["outputs"]:
            output.get("metadata", {}).pop("path", None)
            relative = output.pop("relative_path")
            output.update(self.signed_url(p["project_id"], relative, p["expires_at"]))
        return result

    def public_job(self, job, p):
        result = copy.deepcopy(job)
        result.pop("payload", None)
        if job["kind"] == "render" and job["result"]:
            for output in result["result"].get("outputs", []):
                output.get("metadata", {}).pop("path", None)
                relative = output.pop("relative_path")
                output.update(self.signed_url(p["project_id"], relative, p["expires_at"]))
        return result

    def delete_project(self, pid, token):
        with self.store.tx() as db:
            self.require(db, pid, token, allow_deleted=True)
            active = self.active_job(db, pid, "delete")
            if active:
                return {"job_id": active["id"]}
            db.execute("UPDATE projects SET deleted=1 WHERE id=?", (pid,))
            for row in db.execute(
                "SELECT data FROM jobs WHERE project_id=? AND state IN ('running','queued')", (pid,)
            ).fetchall():
                job = json.loads(row[0])
                job.update(
                    state="cancelled",
                    error={
                        "code": "project_deleted",
                        "message": "Project deletion cancels this work.",
                        "retryable": False,
                    },
                )
                self.store.put_job(db, job)
            job = self.store.enqueue(db, pid, "delete", {})
            return {"job_id": job["id"]}

    def set_templates(self, pid, token, request):
        from string import Formatter

        ids = set()
        for template in request.templates:
            if template.id in ids or len(set(template.slots)) != len(template.slots):
                raise Problem("invalid_template", "Template IDs and slot names must be unique.")
            ids.add(template.id)
            try:
                parsed = list(Formatter().parse(template.pattern))
            except ValueError:
                raise Problem("invalid_template", "Template braces must contain named slots.") from None
            names = {name for _, name, _, _ in parsed if name is not None}
            if names != set(template.slots) or any(spec or conv for _, _, spec, conv in parsed):
                raise Problem(
                    "invalid_template", "Pattern slots must match declared names and use plain substitutions."
                )
        with self.store.tx() as db:
            p = self.require(db, pid, token)
            templates = [t.model_dump() for t in request.templates]
            if p["templates"] == templates:
                return {"templates": templates}
            p["templates"] = templates
            if p["recommendations"]["status"] == "ready":
                raise Problem(
                    "recommendations_ready", "Set templates before body recommendations publish.", 409
                )
            self.store.save(db, pid, p)
            jobs = []
            for source in p["sources"].values():
                if source["role"] != "body" or source.get("deleted") or not source.get("raw_audio_path"):
                    continue
                active = self.active_job(db, pid, "analyze", source["source_id"])
                if active and active["state"] == "queued":
                    jobs.append(active["id"])
                    continue
                job = self.store.enqueue(
                    db,
                    pid,
                    "analyze",
                    {
                        "source_id": source["source_id"],
                        "base_revision": p["plan"]["revision"],
                        "base_plan": copy.deepcopy(p["plan"]),
                    },
                )
                jobs.append(job["id"])
        return {"templates": templates, "job_ids": jobs}
