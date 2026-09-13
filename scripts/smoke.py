"""Run a live audio-first API and render check using explicit synthetic spoken media."""

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
from editmaxxing.editing import canonicalize_plan
from editmaxxing.media import probe
from prepare_media import prepare


def synthetic_video(text: str, directory: Path, name: str) -> Path:
    if shutil.which("say") is None:
        raise RuntimeError("Synthetic spoken media requires the macOS say command.")
    directory.mkdir(parents=True, exist_ok=True)
    audio = directory / f"{name}.aiff"
    video = directory / f"{name}.mp4"
    subprocess.run(["say", "-r", "180", "-o", str(audio), text], check=True, timeout=60)
    duration = probe(audio)["duration_ms"] / 1000
    color = "0x203642" if name == "body" else "0x422b55"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=360x640:r=30",
            "-i",
            str(audio),
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=True,
        timeout=90,
    )
    return video


class Smoke:
    def __init__(self, base_url: str, directory: Path, timeout: int, fixture: bool = False):
        self.directory = directory
        self.deadline = time.monotonic() + timeout
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=60)
        self.prefix = "/api/v1"
        self.fixture = fixture
        self.report = {
            "checks": [],
            "provider": "fixture" if fixture else "openai",
            "media": "synthetic speech",
            "status": "running",
        }

    def request(self, method, path, *, expected=200, **kwargs):
        response = self.client.request(method, self.prefix + path, **kwargs)
        if response.status_code != expected:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:1000]}")
        return response.json()

    def check(self, name, value=True):
        if not value:
            raise AssertionError(name)
        self.report["checks"].append(name)
        print(name, flush=True)

    def wait(self, job_id):
        last = None
        while time.monotonic() < self.deadline:
            job = self.request("GET", f"/jobs/{job_id}")
            state = (job["state"], job.get("stage"))
            if state != last:
                print(f"Job {job.get('kind', 'processing')}: {state[0]} / {state[1]}", flush=True)
                last = state
            if job["state"] == "succeeded":
                return job["result"]
            if job["state"] in ("failed", "cancelled"):
                raise RuntimeError(f"Job failed: {json.dumps(job.get('error'))}")
            time.sleep(2)
        raise TimeoutError("The smoke check reached its total timeout.")

    def audio(self, manifest):
        sid = manifest["source"]["source_id"]
        self.request("POST", self.project_path + "/sources", json=manifest["source"], expected=201)
        if self.fixture:
            self.request("POST", self.project_path + f"/sources/{sid}/fixture")
        with Path(manifest["audio"]["path"]).open("rb") as audio:
            result = self.request(
                "PUT",
                self.project_path + f"/sources/{sid}/audio",
                expected=202,
                content=audio,
                headers={
                    "Content-Type": "application/octet-stream",
                    "X-Content-SHA256": manifest["audio"]["sha256"],
                    "X-Timing-Manifest": json.dumps(manifest["audio"]["timing"], separators=(",", ":")),
                },
            )
        return result["job_id"]

    def video(self, manifest):
        sid = manifest["source"]["source_id"]
        prefix = self.project_path + f"/sources/{sid}/video/uploads"
        session = self.request(
            "POST",
            prefix,
            expected=201,
            json={
                "size_bytes": manifest["video"]["size_bytes"],
                "sha256": manifest["source"]["fingerprint"],
            },
        )
        upload_path = prefix + "/" + session["upload_id"]
        parts = []
        with Path(manifest["video"]["path"]).open("rb") as original:
            while block := original.read(session["part_size"]):
                part = len(parts)
                digest = hashlib.sha256(block).hexdigest()
                self.request(
                    "PUT",
                    upload_path + f"/parts/{part}",
                    content=block,
                    headers={"X-Content-SHA256": digest, "Content-Type": "application/octet-stream"},
                )
                if part == 0:
                    self.request(
                        "PUT",
                        upload_path + "/parts/0",
                        content=block,
                        headers={"X-Content-SHA256": digest, "Content-Type": "application/octet-stream"},
                    )
                    acknowledged = self.request("GET", upload_path)
                    self.check(
                        f"{sid}: resumable upload acknowledges an idempotent first part",
                        len(acknowledged["parts"]) == 1,
                    )
                parts.append({"part": part, "sha256": digest})
        return self.request("POST", upload_path + "/complete", expected=202, json={"parts": parts})["job_id"]

    def render(self, revision, combinations, kind):
        queued = self.request(
            "POST",
            self.project_path + "/renders",
            expected=202,
            json={
                "plan_revision": revision,
                "kind": kind,
                "combinations": combinations,
            },
        )
        result = self.wait(queued["job_id"])
        for output in result["outputs"]:
            path = self.directory / f"{kind}-{output['combination_id']}.mp4"
            with httpx.stream("GET", output["url"], timeout=60) as response:
                response.raise_for_status()
                with path.open("wb") as destination:
                    for data in response.iter_bytes():
                        destination.write(data)
            metadata = probe(path)
            dimensions = (540, 960) if kind == "draft" else (1080, 1920)
            self.check(
                f"{kind}/{output['combination_id']}: downloaded H.264/AAC portrait MP4",
                (metadata["width"], metadata["height"]) == dimensions
                and metadata["video_codec"] == "h264"
                and metadata["audio_codec"] == "aac"
                and round(metadata["fps"]) == 30,
            )
            self.check(
                f"{kind}/{output['combination_id']}: captured saved revision",
                output["plan_revision"] == revision,
            )
            self.report.setdefault("outputs", []).append({"path": str(path), "metadata": metadata})
        return result

    def run(self):
        health = self.client.get("/healthz")
        self.check("API and worker report healthy", health.status_code == 200)
        project = self.request(
            "POST",
            "/projects",
            expected=201,
            json={"name": "Live synthetic integration", "target_duration_ms": 90000},
        )
        token = project["project_token"]
        self.client.headers["Authorization"] = f"Bearer {token}"
        self.project_path = f"/projects/{project['project_id']}"
        self.report["project_id"] = project["project_id"]
        session = self.directory / "session.json"
        session.write_text(json.dumps(project, indent=2))
        os.chmod(session, 0o600)
        self.request(
            "PUT",
            self.project_path + "/templates",
            json={
                "templates": [
                    {"id": f"t{index}", "pattern": pattern, "slots": ["topic"]}
                    for index, pattern in enumerate(
                        ("Start with {topic}", "Try {topic}", "Focus on {topic}", "Remember {topic}")
                    )
                ]
            },
        )
        body = synthetic_video(
            "Clear audio keeps people watching. Trim the long pauses between your ideas. "
            "Put your strongest hook first, then explain one useful point. "
            "These three edits make a short video easier to follow.",
            self.directory,
            "body",
        )
        body_manifest = prepare(body, self.directory / "body-prepared", source_id="smoke_body")
        self.wait(self.audio(body_manifest))
        state = self.request("GET", self.project_path)
        self.check(
            "Body draft is ready while original video is pending",
            bool(state["plan"]["clips"]) and state["sources"]["smoke_body"]["video_state"] == "pending",
        )
        self.check(
            "Body analysis supplies four hooks and sixteen title choices",
            len(state["hooks"]) == 4 and sum(len(hook["visual_titles"]) for hook in state["hooks"]) == 16,
        )
        plan = copy.deepcopy(state["plan"])
        if len(plan["clips"]) > 1:
            plan["clips"][0], plan["clips"][1] = plan["clips"][1], plan["clips"][0]
        first = plan["clips"][0]
        first["source_start_ms"] += min(50, (first["source_end_ms"] - first["source_start_ms"]) // 4)
        plan = canonicalize_plan(plan, state["words"], state["sources"], state["takes"])
        spoken_caption = plan["captions"][0]
        clip_index = next(
            index for index, clip in enumerate(plan["clips"]) if clip["id"] == spoken_caption["clip_id"]
        )
        caption_clip = plan["clips"][clip_index]
        caption_offset = sum(
            clip["source_end_ms"] - clip["source_start_ms"] for clip in plan["clips"][:clip_index]
        )
        plan["caption_edits"].append(
            {
                "id": "manual_smoke",
                "clip_id": caption_clip["id"],
                "source_start_ms": caption_clip["source_start_ms"]
                + spoken_caption["start_ms"]
                - caption_offset,
                "source_end_ms": caption_clip["source_start_ms"] + spoken_caption["end_ms"] - caption_offset,
                "deleted": False,
                "replaces_word_ids": [word["word_id"] for word in spoken_caption["words"]],
                "words": [
                    {"word_id": word["word_id"], "text": word["text"]} for word in spoken_caption["words"]
                ],
                "emphasis_word_id": spoken_caption["emphasis_word_id"],
            }
        )
        saved = self.request(
            "PUT",
            self.project_path + "/plan",
            json={"base_revision": state["plan"]["revision"], "plan": plan},
        )
        self.request(
            "PUT",
            self.project_path + "/plan",
            expected=409,
            json={"base_revision": state["plan"]["revision"], "plan": plan},
        )
        saved_caption = next(caption for caption in saved["captions"] if caption["id"] == "manual_smoke")
        self.check(
            "Trim, reorder, spoken manual-caption timing, and stale revision rejection pass",
            saved_caption["words"] == spoken_caption["words"]
            and all(
                word["start_ms"] is not None and word["end_ms"] is not None for word in saved_caption["words"]
            ),
        )
        self.wait(self.video(body_manifest))
        scripts = [{"hook_id": hook["id"], "text": hook["proposed_text"]} for hook in state["hooks"]]
        hooks = synthetic_video(
            " [[slnc 1200]] ".join(script["text"] for script in scripts), self.directory, "hooks"
        )
        hooks_manifest = prepare(
            hooks,
            self.directory / "hooks-prepared",
            source_id="smoke_hooks",
            role="hooks",
            hook_scripts=scripts,
        )
        hook_job = self.audio(hooks_manifest)
        hook_video = self.video(hooks_manifest)
        self.wait(hook_job)
        self.wait(hook_video)
        state = self.request("GET", self.project_path)
        self.check(
            "Recorded hook attachment preserves the saved body revision and edit", state["plan"] == saved
        )
        ready = [hook for hook in state["hooks"] if hook.get("take_id")]
        self.check("Four recorded hook candidates are available", len(ready) == 4)
        self.check(
            "Both originals have verified processing copies",
            all(
                source["storage"]["original_verified"] and source["storage"]["copy_kind"] == "processing"
                for source in state["sources"].values()
            ),
        )
        combinations = [
            {
                "id": f"combo_{index + 1}",
                "hook_id": hook["id"],
                "visual_title_id": hook["visual_titles"][0]["id"],
                "use_title": True,
                "overlay": {
                    "text": "Synthetic integration",
                    "position": {"x": 0.44, "y": 0.24},
                    "hold_ms": 12000,
                    "fade_ms": 300,
                },
            }
            for index, hook in enumerate(ready[:2])
        ]
        self.render(saved["revision"], combinations, "draft")
        self.render(saved["revision"], combinations[:1], "export")
        state = self.request("GET", self.project_path)
        self.check("Project reload preserves captions and clip order", state["plan"] == saved)
        self.check(
            "Delivery feedback is advisory and revision-bound",
            bool(state["feedback"])
            and all(
                item["advisory"] and item["body_revision"] == saved["revision"] for item in state["feedback"]
            ),
        )
        self.report["status"] = "passed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        required=True,
        help="Generate synthetic spoken recordings and run live provider requests",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/api-smoke"))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--fixture", action="store_true", help="Request explicit fixture analysis from an enabled backend"
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    smoke = Smoke(args.base_url, args.output_dir.resolve(), args.timeout, args.fixture)
    started = time.monotonic()
    try:
        smoke.run()
    except Exception as error:
        smoke.report.update(status="failed", error=str(error))
        raise
    finally:
        smoke.report["elapsed_seconds"] = round(time.monotonic() - started, 1)
        (args.output_dir / "report.json").write_text(json.dumps(smoke.report, indent=2) + "\n")
        smoke.client.close()


if __name__ == "__main__":
    main()
