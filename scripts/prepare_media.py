#!/usr/bin/env python3
"""Prepare compact analysis audio and source manifests for the endpoint client."""

import argparse
import json
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path

from editmaxxing.media import probe
from editmaxxing.models import SourceCreate


def digest(path: Path) -> str:
    result = sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def prepare(
    input_path: Path,
    output_dir: Path,
    *,
    source_id: str = "source_body",
    role: str = "body",
    hook_scripts: list[dict] | None = None,
) -> dict:
    media = probe(input_path)
    if not media["has_video"] or not media["has_audio"]:
        raise ValueError("Preparation requires a video with recorded audio.")
    output_dir.mkdir(parents=True, exist_ok=True)
    compact = output_dir / "compact.m4a"
    if compact.resolve() == input_path.resolve():
        raise ValueError("Choose an output directory separate from the original recording.")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            "asetpts=PTS-STARTPTS",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "48k",
            "-movflags",
            "+faststart",
            str(compact),
        ],
        check=True,
    )
    with tempfile.TemporaryDirectory(prefix="audio-timing-", dir=output_dir) as directory:
        decoded = Path(directory) / "decoded.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(compact),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(decoded),
            ],
            check=True,
        )
        audio_duration = probe(decoded)["duration_ms"]
    origin = max(0, media["audio_start_ms"] - media["start_time_ms"])
    source_timing = {
        "duration_ms": media["duration_ms"],
        "media_origin_ms": 0,
        "encoder_delay_ms": 0,
        "sample_rate": media["sample_rate"],
        "extractor": "captured_original",
    }
    audio_timing = {
        "duration_ms": audio_duration,
        "media_origin_ms": origin,
        "encoder_delay_ms": 0,
        "sample_rate": 16000,
        "extractor": "ffmpeg_aac16k_48k_decoded_clock_v1",
    }
    manifest = {
        "source": {
            "source_id": source_id,
            "role": role,
            "duration_ms": media["duration_ms"],
            "fingerprint": digest(input_path),
            "timing": source_timing,
            "hook_scripts": hook_scripts or [],
        },
        "video": {
            "path": str(input_path.resolve()),
            "size_bytes": input_path.stat().st_size,
            "sha256": digest(input_path),
        },
        "audio": {
            "path": str(compact.resolve()),
            "size_bytes": compact.stat().st_size,
            "sha256": digest(compact),
            "timing": audio_timing,
        },
    }
    manifest["source"] = SourceCreate.model_validate(manifest["source"]).model_dump()
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-id", default="source_body")
    parser.add_argument("--role", choices=["body", "hooks"], default="body")
    parser.add_argument("--hook-scripts", type=Path, help="JSON array of edited hook_id/text suggestions")
    args = parser.parse_args()
    scripts = json.loads(args.hook_scripts.read_text()) if args.hook_scripts else []
    result = prepare(
        args.input, args.output_dir, source_id=args.source_id, role=args.role, hook_scripts=scripts
    )
    print(
        json.dumps(
            {
                "manifest": str((args.output_dir / "manifest.json").resolve()),
                "audio": result["audio"]["path"],
                "source_duration_ms": result["source"]["duration_ms"],
            },
            indent=2,
        )
    )
