"""Serve the browser editor, editing API, and FFmpeg preparation on loopback."""

import asyncio
import hashlib
import shutil
import uuid
from pathlib import Path

from editmaxxing.app import create_app
from editmaxxing.config import Settings
from editmaxxing.media import normalize_audio, probe
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

settings = Settings()
app = create_app(settings)
originals = settings.storage_root / "browser-originals"
originals.mkdir(parents=True, exist_ok=True)


def prepare(directory: Path):
    original = directory / "original.mov"
    metadata = probe(original)
    if not metadata["has_video"] or not metadata["has_audio"]:
        raise ValueError("Choose a video with recorded speech.")
    duration = metadata["duration_ms"]
    if duration > 1_200_000:
        raise ValueError("Choose a video under twenty minutes.")
    timing = {
        "media_origin_ms": 0,
        "encoder_delay_ms": 0,
        "duration_ms": duration,
        "sample_rate": 48000,
        "extractor": "original",
    }
    audio = directory / "audio.wav"
    offset = metadata["audio_start_ms"] - metadata["start_time_ms"]
    normalize_audio(
        original,
        audio,
        {**timing, "media_origin_ms": max(0, offset), "encoder_delay_ms": max(0, -offset)},
        duration,
    )

    def file(path, mime):
        with path.open("rb") as content:
            digest = hashlib.file_digest(content, "sha256").hexdigest()
        return {
            "uri": f"{settings.public_base_url}/local/files/{directory.name}/{path.name}",
            "name": path.name,
            "size": path.stat().st_size,
            "sha256": digest,
            "mime": mime,
        }

    return {
        "duration": duration,
        "timing": timing,
        "audioTiming": {**timing, "extractor": "local-ffmpeg"},
        "original": file(original, "video/quicktime"),
        "audio": file(audio, "audio/wav"),
    }


@app.post("/local/prepare")
async def prepare_video(request: Request):
    if request.headers.get("origin") != settings.public_base_url:
        raise HTTPException(403, "Open the editor at its local server address.")
    directory = originals / uuid.uuid4().hex
    directory.mkdir()
    try:
        size = 0
        with (directory / "original.mov").open("wb") as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_video_bytes:
                    raise HTTPException(413, "This video exceeds the upload limit.")
                output.write(chunk)
        return await asyncio.to_thread(prepare, directory)
    except HTTPException:
        shutil.rmtree(directory)
        raise
    except Exception as error:
        shutil.rmtree(directory)
        raise HTTPException(422, str(error)) from error


@app.get("/local/files/{recording}/{name}")
def local_file(recording: str, name: str):
    if len(recording) != 32 or any(c not in "0123456789abcdef" for c in recording):
        raise HTTPException(404)
    if name not in {"original.mov", "audio.wav"}:
        raise HTTPException(404)
    path = originals / recording / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/quicktime" if name.endswith(".mov") else "audio/wav")


app.mount("/", StaticFiles(directory=Path("clients/mobile/dist"), html=True), name="editor")
