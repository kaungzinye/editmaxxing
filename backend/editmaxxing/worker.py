"""One durable queue consumer per storage volume."""

import copy
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .hook_policy import policy_version
from .models import BodyEditorial, HookScript, Template, Timing, Word
from .provider import PROMPT_VERSION, complete_editorial, get_provider
from .service import Problem
from .store import uid

log = logging.getLogger(__name__)


class WaitingForVideo(Exception):
    pass


class Worker:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.stop = threading.Event()
        self.thread = None
        self.last_tick = time.time()

    def start(self):
        with self.store.tx() as db:
            for row in db.execute("SELECT data FROM jobs WHERE state='running'").fetchall():
                job = json.loads(row[0])
                job.update(
                    state="failed",
                    error={
                        "code": "worker_restarted",
                        "message": "Processing was interrupted. Retry this operation.",
                        "retryable": True,
                    },
                )
                self.store.put_job(db, job)
        self.thread = threading.Thread(target=self.loop, name="editmaxxing-worker", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)

    def loop(self):
        last_cleanup = 0
        while not self.stop.is_set():
            self.last_tick = time.time()
            try:
                if time.time() - last_cleanup > 60:
                    self.cleanup()
                    last_cleanup = time.time()
                if not self.run_once():
                    self.stop.wait(0.25)
            except Exception:
                log.exception("Queue iteration failed")
                self.stop.wait(1)

    def cleanup(self):
        expired = []
        with self.store.tx() as db:
            for row in db.execute(
                "SELECT id FROM projects WHERE deleted=0 AND expires<=?", (time.time(),)
            ).fetchall():
                pid = row[0]
                db.execute("UPDATE projects SET deleted=1 WHERE id=?", (pid,))
                self.store.enqueue(db, pid, "delete", {})
            for row in db.execute("SELECT id,data FROM projects WHERE deleted=0").fetchall():
                p = json.loads(row["data"])
                changed = False
                for source in p["sources"].values():
                    for up in source["uploads"].values():
                        if up["expires_at"] <= time.time() and up["state"] == "uploading":
                            up["state"] = "expired"
                            changed = True
                            expired.append(
                                self.store.directory(p["project_id"])
                                / "uploads"
                                / source["source_id"]
                                / up["upload_id"]
                            )
                if changed:
                    self.store.save(db, p["project_id"], p)
        for path in expired:
            shutil.rmtree(path, ignore_errors=True)

    def checkpoint(self, job, stage=None, progress=None):
        with self.store.tx() as db:
            self.publishing_project(db, job)
            current = self.store.job(db, job["id"])
            if stage:
                current["stage"] = stage
            if progress is not None:
                current["progress"] = progress
            self.store.put_job(db, current)

    def publishing_project(self, db, job):
        """Check cancellation and project retention within the transaction that publishes data."""
        current = self.store.job(db, job["id"])
        if current is None or current["state"] != "running" or self.stop.is_set():
            raise Problem("cancelled", "This job is cancelled.", 409)
        if job["kind"] == "delete":
            return None
        return self.service.require(db, job["project_id"])

    def project(self, job):
        with self.store.tx() as db:
            return copy.deepcopy(self.publishing_project(db, job))

    def run_once(self):
        with self.store.tx() as db:
            row = db.execute(
                "SELECT data FROM jobs WHERE state='queued' AND json_extract(data, '$.stage') != 'waiting_video' ORDER BY created LIMIT 1"
            ).fetchone()
            if row is None:
                return False
            job = json.loads(row[0])
            job["state"] = "running"
            self.store.put_job(db, job)
        try:
            self.checkpoint(job)
            result = getattr(self, "do_" + job["kind"])(job)
            with self.store.tx() as db:
                self.publishing_project(db, job)
                current = self.store.job(db, job["id"])
                if current["state"] == "running":
                    current.update(state="succeeded", progress=1, result=result, error=None)
                    self.store.put_job(db, current)
        except WaitingForVideo:
            with self.store.tx() as db:
                self.publishing_project(db, job)
                current = self.store.job(db, job["id"])
                current.update(state="queued", stage="waiting_video", progress=0.55)
                self.store.put_job(db, current)
        except Exception as exc:  # noqa: BLE001 - each job records its failure and releases the queue
            code = getattr(exc, "code", "processing_failed")
            message = getattr(exc, "message", None)
            if message is None and isinstance(exc, ValueError):
                message = str(exc)
            if message is None:
                message = "Processing failed. Check media and retry."
                log.error("Job %s failed with %s", job["id"], type(exc).__name__)
            with self.store.tx() as db:
                current = self.store.job(db, job["id"])
                if current and current["state"] == "running":
                    current.update(
                        state="failed",
                        error={
                            "code": code,
                            "message": message,
                            "retryable": getattr(exc, "retryable", True),
                        },
                    )
                    self.store.put_job(db, current)
                    row, p = self.store.project(db, job["project_id"])
                    sid = job["payload"].get("source_id")
                    if (
                        p
                        and not row["deleted"]
                        and row["expires"] > time.time()
                        and sid in p.get("sources", {})
                    ):
                        source = p["sources"][sid]
                        if job["kind"] == "normalize":
                            source["video_state"] = "failed"
                        elif job["kind"] == "analyze":
                            source["analysis_error"] = current["error"]
                        self.store.save(db, job["project_id"], p)
        return True

    def do_normalize(self, job):
        from .media import normalize_video

        p = self.project(job)
        sid = job["payload"]["source_id"]
        source = self.service.source(p, sid)
        up = self.service.upload(p, sid, job["payload"]["upload_id"])
        original_dir = self.store.directory(p["project_id"]) / "originals" / sid
        original_dir.mkdir(parents=True, exist_ok=True)
        original = original_dir / "original.mp4"
        assembled = original_dir / f"{job['id']}.tmp"
        editing = self.store.directory(p["project_id"]) / "editing" / sid / f"{job['id']}.mp4"
        published = False
        try:
            if original.is_file():
                hasher, size = hashlib.sha256(), 0
                with original.open("rb") as data:
                    while chunk := data.read(1024 * 1024):
                        hasher.update(chunk)
                        size += len(chunk)
                if size != up["size_bytes"] or hasher.hexdigest() != up["sha256"]:
                    raise Problem(
                        "source_immutable", "The retained original differs from this upload manifest.", 409
                    )
            else:
                hasher, size = hashlib.sha256(), 0
                with assembled.open("wb") as target:
                    for part in up["parts"]:
                        part_hash = hashlib.sha256()
                        with self.service.part_path(p["project_id"], sid, up["upload_id"], part["part"]).open(
                            "rb"
                        ) as data:
                            while chunk := data.read(1024 * 1024):
                                target.write(chunk)
                                hasher.update(chunk)
                                part_hash.update(chunk)
                                size += len(chunk)
                        if part_hash.hexdigest() != part["sha256"]:
                            raise Problem(
                                "checksum_mismatch",
                                "An acknowledged upload part failed checksum verification.",
                            )
                        self.checkpoint(job, "normalize", 0.1 * size / up["size_bytes"])
                    target.flush()
                    os.fsync(target.fileno())
                if size != up["size_bytes"] or hasher.hexdigest() != up["sha256"]:
                    raise Problem(
                        "checksum_mismatch", "Whole original size or checksum does not match its manifest."
                    )
            with self.store.tx() as db:
                live = self.publishing_project(db, job)
                s = self.service.source(live, sid)
                if not original.is_file():
                    os.replace(assembled, original)
                    original.chmod(0o400)
                s["original_path"] = str(original)
                if not s["storage"].get("original_verified"):
                    s["storage"].update(
                        original_verified=True,
                        sha256=hasher.hexdigest(),
                        size_bytes=size,
                        verified_at=time.time(),
                    )
                s["video_state"] = "normalizing"
                self.store.save(db, p["project_id"], live)
            editing.parent.mkdir(parents=True, exist_ok=True)
            metadata = normalize_video(original, editing, source["timing"], source["duration_ms"])
            with self.store.tx() as db:
                live = self.publishing_project(db, job)
                s = self.service.source(live, sid)
                s.update(
                    editing_path=str(editing),
                    video_state="ready",
                    video_metadata=metadata,
                    editing_timing={
                        "media_origin_ms": 0,
                        "encoder_delay_ms": 0,
                        "duration_ms": source["duration_ms"],
                        "sample_rate": 48000,
                        "extractor": "ffmpeg",
                    },
                )
                s["uploads"][up["upload_id"]]["state"] = "complete"
                for row in db.execute(
                    "SELECT data FROM jobs WHERE project_id=? AND state='queued'", (p["project_id"],)
                ).fetchall():
                    waiting = json.loads(row[0])
                    if waiting["stage"] == "waiting_video" and waiting["payload"].get("source_id") == sid:
                        waiting["stage"] = "analyze"
                        self.store.put_job(db, waiting)
                self.store.save(db, p["project_id"], live)
                published = True
            shutil.rmtree(
                self.service.part_path(p["project_id"], sid, up["upload_id"], 0).parent, ignore_errors=True
            )
            return {"source_id": sid, "video_state": "ready", "storage": s["storage"]}
        finally:
            assembled.unlink(missing_ok=True)
            if not published:
                editing.unlink(missing_ok=True)

    def do_analyze(self, job):
        from .editing import canonicalize_plan, clips_for_take, compile_draft
        from .media import audio_metrics, normalize_audio

        p = self.project(job)
        base_plan = copy.deepcopy(job["payload"]["base_plan"])
        sid = job["payload"]["source_id"]
        source = self.service.source(p, sid)
        provider = get_provider(self.service.settings, fixture=source.get("fixture", False))
        audio = self.store.directory(p["project_id"]) / "audio" / sid / "canonical.wav"
        if not source.get("audio_path"):
            metadata = normalize_audio(
                Path(source["raw_audio_path"]), audio, source["audio_timing"], source["duration_ms"]
            )
            self.checkpoint(job, "transcribe", 0.15)
            metrics = audio_metrics(audio)
            with self.store.tx() as db:
                live = self.publishing_project(db, job)
                s = self.service.source(live, sid)
                s.update(audio_path=str(audio), audio_state="ready", audio_metadata=metadata, metrics=metrics)
                self.store.save(db, p["project_id"], live)
            source.update(audio_path=str(audio), metrics=metrics)
        if not source.get("words"):
            # Provider upload uses compact audio, with decoded origin at canonical zero.
            import subprocess

            compact = audio.with_suffix(".m4a")
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(audio),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "64k",
                    str(compact),
                ],
                check=True,
                timeout=180,
            )
            words = provider.transcribe(
                compact,
                sid,
                Timing(duration_ms=source["duration_ms"]),
                source["duration_ms"],
                role=source["role"],
                hook_scripts=[HookScript(**x) for x in source["hook_scripts"]],
            )
            self.checkpoint(job, "analyze", 0.4)
            with self.store.tx() as db:
                live = self.publishing_project(db, job)
                s = self.service.source(live, sid)
                s["words"] = [w.model_dump() for w in words]
                live["words"] = [w for w in live["words"] if w["source_id"] != sid] + s["words"]
                self.store.save(db, p["project_id"], live)
            source["words"] = [w.model_dump() for w in words]
        words = [Word(**w) for w in source["words"]]
        p = self.project(job)
        reserved_duration_ms = sum(
            c["source_end_ms"] - c["source_start_ms"] for c in base_plan["clips"] if c["role"] == "hook"
        )
        key = hashlib.sha256(
            json.dumps(
                [
                    source["fingerprint"],
                    source["audio_sha256"],
                    source["audio_timing"],
                    p["templates"],
                    self.service.settings.editor_model,
                    PROMPT_VERSION,
                    policy_version() if source["role"] == "body" else None,
                    base_plan["target_duration_ms"] if source["role"] == "body" else None,
                    base_plan["dead_space"] if source["role"] == "body" else None,
                    reserved_duration_ms if source["role"] == "body" else None,
                    120000,
                    source["role"],
                    source["hook_scripts"],
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        stored = p["analysis"].get(key)
        if source["role"] == "hooks":
            matches = (
                stored["matches"]
                if stored
                else provider.match_hooks(
                    words, [HookScript(**x) for x in source["hook_scripts"]]
                ).model_dump()
            )
            self.cache_editorial(
                job,
                key,
                {
                    "source_id": sid,
                    "version": PROMPT_VERSION,
                    "matches": matches,
                    "fixture": source.get("fixture", False),
                },
            )
            self.require_review_video(job, sid)
            candidates = {}
            for match in matches["matches"]:
                if match["word_ids"]:
                    take_id = f"t_{hashlib.sha256((sid + match['hook_id'] + json.dumps(match['word_ids'])).encode()).hexdigest()[:20]}"
                    take = {
                        "id": take_id,
                        "line_id": match["hook_id"],
                        "word_ids": match["word_ids"],
                        "role": "hook",
                        "reason": match["reason"],
                    }
                    candidates[match["hook_id"]] = clips_for_take(
                        take, p["words"], p["sources"], {sid: source.get("metrics", {}).get("silences", [])}
                    )
            reviewed = self.review_cuts(job, source, [c for clips in candidates.values() for c in clips])
            self.checkpoint(job, "plan", 0.85)
            with self.store.tx() as db:
                live = self.publishing_project(db, job)
                self.service.source(live, sid)
                for match in matches["matches"]:
                    if not match["word_ids"]:
                        continue
                    take_id = f"t_{hashlib.sha256((sid + match['hook_id'] + json.dumps(match['word_ids'])).encode()).hexdigest()[:20]}"
                    take = {
                        "id": take_id,
                        "line_id": match["hook_id"],
                        "word_ids": match["word_ids"],
                        "source_id": sid,
                        "role": "hook",
                        "score": round(match["confidence"] * 100),
                        "selected": True,
                        "reason": match["reason"],
                        "emphasis_word_ids": [],
                    }
                    live["takes"][take_id] = take
                    hook = next(h for h in live["hooks"] if h["id"] == match["hook_id"])
                    candidate = {
                        "take_id": take_id,
                        "source_id": sid,
                        "confidence": match["confidence"],
                        "capture_revision": next(
                            s["capture_revision"]
                            for s in source["hook_scripts"]
                            if s["hook_id"] == hook["id"]
                        ),
                        "reason": match["reason"],
                        "clips": [c for c in reviewed if c["take_id"] == take_id],
                    }
                    hook.setdefault("candidates", [])
                    existing = next((c for c in hook["candidates"] if c["take_id"] == take_id), None)
                    if existing is None:
                        hook["candidates"].append(candidate)
                    else:
                        existing.update(candidate)
                    if (
                        hook.get("take_id") is None
                        and match["confidence"] >= 0.65
                        and candidate["capture_revision"] == hook["capture_revision"]
                    ):
                        hook["take_id"] = take_id
                    if hook.get("take_id") == take_id:
                        hook["clips"] = candidate["clips"]
                live["analysis"][key] = {
                    "source_id": sid,
                    "version": PROMPT_VERSION,
                    "matches": matches,
                    "fixture": source.get("fixture", False),
                }
                self.store.save(db, p["project_id"], live)
                self.store.enqueue(
                    db, p["project_id"], "feedback", {"body_revision": live["plan"]["revision"]}
                )
            return {
                "source_id": sid,
                "hooks": live["hooks"],
                "body_revision": live["plan"]["revision"],
                "fixture": source.get("fixture", False),
            }
        templates = [Template(**x) for x in p["templates"]]
        if stored and "editorial" in stored:
            editorial = stored["editorial"]
        else:
            if stored and "body" in stored:
                body = BodyEditorial.model_validate(stored["body"])
            else:
                body = provider.analyze_body(words, 120000)
                self.cache_editorial(
                    job,
                    key,
                    {
                        "source_id": sid,
                        "version": PROMPT_VERSION,
                        "body": body.model_dump(),
                        "fixture": source.get("fixture", False),
                    },
                )
            self.checkpoint(job, "generate_hooks", 0.55)
            candidate_plan = compile_draft(
                source["words"],
                body,
                p["sources"],
                base_plan["target_duration_ms"],
                base_plan["dead_space"]["enabled"],
                {sid: source.get("metrics", {}).get("silences", [])},
                reserved_duration_ms=reserved_duration_ms,
            )
            retained_word_ids = {
                w.id
                for w in words
                for c in candidate_plan["clips"]
                if c["role"] == "body"
                and c["source_id"] == w.source_id
                and c["source_start_ms"] <= w.start_ms < w.end_ms <= c["source_end_ms"]
            }
            decision = complete_editorial(provider, body, words, templates, retained_word_ids)
            editorial = decision.model_dump()
            for take in editorial["takes"]:
                take["id"] = f"t_{hashlib.sha256((sid + take['id']).encode()).hexdigest()[:20]}"
                take["line_id"] = f"l_{hashlib.sha256((sid + take['line_id']).encode()).hexdigest()[:20]}"
                take["source_id"] = sid
        self.cache_editorial(
            job,
            key,
            {
                "source_id": sid,
                "version": PROMPT_VERSION,
                "editorial": editorial,
                "fixture": source.get("fixture", False),
            },
        )
        self.require_review_video(job, sid)
        draft = compile_draft(
            source["words"],
            editorial,
            p["sources"],
            base_plan["target_duration_ms"],
            base_plan["dead_space"]["enabled"],
            {sid: source.get("metrics", {}).get("silences", [])},
            reserved_duration_ms=reserved_duration_ms,
        )
        draft["clips"] = self.review_cuts(job, source, draft["clips"])
        for field in ("caption_edits", "caption_style", "audio", "hook_overlay"):
            draft[field] = copy.deepcopy(base_plan[field])
        if base_plan.get("selected_hook_id"):
            draft["clips"] = [c for c in base_plan["clips"] if c["role"] == "hook"] + draft["clips"]
            draft["selected_hook_id"] = base_plan["selected_hook_id"]
            draft["selected_visual_title_id"] = base_plan["selected_visual_title_id"]
        draft["revision"] = job["payload"]["base_revision"]
        draft = canonicalize_plan(
            draft, p["words"], p["sources"], {**p["takes"], **{t["id"]: t for t in editorial["takes"]}}
        )
        self.checkpoint(job, "plan", 0.9)
        with self.store.tx() as db:
            live = self.publishing_project(db, job)
            self.service.source(live, sid)
            live["takes"].update({t["id"]: t for t in editorial["takes"]})
            live["analysis"][key] = {
                "source_id": sid,
                "version": PROMPT_VERSION,
                "editorial": editorial,
                "fixture": source.get("fixture", False),
            }
            proposal = {
                "id": uid("proposal"),
                "base_revision": job["payload"]["base_revision"],
                "analysis_refs": [key],
                "plan": draft,
            }
            if (
                live["plan"]["revision"] == 0
                and not live["plan"]["clips"]
                and job["payload"]["base_revision"] == 0
            ):
                draft["revision"] = 1
                live["plan"] = draft
                initialized = True
            else:
                live["proposals"].append(proposal)
                initialized = False
            self.store.save(db, p["project_id"], live)
        return {
            "source_id": sid,
            "initialized": initialized,
            "plan": draft,
            "proposal": None if initialized else proposal,
            "hooks": live["hooks"],
            "fixture": source.get("fixture", False),
        }

    def do_rank(self, job):
        from .editing import canonicalize_plan, clips_for_take, compile_draft

        p = self.project(job)
        payload = job["payload"]
        base_plan = payload["base_plan"]
        bodies = [(key, a) for key, a in p["analysis"].items() if "editorial" in a]
        if not bodies:
            raise Problem("analysis_pending", "Body editorial analysis is required.", 409, True)
        analysis_key, analysis = bodies[-1]
        hook = next((h for h in p["hooks"] if h["id"] == payload["selected_hook_id"]), None)
        hook_clips = []
        same_hook = base_plan.get("selected_hook_id") == payload["selected_hook_id"]
        if hook:
            saved_hook = [copy.deepcopy(c) for c in base_plan["clips"] if c["role"] == "hook"]
            if same_hook and saved_hook:
                hook_clips = saved_hook
            elif hook.get("take_id") in p["takes"]:
                hook_clips = clips_for_take(
                    p["takes"][hook["take_id"]],
                    p["words"],
                    p["sources"],
                    {sid: s.get("metrics", {}).get("silences", []) for sid, s in p["sources"].items()},
                    payload["dead_space_enabled"],
                )
            else:
                raise Problem(
                    "hook_pending", "The selected hook needs a recorded take before ranking.", 409, True
                )
        draft = compile_draft(
            p["words"],
            analysis["editorial"],
            p["sources"],
            payload["target_duration_ms"],
            payload["dead_space_enabled"],
            {sid: s.get("metrics", {}).get("silences", []) for sid, s in p["sources"].items()},
            reserved_duration_ms=sum(c["source_end_ms"] - c["source_start_ms"] for c in hook_clips),
        )
        reviewed = {}
        for sid in dict.fromkeys(c["source_id"] for c in draft["clips"]):
            candidates = [c for c in draft["clips"] if c["source_id"] == sid]
            reviewed.update({c["id"]: c for c in self.review_cuts(job, p["sources"][sid], candidates)})
        draft["clips"] = [reviewed[c["id"]] for c in draft["clips"]]
        for field in ("caption_edits", "caption_style", "audio"):
            draft[field] = copy.deepcopy(base_plan[field])
        draft.update(
            clips=hook_clips + draft["clips"],
            revision=payload["base_revision"],
            selected_hook_id=payload["selected_hook_id"],
            selected_visual_title_id=base_plan.get("selected_visual_title_id") if same_hook else None,
            hook_overlay=copy.deepcopy(base_plan.get("hook_overlay")) if same_hook else None,
        )
        draft = canonicalize_plan(draft, p["words"], p["sources"], p["takes"])
        proposal = {
            "id": uid("proposal"),
            "base_revision": payload["base_revision"],
            "analysis_refs": [analysis_key],
            "plan": draft,
        }
        with self.store.tx() as db:
            live = self.publishing_project(db, job)
            live["proposals"].append(proposal)
            self.store.save(db, p["project_id"], live)
        return {"proposal": proposal}

    def do_visual(self, job):
        from .editing import canonicalize_plan

        p = self.project(job)
        source = self.service.source(p, job["payload"]["source_id"])
        base_plan = job["payload"]["base_plan"]
        if source["video_state"] != "ready" or not source.get("editing_path"):
            raise Problem("media_pending", "Visual review needs the normalized recording.", 409, True)
        words = [Word(**w) for w in source["words"]]
        if not words:
            raise Problem("analysis_pending", "Visual review needs the source transcript.", 409, True)
        draft = copy.deepcopy(base_plan)
        candidates = [
            c for c in draft["clips"] if c["source_id"] == source["source_id"] and c["role"] == "body"
        ]
        reviewed = self.review_cuts(job, source, candidates)
        reviewed_by_id = {c["id"]: c for c in reviewed}
        draft["clips"] = [reviewed_by_id.get(c["id"], c) for c in draft["clips"]]
        draft = canonicalize_plan(draft, p["words"], p["sources"], p["takes"])
        frame_count = len(candidates) * 16
        proposal = {
            "id": uid("proposal"),
            "base_revision": job["payload"]["base_revision"],
            "analysis_refs": [],
            "plan": draft,
            "kind": "visual_review",
        }
        with self.store.tx() as db:
            live = self.publishing_project(db, job)
            self.service.source(live, source["source_id"])
            live["proposals"].append(proposal)
            self.store.save(db, p["project_id"], live)
        return {
            "proposal": proposal,
            "sampled_frame_count": frame_count,
            "fixture": source.get("fixture", False),
        }

    def cache_editorial(self, job, key, analysis):
        with self.store.tx() as db:
            p = self.publishing_project(db, job)
            p["analysis"][key] = analysis
            if "editorial" in analysis:
                from .recommendations import publish

                publish(p, analysis["source_id"], analysis["editorial"])
            self.store.save(db, p["project_id"], p)

    def require_review_video(self, job, sid):
        source = self.service.source(self.project(job), sid)
        if source["video_state"] != "ready" or not source.get("editing_path"):
            if job["kind"] == "analyze":
                raise WaitingForVideo()
            raise Problem("media_pending", "Cut review requires normalized source video.", 409, True)

    def review_cuts(self, job, source, clips):
        from .boundaries import BATCH_SIZE, REVIEW_VERSION, apply_review, candidate_boundaries
        from .media import boundary_contact_sheet
        from .models import BoundaryReview

        if not clips:
            return []
        self.require_review_video(job, source["source_id"])
        source = self.service.source(self.project(job), source["source_id"])
        boundaries = candidate_boundaries(clips, source["words"], source["duration_ms"])
        for boundary in boundaries:
            if boundary["side"] == "start":
                clip = next(c for c in clips if c["id"] == boundary["clip_id"])
                script = next((s for s in source["hook_scripts"] if s["hook_id"] == clip["line_id"]), None)
                if (
                    script
                    and script["action_start_ms"] is not None
                    and clip["source_start_ms"] == script["action_start_ms"]
                ):
                    boundary["min_ms"] = boundary["max_ms"] = script["action_start_ms"]
        key = hashlib.sha256(
            json.dumps(
                [
                    REVIEW_VERSION,
                    source["fingerprint"],
                    source["audio_sha256"],
                    source["audio_timing"],
                    source["timing"],
                    self.service.settings.editor_model,
                    source.get("fixture", False),
                    boundaries,
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cached = self.project(job).get("boundary_reviews", {}).get(key)
        if cached:
            review = BoundaryReview.model_validate(cached["review"])
        else:
            started = time.monotonic()
            provider = get_provider(self.service.settings, fixture=source.get("fixture", False))
            directory = self.store.directory(job["project_id"]) / "boundaries"
            directory.mkdir(parents=True, exist_ok=True)
            decisions, sampled = [], []
            with tempfile.TemporaryDirectory(prefix="review-", dir=directory) as work:
                for offset in range(0, len(boundaries), BATCH_SIZE):
                    self.checkpoint(job, "review_boundaries", 0.6 + 0.2 * offset / len(boundaries))
                    batch = boundaries[offset : offset + BATCH_SIZE]
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        frames = list(
                            pool.map(
                                lambda boundary: boundary_contact_sheet(
                                    source["editing_path"], boundary, source["duration_ms"], work
                                ),
                                batch,
                            )
                        )
                    self.checkpoint(job)
                    result = provider.review_boundaries(batch, frames)
                    # Validate full coverage before caching any provider result.
                    apply_review(clips, batch, result)
                    decisions.extend(result.decisions)
                    sampled.extend({k: v for k, v in frame.items() if k != "path"} for frame in frames)
                    for frame in frames:
                        Path(frame["path"]).unlink(missing_ok=True)
            review = BoundaryReview(decisions=decisions)
            adjusted, evidence = apply_review(clips, boundaries, review)
            with self.store.tx() as db:
                p = self.publishing_project(db, job)
                p.setdefault("boundary_reviews", {})[key] = {
                    "source_id": source["source_id"],
                    "version": REVIEW_VERSION,
                    "review": review.model_dump(),
                    "evidence": evidence,
                    "frames": sampled,
                    "fixture": source.get("fixture", False),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
                self.store.save(db, job["project_id"], p)
            return adjusted
        return apply_review(clips, boundaries, review)[0]

    def range_metrics(self, job, project, source, start_ms, end_ms):
        from .media import audio_metrics

        key = hashlib.sha256(
            json.dumps(
                [
                    source["fingerprint"],
                    source["audio_sha256"],
                    source["audio_timing"],
                    "canonical48k_metrics_v1",
                    start_ms,
                    end_ms,
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cache = project.setdefault("range_metrics", {})
        if key not in cache:
            measured = audio_metrics(source["audio_path"], start_ms, end_ms)
            with self.store.tx() as db:
                live = self.publishing_project(db, job)
                self.service.source(live, source["source_id"])
                live.setdefault("range_metrics", {})[key] = measured
                self.store.save(db, project["project_id"], live)
            cache[key] = measured
        return copy.deepcopy(cache[key])

    def do_feedback(self, job):
        p = self.project(job)
        body = [c for c in p["plan"]["clips"] if c["role"] == "body"]
        if not body:
            return {"feedback": []}
        opening = body[0]
        source = p["sources"][opening["source_id"]]
        if not source.get("audio_path"):
            return {"feedback": []}
        body_metrics = self.range_metrics(
            job, p, source, opening["source_start_ms"], opening["source_end_ms"]
        )
        body_words = [
            w
            for w in p["words"]
            if w["source_id"] == opening["source_id"]
            and w["start_ms"] < opening["source_end_ms"]
            and w["end_ms"] > opening["source_start_ms"]
        ]
        body_metrics["words_per_minute"] = (
            60000 * len(body_words) / (opening["source_end_ms"] - opening["source_start_ms"])
        )
        results, assessed_sources = [], {source["source_id"]}
        for hook in p["hooks"]:
            take = p["takes"].get(hook.get("take_id"))
            if not take:
                continue
            hwords = [w for w in p["words"] if w["id"] in take["word_ids"]]
            if not hwords:
                continue
            hs = p["sources"][hwords[0]["source_id"]]
            if not hs.get("audio_path"):
                continue
            assessed_sources.add(hs["source_id"])
            hwords.sort(key=lambda w: (w["start_ms"], w["end_ms"]))
            metrics = self.range_metrics(job, p, hs, hwords[0]["start_ms"], hwords[-1]["end_ms"])
            metrics["words_per_minute"] = 60000 * len(hwords) / (hwords[-1]["end_ms"] - hwords[0]["start_ms"])
            context = {
                "hook_metrics": metrics,
                "body_opening_metrics": body_metrics,
                "hook_text": " ".join(w["text"] for w in hwords),
                "body_opening_text": " ".join(w["text"] for w in body_words),
                "body_context": " ".join(
                    w["text"] for w in p["words"] if w["source_id"] == source["source_id"]
                ),
                "recording_level_context": "Microphone gain and distance may differ across recordings.",
            }
            feedback_key = hashlib.sha256(
                json.dumps(
                    [
                        source["audio_sha256"],
                        hs["audio_sha256"],
                        take["id"],
                        context,
                        self.service.settings.editor_model,
                        PROMPT_VERSION,
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            cached = p.setdefault("feedback_cache", {}).get(feedback_key)
            if cached is None:
                provider = get_provider(self.service.settings, fixture=hs.get("fixture", False))
                cached = provider.feedback(context).model_dump()
                with self.store.tx() as db:
                    live = self.publishing_project(db, job)
                    for assessed in assessed_sources:
                        self.service.source(live, assessed)
                    live.setdefault("feedback_cache", {})[feedback_key] = cached
                    self.store.save(db, p["project_id"], live)
                p["feedback_cache"][feedback_key] = cached
            result = copy.deepcopy(cached)
            result.update(
                hook_take_id=take["id"],
                hook_id=hook["id"],
                body_revision=p["plan"]["revision"],
                evidence=context,
                stale=False,
                advisory=True,
            )
            results.append(result)
            self.checkpoint(job, "feedback", 0.8)
        with self.store.tx() as db:
            live = self.publishing_project(db, job)
            for assessed in assessed_sources:
                self.service.source(live, assessed)
            for result in results:
                result["stale"] = result["body_revision"] != live["plan"]["revision"]
            live["feedback"] = [
                f
                for f in live["feedback"]
                if not any(
                    f["hook_take_id"] == r["hook_take_id"] and f["body_revision"] == r["body_revision"]
                    for r in results
                )
            ] + results
            self.store.save(db, p["project_id"], live)
        return {"feedback": results}

    def do_render(self, job):
        from .media import render_plan

        snapshot = job["payload"]
        pid = job["project_id"]
        outputs = []
        self.service.check_quota(sum(c["plan"]["duration_ms"] for c in snapshot["combinations"]) * 1500)
        for i, combination in enumerate(snapshot["combinations"]):
            self.checkpoint(job, "render", i / len(snapshot["combinations"]))
            relative = f"renders/{job['id']}/{combination['combination_id']}.mp4"
            output = self.store.directory(pid) / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            metadata = render_plan(combination["plan"], snapshot["sources"], output, snapshot["kind"])
            self.checkpoint(job)
            outputs.append(
                {
                    "combination_id": combination["combination_id"],
                    "render_job_id": job["id"],
                    "input_hash": combination["input_hash"],
                    "hook_revision": combination["hook_revision"],
                    "title_revision": combination["title_revision"],
                    "plan_revision": snapshot["plan_revision"],
                    "hook_take_id": combination["hook_take_id"],
                    "kind": snapshot["kind"],
                    "relative_path": relative,
                    "metadata": metadata,
                }
            )
        with self.store.tx() as db:
            p = self.publishing_project(db, job)
            for source_id in {
                c["source_id"]
                for combination in snapshot["combinations"]
                for c in combination["plan"]["clips"]
            }:
                self.service.source(p, source_id)
            p["outputs"].extend(outputs)
            self.store.save(db, pid, p)
        return {"plan_revision": snapshot["plan_revision"], "outputs": outputs}

    def do_delete(self, job):
        pid = job["project_id"]
        self.checkpoint(job)
        try:
            shutil.rmtree(self.store.directory(pid))
        except FileNotFoundError:
            pass
        with self.store.tx() as db:
            self.publishing_project(db, job)
            row, p = self.store.project(db, pid)
            if row:
                p = {
                    "project_id": pid,
                    "name": "Deleted project",
                    "expires_at": row["expires"],
                    "deleted": True,
                    "sources": {},
                    "plan": {"revision": 0},
                    "outputs": [],
                }
                self.store.save(db, pid, p)
            db.execute("DELETE FROM jobs WHERE project_id=? AND id<>?", (pid, job["id"]))
        return {"deleted": True, "project_id": pid}
