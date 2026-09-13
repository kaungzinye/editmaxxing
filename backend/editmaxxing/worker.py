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
from pathlib import Path

from .models import HookScript, Template, Timing, Word
from .provider import PROMPT_VERSION, assemble_title, get_provider
from .service import Problem
from .store import uid

log = logging.getLogger(__name__)


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
            row = db.execute("SELECT data FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
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
        key = hashlib.sha256(
            json.dumps(
                [
                    source["fingerprint"],
                    source["audio_sha256"],
                    source["audio_timing"],
                    p["templates"],
                    self.service.settings.editor_model,
                    PROMPT_VERSION,
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
                        "reason": match["reason"],
                    }
                    hook.setdefault("candidates", [])
                    if not any(c["take_id"] == take_id for c in hook["candidates"]):
                        hook["candidates"].append(candidate)
                    if hook.get("take_id") is None and match["confidence"] >= 0.65:
                        hook["take_id"] = take_id
                        hook["clips"] = clips_for_take(take, live["words"], live["sources"])
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
        if stored:
            editorial = stored["editorial"]
        else:
            decision = provider.analyze(words, templates, 120000)
            editorial = decision.model_dump()
            for take in editorial["takes"]:
                take["id"] = f"t_{hashlib.sha256((sid + take['id']).encode()).hexdigest()[:20]}"
                take["line_id"] = f"l_{hashlib.sha256((sid + take['line_id']).encode()).hexdigest()[:20]}"
                take["source_id"] = sid
        draft = compile_draft(
            source["words"],
            editorial,
            p["sources"],
            base_plan["target_duration_ms"],
            base_plan["dead_space"]["enabled"],
            {sid: source.get("metrics", {}).get("silences", [])},
            reserved_duration_ms=sum(
                c["source_end_ms"] - c["source_start_ms"] for c in base_plan["clips"] if c["role"] == "hook"
            ),
        )
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
            if live["templates"] == p["templates"]:
                from .models import TitleChoice

                for i, hook in enumerate(editorial["hooks"]):
                    hid = f"h_{hashlib.sha256((sid + str(i)).encode()).hexdigest()[:18]}"
                    titles = []
                    for j, choice in enumerate(hook["visual_titles"]):
                        template = next(t for t in templates if t.id == choice["template_id"])
                        title = assemble_title(TitleChoice(**choice), template, words)
                        title["id"] = f"{hid}_v{j + 1}"
                        titles.append(title)
                    existing = next((h for h in live["hooks"] if h["id"] == hid), None)
                    if existing:
                        existing["visual_titles"] = titles
                    else:
                        live["hooks"].append(
                            {
                                "id": hid,
                                "proposed_text": hook["proposed_text"],
                                "take_id": None,
                                "visual_titles": titles,
                                "candidates": [],
                                "clips": [],
                            }
                        )
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
        from .editing import canonicalize_plan, compile_draft
        from .media import sample_frames

        p = self.project(job)
        source = self.service.source(p, job["payload"]["source_id"])
        base_plan = job["payload"]["base_plan"]
        if source["video_state"] != "ready" or not source.get("editing_path"):
            raise Problem("media_pending", "Visual review needs the normalized recording.", 409, True)
        words = [Word(**w) for w in source["words"]]
        if not words:
            raise Problem("analysis_pending", "Visual review needs the source transcript.", 409, True)
        count = min(8, len(words))
        timestamps = [
            (
                words[round(i * (len(words) - 1) / max(1, count - 1))].start_ms
                + words[round(i * (len(words) - 1) / max(1, count - 1))].end_ms
            )
            // 2
            for i in range(count)
        ]
        key = hashlib.sha256(
            json.dumps(
                [
                    "visual_review_v1",
                    source["fingerprint"],
                    source["audio_sha256"],
                    source["audio_timing"],
                    self.service.settings.editor_model,
                    PROMPT_VERSION,
                    timestamps,
                    p["templates"],
                    120000,
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        stored = p["analysis"].get(key)
        if stored:
            editorial = stored["editorial"]
            frame_count = stored["sampled_frame_count"]
        else:
            provider = get_provider(self.service.settings, fixture=source.get("fixture", False))
            directory = self.store.directory(p["project_id"]) / "visual"
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="review-", dir=directory) as work:
                frames = sample_frames(source["editing_path"], source["source_id"], timestamps, work)
                if not frames:
                    raise Problem(
                        "frames_unavailable",
                        "The recording needs readable video frames for visual review.",
                        422,
                    )
                frame_count = len(frames)
                self.checkpoint(job, "visual", 0.25)
                editorial = provider.analyze(
                    words, [Template(**t) for t in p["templates"]], 120000, frames=frames
                ).model_dump()
            for take in editorial["takes"]:
                take["id"] = f"t_{hashlib.sha256((key + take['id']).encode()).hexdigest()[:20]}"
                take["line_id"] = f"l_{hashlib.sha256((key + take['line_id']).encode()).hexdigest()[:20]}"
                take["source_id"] = source["source_id"]
        hooks = [copy.deepcopy(c) for c in base_plan["clips"] if c["role"] == "hook"]
        draft = compile_draft(
            source["words"],
            editorial,
            p["sources"],
            base_plan["target_duration_ms"],
            base_plan["dead_space"]["enabled"],
            {source["source_id"]: source.get("metrics", {}).get("silences", [])},
            reserved_duration_ms=sum(c["source_end_ms"] - c["source_start_ms"] for c in hooks),
        )
        available = [copy.deepcopy(c) for c in base_plan["clips"] if c["role"] == "body"]
        for clip in draft["clips"]:
            match = next(
                (
                    c
                    for c in available
                    if all(
                        c[field] == clip[field] for field in ("source_id", "source_start_ms", "source_end_ms")
                    )
                ),
                None,
            )
            if match:
                clip["id"] = match["id"]
                available.remove(match)
        for field in (
            "caption_edits",
            "caption_style",
            "audio",
            "hook_overlay",
            "selected_hook_id",
            "selected_visual_title_id",
        ):
            draft[field] = copy.deepcopy(base_plan[field])
        draft["clips"] = hooks + draft["clips"]
        draft["revision"] = job["payload"]["base_revision"]
        takes = {**p["takes"], **{take["id"]: take for take in editorial["takes"]}}
        draft = canonicalize_plan(draft, p["words"], p["sources"], takes)
        proposal = {
            "id": uid("proposal"),
            "base_revision": job["payload"]["base_revision"],
            "analysis_refs": [key],
            "plan": draft,
            "kind": "visual_review",
        }
        with self.store.tx() as db:
            live = self.publishing_project(db, job)
            self.service.source(live, source["source_id"])
            live["takes"].update({take["id"]: take for take in editorial["takes"]})
            live["analysis"][key] = {
                "source_id": source["source_id"],
                "version": PROMPT_VERSION,
                "kind": "visual_review",
                "frame_timestamps_ms": timestamps,
                "sampled_frame_count": frame_count,
                "editorial": editorial,
                "fixture": source.get("fixture", False),
            }
            live["proposals"].append(proposal)
            self.store.save(db, p["project_id"], live)
        return {
            "proposal": proposal,
            "sampled_frame_count": frame_count,
            "fixture": source.get("fixture", False),
        }

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
