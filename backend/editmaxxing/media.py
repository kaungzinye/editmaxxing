"""Canonical media timing, measured audio, and exact-plan ffmpeg renders."""

from __future__ import annotations

import json
import logging
import math
import re
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path

from PIL import ImageFont

FONT_PATH = Path(__file__).parent / "fonts" / "TikTokSans36pt-Bold.ttf"
SAMPLE_RATE = 48000
FPS = 30
LOUDNESS = "loudnorm=I=-16:TP=-1.5:LRA=11"
log = logging.getLogger(__name__)


class MediaError(ValueError):
    code = "invalid_media"
    retryable = False

    def __init__(self, message: str, diagnostic: str | None = None):
        super().__init__(message)
        self.message = message
        self.diagnostic = diagnostic


def _run(args: list[str], *, timeout: int = 1800, binary: bool = False) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False, text=not binary)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError("Media processing requires an available ffmpeg and a completed media file.") from exc
    if result.returncode:
        stderr = result.stderr.decode(errors="replace") if binary else result.stderr
        log.warning("ffmpeg/ffprobe failed: %s", stderr[-2000:].strip())
        raise MediaError(
            "The media processor cannot decode or render this file. Verify the complete recording and retry.",
            stderr[-2000:].strip(),
        )
    return result


def _ffmpeg(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
    return _run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-threads", "2", *map(str, args)], binary=binary)


def _number(value: object, default: float = 0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def probe(path: str | Path) -> dict:
    raw = json.loads(
        _run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], timeout=60
        ).stdout
    )
    streams = raw.get("streams", [])
    video = next(
        (
            stream
            for stream in streams
            if stream["codec_type"] == "video" and not stream.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    audio = next((stream for stream in streams if stream["codec_type"] == "audio"), None)
    if video is None and audio is None:
        raise MediaError("The file needs a readable video or audio stream.")
    start = _number(raw.get("format", {}).get("start_time"))
    end = max(
        (_number(s.get("start_time"), start) + _number(s.get("duration")) for s in (video, audio) if s),
        default=start,
    )
    format_duration = _number(raw.get("format", {}).get("duration"))
    duration = end - start if end > start else format_duration
    if duration <= 0:
        raise MediaError("The media duration must be positive.")
    rotation = 0
    fps = 0.0
    if video:
        rotation = round(_number(video.get("tags", {}).get("rotate")))
        for side in video.get("side_data_list", []):
            if "rotation" in side:
                rotation = round(_number(side["rotation"]))
        rate = video.get("avg_frame_rate", "0/1").split("/")
        fps = _number(rate[0]) / max(_number(rate[1] if len(rate) > 1 else 1), 1)
    width, height = (video.get("width", 0), video.get("height", 0)) if video else (0, 0)
    return {
        "duration_ms": round(duration * 1000),
        "start_time_ms": round(start * 1000),
        "has_video": video is not None,
        "has_audio": audio is not None,
        "width": width,
        "height": height,
        "display_width": height if rotation % 180 else width,
        "display_height": width if rotation % 180 else height,
        "rotation": rotation,
        "fps": fps,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "sample_rate": int(audio.get("sample_rate", 0)) if audio else None,
        "audio_duration_ms": round(_number(audio.get("duration"), duration) * 1000) if audio else 0,
        "video_duration_ms": round(_number(video.get("duration"), duration) * 1000) if video else 0,
        "audio_start_ms": round(_number(audio.get("start_time"), start) * 1000) if audio else 0,
        "video_start_ms": round(_number(video.get("start_time"), start) * 1000) if video else 0,
        "size_bytes": Path(path).stat().st_size,
    }


def validate_timing(
    metadata: dict, timing: dict, source_duration_ms: int, *, tolerance_ms: int = 150
) -> dict:
    timing = timing.model_dump() if hasattr(timing, "model_dump") else dict(timing)
    decoded = metadata["duration_ms"]
    shift = timing.get("media_origin_ms", 0) - timing.get("encoder_delay_ms", 0)
    if abs(decoded - timing["duration_ms"]) > tolerance_ms:
        raise MediaError(
            "The uploaded media duration differs from its timing manifest. Extract this recording again and submit its measured timing."
        )
    if abs(decoded + shift - source_duration_ms) > tolerance_ms:
        raise MediaError(
            "The audio/video timestamp map differs from the registered source duration. Use derivatives from the same complete recording."
        )
    if shift >= source_duration_ms or decoded + shift <= 0:
        raise MediaError("The timestamp map must cover a positive part of the source.")
    return {
        "input_duration_ms": decoded,
        "input_start_time_ms": metadata["start_time_ms"],
        "media_origin_ms": timing.get("media_origin_ms", 0),
        "encoder_delay_ms": timing.get("encoder_delay_ms", 0),
        "canonical_shift_ms": shift,
        "duration_ms": source_duration_ms,
        "editing_media_origin_ms": 0,
        "editing_encoder_delay_ms": 0,
        "clock": "canonical_ms = decoded_media_ms + media_origin_ms - encoder_delay_ms",
    }


def _audio_filter(shift_ms: int, duration_ms: int) -> str:
    filters = ["asetpts=PTS-STARTPTS", f"aresample={SAMPLE_RATE}", "aformat=channel_layouts=mono"]
    if shift_ms < 0:
        filters += [f"atrim=start_sample={round(-shift_ms * SAMPLE_RATE / 1000)}", "asetpts=PTS-STARTPTS"]
    elif shift_ms > 0:
        filters += [f"adelay={round(shift_ms * SAMPLE_RATE / 1000)}S:all=1"]
    filters += ["apad", f"atrim=end_sample={round(duration_ms * SAMPLE_RATE / 1000)}", "asetpts=N/SR/TB"]
    return ",".join(filters)


def normalize_audio(
    input_path: str | Path, output_path: str | Path, timing: dict, source_duration_ms: int
) -> dict:
    metadata = probe(input_path)
    if not metadata["has_audio"]:
        raise MediaError("The analysis upload needs an audio stream.")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="decode-", dir=Path(output_path).parent) as directory:
        decoded_path = Path(directory) / "decoded.wav"
        _ffmpeg(
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(decoded_path),
        )
        decoded = probe(decoded_path)
        mapping = validate_timing(decoded, timing, source_duration_ms)
        mapping["container_start_time_ms"] = metadata["start_time_ms"]
        _ffmpeg(
            "-i",
            str(decoded_path),
            "-af",
            _audio_filter(mapping["canonical_shift_ms"], source_duration_ms),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(output_path),
        )
    output = probe(output_path)
    if abs(output["duration_ms"] - source_duration_ms) > 1:
        raise MediaError("The normalized audio duration differs from the canonical source clock.")
    return {**output, "path": str(output_path), "timing": mapping}


def normalize_video(
    input_path: str | Path, output_path: str | Path, timing: dict, source_duration_ms: int
) -> dict:
    metadata = probe(input_path)
    if not metadata["has_video"]:
        raise MediaError("The original upload needs a video stream.")
    mapping = validate_timing(metadata, timing, source_duration_ms)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    shift = mapping["canonical_shift_ms"]
    video_shift = shift + metadata["video_start_ms"] - metadata["start_time_ms"]
    video_filter = ["setpts=PTS-STARTPTS"]
    if video_shift < 0:
        video_filter += [f"trim=start={-video_shift / 1000:.6f}", "setpts=PTS-STARTPTS"]
    elif video_shift > 0:
        video_filter += [f"tpad=start_mode=clone:start_duration={video_shift / 1000:.6f}"]
    frames = max(1, math.ceil(source_duration_ms * FPS / 1000))
    video_filter += [
        "scale=w='min(1920,iw)':h='min(1920,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
        "setsar=1",
        "fps=30",
        "tpad=stop_mode=clone:stop_duration=1",
        f"trim=end_frame={frames}",
        "setpts=N/(30*TB)",
    ]
    args = ["-i", str(input_path)]
    if metadata["has_audio"]:
        audio_shift = shift + metadata["audio_start_ms"] - metadata["start_time_ms"]
        graph = (
            f"[0:v:0]{','.join(video_filter)}[v];[0:a:0]{_audio_filter(audio_shift, source_duration_ms)}[a]"
        )
    else:
        graph = f"[0:v:0]{','.join(video_filter)}[v];anullsrc=r=48000:cl=mono,atrim=duration={source_duration_ms / 1000:.6f}[a]"
    _ffmpeg(
        *args,
        "-filter_complex_threads",
        "1",
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-threads",
        "2",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-metadata:s:v:0",
        "rotate=0",
        "-movflags",
        "+faststart",
        str(output_path),
    )
    output = probe(output_path)
    if abs(output["duration_ms"] - source_duration_ms) > 35:
        raise MediaError("The normalized video duration differs from the canonical source clock.")
    return {**output, "path": str(output_path), "timing": mapping}


def _range_args(path: str | Path, start_ms: int | None, end_ms: int | None) -> list[str]:
    start = 0 if start_ms is None else start_ms
    if start < 0 or (end_ms is not None and end_ms <= start):
        raise MediaError("Audio measurements need a positive source range.")
    args = ["-ss", f"{start / 1000:.6f}", "-i", str(path)]
    if end_ms is not None:
        args += ["-t", f"{(end_ms - start) / 1000:.6f}"]
    return args


def _silences(stderr: str, duration_ms: int, offset_ms: int = 0) -> list[dict]:
    intervals, start = [], None
    for event, number in re.findall(r"silence_(start|end):\s*([0-9.+-]+)", stderr):
        at = max(0, min(duration_ms, round(float(number) * 1000)))
        if event == "start":
            start = at
        elif start is not None:
            intervals.append({"start_ms": offset_ms + start, "end_ms": offset_ms + at})
            start = None
    if start is not None and start < duration_ms:
        intervals.append({"start_ms": offset_ms + start, "end_ms": offset_ms + duration_ms})
    return intervals


def silence_detect(path: str | Path) -> list[dict]:
    duration = probe(path)["duration_ms"]
    result = _ffmpeg("-i", str(path), "-vn", "-af", "silencedetect=noise=-35dB:d=0.15", "-f", "null", "-")
    return _silences(result.stderr, duration)


def _loudness(path: str | Path, start_ms: int | None = None, end_ms: int | None = None) -> dict:
    result = _ffmpeg(
        *_range_args(path, start_ms, end_ms), "-vn", "-af", f"{LOUDNESS}:print_format=json", "-f", "null", "-"
    )
    matches = re.findall(r'\{\s*"input_i"[\s\S]*?\}', result.stderr)
    return json.loads(matches[-1]) if matches else {}


def _db(value: float) -> float | None:
    return round(20 * math.log10(value), 3) if value > 0 else None


def audio_metrics(path: str | Path, start_ms: int | None = None, end_ms: int | None = None) -> dict:
    start = start_ms or 0
    result = _ffmpeg(
        *_range_args(path, start_ms, end_ms),
        "-vn",
        "-af",
        "silencedetect=noise=-35dB:d=0.15",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
        binary=True,
    )
    samples = array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise MediaError("The selected audio range contains zero samples.")
    envelope, total_energy, speech_energy, speech_samples, peak = [], 0, 0, 0, 0
    for begin in range(0, len(samples), 1600):
        block = samples[begin : begin + 1600]
        energy = sum(sample * sample for sample in block)
        total_energy += energy
        peak = max(peak, max(abs(sample) for sample in block))
        rms = math.sqrt(energy / len(block)) / 32768
        if rms >= 0.01:
            speech_energy += energy
            speech_samples += len(block)
        envelope.append(
            {
                "start_ms": start + round(begin / 16),
                "end_ms": start + round((begin + len(block)) / 16),
                "rms_dbfs": _db(rms),
            }
        )
    duration = round(len(samples) / 16)
    measured = _loudness(path, start_ms, end_ms)
    finite = lambda key: (
        _number(measured.get(key), float("nan"))
        if math.isfinite(_number(measured.get(key), float("nan")))
        else None
    )
    silences = _silences(result.stderr.decode(errors="replace"), duration, start)
    return {
        "start_ms": start,
        "duration_ms": duration,
        "sample_count": len(samples),
        "sample_rate": 16000,
        "rms_dbfs": _db(math.sqrt(total_energy / len(samples)) / 32768),
        "speech_rms_dbfs": _db(math.sqrt(speech_energy / speech_samples) / 32768) if speech_samples else None,
        "peak_dbfs": _db(peak / 32768),
        "integrated_lufs": finite("input_i"),
        "true_peak_dbtp": finite("input_tp"),
        "loudness_range_lu": finite("input_lra"),
        "speech_duration_ms": round(speech_samples / 16),
        "pause_fraction": sum(s["end_ms"] - s["start_ms"] for s in silences) / duration,
        "silences": silences,
        "rms_envelope": envelope,
    }


def _ass_time(ms: int) -> str:
    centiseconds = max(0, round(ms / 10))
    seconds, fraction = divmod(centiseconds, 100)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def _escape_ass(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\r", "")
        .replace("\n", "\\N")
    )


def _rounded_path(width: int, height: int, radius: int = 22) -> str:
    r, k = min(radius, width // 2, height // 2), 0.55228475
    c = round(r * (1 - k))
    return (
        f"m {r} 0 l {width - r} 0 b {width - c} 0 {width} {c} {width} {r} "
        f"l {width} {height - r} b {width} {height - c} {width - c} {height} {width - r} {height} "
        f"l {r} {height} b {c} {height} 0 {height - c} 0 {height - r} "
        f"l 0 {r} b 0 {c} {c} 0 {r} 0"
    )


def _text_block(words: list[dict], position: dict, *, title: bool = False) -> tuple[str, str, int]:
    size, max_width = (70 if title else 62), 840
    tokens = [part for word in words for part in word["text"].split()]
    if not tokens:
        return "", "", size
    while True:
        font = ImageFont.truetype(str(FONT_PATH), size)
        lines, line, line_width = [], [], 0.0
        space = font.getlength(" ")
        for text in tokens:
            parts, part = [], ""
            for char in text:
                if part and font.getlength(part + char) > max_width:
                    parts.append(part)
                    part = ""
                part += char
            parts.append(part)
            for part in parts:
                length = font.getlength(part)
                if line and line_width + space + length > max_width:
                    lines.append((line, line_width))
                    line, line_width = [], 0.0
                line_width += (space if line else 0) + length
                line.append(part)
        if line:
            lines.append((line, line_width))
        line_height = math.ceil(size * 1.38)
        if len(lines) * line_height <= 1500 or size <= 24:
            break
        size -= 2
    width = min(1060, math.ceil(max(width for _, width in lines)) + 48)
    height = min(1900, len(lines) * line_height + 30)
    cx = min(1080 - width / 2 - 10, max(width / 2 + 10, position["x"] * 1080))
    cy = min(1920 - height / 2 - 10, max(height / 2 + 10, position["y"] * 1920))
    background = (
        f"{{\\an7\\pos({cx - width / 2:.1f},{cy - height / 2:.1f})\\p1\\bord0\\shad0\\1c&H000000&\\1a&H65&}}{_rounded_path(width, height)}{{\\p0}}"
        if title
        else ""
    )
    text = "\\N".join(" ".join(_escape_ass(word) for word in line) for line, _ in lines)
    border = 0 if title else 4
    foreground = f"{{\\an5\\pos({cx:.1f},{cy:.1f})\\fs{size}\\bord{border}\\1c&HFFFFFF&\\3c&H000000&\\3a&H00&\\shad0\\1a&H00&}}{text}"
    return background, foreground, size


def write_subtitles(plan: dict, path: str | Path, *, clip_id: str | None = None) -> Path:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Text,TikTok Sans,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    def add(
        start: int,
        end: int,
        words: list[dict],
        position: dict,
        title: bool = False,
        fade_ms: int = 0,
    ):
        end = min(plan["duration_ms"], end)
        if start >= end:
            return
        if _ass_time(start) == _ass_time(end):
            return
        background, foreground, _ = _text_block(words, position, title=title)
        fade = f"{{\\fad(0,{min(fade_ms, end - start)})}}" if fade_ms else ""
        for layer, text in ((0, background), (1, foreground)):
            if text:
                events.append(
                    f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},Text,,0,0,0,,{fade}{text}"
                )

    clip_windows, cursor_ms = {}, 0
    for clip in plan.get("clips", []):
        end_ms = cursor_ms + clip["source_end_ms"] - clip["source_start_ms"]
        clip_windows[clip["id"]] = (cursor_ms, end_ms)
        cursor_ms = end_ms
    for caption in plan.get("captions", []):
        if clip_id is not None and caption["clip_id"] != clip_id:
            continue
        window_start, window_end = clip_windows.get(caption["clip_id"], (0, plan["duration_ms"]))
        start = max(caption["start_ms"], window_start)
        end = min(caption["end_ms"], window_end, plan["duration_ms"])
        if start >= end:
            continue
        add(start, end, caption["words"], plan["caption_style"]["position"])
    overlay = plan.get("hook_overlay")
    if overlay and overlay.get("text", "").strip():
        add(
            0,
            overlay["hold_ms"],
            [{"text": overlay["text"], "word_id": None}],
            overlay["position"],
            True,
            overlay.get("fade_ms", 300),
        )
    Path(path).write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return Path(path)


def _filter_path(path: str | Path) -> str:
    # ffmpeg filter values use a separate escaping layer from process arguments.
    value = str(Path(path).resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\''")
    return f"'{value}'"


def _concat_audio(paths: list[Path], output: Path) -> None:
    with wave.open(str(output), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(SAMPLE_RATE)
        for path in paths:
            with wave.open(str(path), "rb") as source:
                if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (
                    1,
                    2,
                    SAMPLE_RATE,
                ):
                    raise MediaError("Render audio needs mono 48 kHz PCM segments.")
                while data := source.readframes(65536):
                    target.writeframesraw(data)


def render_plan(plan: dict, sources: dict[str, dict], output_path: str | Path, kind: str = "draft") -> dict:
    if kind not in {"draft", "export"}:
        raise MediaError("Render kind must be draft or export.")
    clips = plan.get("clips", [])
    duration = sum(clip["source_end_ms"] - clip["source_start_ms"] for clip in clips)
    if not clips or duration <= 0 or duration != plan.get("duration_ms"):
        raise MediaError("Render requires a nonempty canonical plan with its derived duration.")
    for clip in clips:
        source = sources.get(clip["source_id"])
        if source is None or not source.get("editing_path") or not Path(source["editing_path"]).is_file():
            raise MediaError(f"Source {clip['source_id']} needs a verified editing video.")
        if not 0 <= clip["source_start_ms"] < clip["source_end_ms"] <= source["duration_ms"]:
            raise MediaError("Render clip exceeds its source range.")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height = (540, 960) if kind == "draft" else (1080, 1920)
    enabled = plan.get("audio", {}).get("normalization_enabled", True)
    source_info = {sid: probe(sources[sid]["editing_path"]) for sid in {clip["source_id"] for clip in clips}}
    gains = {"body": 0.0, "hook": 0.0}
    with tempfile.TemporaryDirectory(prefix="render-", dir=output.parent) as directory:
        work = Path(directory)
        audio_paths, video_paths = [], []
        role_energy = {"body": [0.0, 0], "hook": [0.0, 0]}
        for number, clip in enumerate(clips):
            audio_path = work / f"audio-{number:04d}.wav"
            audio_paths.append(audio_path)
            source = sources[clip["source_id"]]
            span = clip["source_end_ms"] - clip["source_start_ms"]
            audio_input = source.get("audio_path") or source["editing_path"]
            if source.get("audio_path") or source_info[clip["source_id"]]["has_audio"]:
                _ffmpeg(
                    *_range_args(audio_input, clip["source_start_ms"], clip["source_end_ms"]),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-af",
                    _audio_filter(0, span),
                    "-c:a",
                    "pcm_s16le",
                    str(audio_path),
                )
            else:
                _ffmpeg(
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=48000:cl=mono",
                    "-t",
                    f"{span / 1000:.6f}",
                    "-c:a",
                    "pcm_s16le",
                    str(audio_path),
                )
            if enabled:
                with wave.open(str(audio_path), "rb") as track:
                    samples = array("h", track.readframes(track.getnframes()))
                if sys.byteorder != "little":
                    samples.byteswap()
                for begin in range(0, len(samples), 4800):
                    block = samples[begin : begin + 4800]
                    energy = sum(value * value for value in block)
                    if block and math.sqrt(energy / len(block)) / 32768 >= 0.01:
                        role_energy[clip["role"]][0] += energy
                        role_energy[clip["role"]][1] += len(block)
        levels = {
            role: _db(math.sqrt(energy / count) / 32768)
            for role, (energy, count) in role_energy.items()
            if count
        }
        if enabled and "body" in levels and "hook" in levels:
            gains["hook"] = round(max(-6.0, min(6.0, levels["body"] - levels["hook"])), 3)
        if enabled:
            for number, clip in enumerate(clips):
                gain = gains[clip["role"]]
                if gain:
                    adjusted = work / f"gain-{number:04d}.wav"
                    _ffmpeg(
                        "-i",
                        str(audio_paths[number]),
                        "-af",
                        f"volume={gain}dB",
                        "-c:a",
                        "pcm_s16le",
                        str(adjusted),
                    )
                    audio_paths[number] = adjusted
        assembled_audio = work / "assembled.wav"
        _concat_audio(audio_paths, assembled_audio)
        measurement = _loudness(assembled_audio) if enabled else {}
        normalization = "anull"
        if enabled and math.isfinite(_number(measurement.get("input_i"), float("nan"))):
            normalization = (
                LOUDNESS
                + ":"
                + ":".join(
                    [
                        f"measured_I={measurement['input_i']}",
                        f"measured_TP={measurement['input_tp']}",
                        f"measured_LRA={measurement['input_lra']}",
                        f"measured_thresh={measurement['input_thresh']}",
                        f"offset={measurement['target_offset']}",
                        "linear=true",
                    ]
                )
            )
        elif enabled:
            normalization = "alimiter=limit=0.841395:level=false:latency=true"
        frame_cursor, timeline_ms = 0, 0
        for number, clip in enumerate(clips):
            span = clip["source_end_ms"] - clip["source_start_ms"]
            next_cursor = round((timeline_ms + span) * FPS / 1000)
            if number == len(clips) - 1:
                next_cursor = max(1, next_cursor)
            frames = next_cursor - frame_cursor
            if frames > 0:
                subtitles = write_subtitles(plan, work / f"captions-{number:04d}.ass", clip_id=clip["id"])
                video_path = work / f"video-{number:04d}.mp4"
                video_paths.append(video_path)
                source_path = sources[clip["source_id"]]["editing_path"]
                filters = [
                    "setpts=PTS-STARTPTS",
                    f"scale={width}:{height}:force_original_aspect_ratio=increase",
                    f"crop={width}:{height}",
                    "setsar=1",
                    "fps=30",
                    "tpad=stop_mode=clone:stop_duration=1",
                    f"trim=end_frame={frames}",
                    f"setpts=N/(30*TB)+{frame_cursor}/(30*TB)",
                    f"subtitles=filename={_filter_path(subtitles)}:fontsdir={_filter_path(FONT_PATH.parent)}",
                    "setpts=PTS-STARTPTS",
                    "format=yuv420p",
                ]
                _ffmpeg(
                    "-ss",
                    f"{clip['source_start_ms'] / 1000:.6f}",
                    "-i",
                    source_path,
                    "-an",
                    "-vf",
                    ",".join(filters),
                    "-frames:v",
                    str(frames),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "20" if kind == "draft" else "18",
                    "-threads",
                    "2",
                    "-video_track_timescale",
                    "30000",
                    str(video_path),
                )
            frame_cursor, timeline_ms = next_cursor, timeline_ms + span
        concat_file = work / "video.txt"
        concat_file.write_text("".join(f"file '{path.name}'\n" for path in video_paths))
        audio_filter = (
            f"{normalization},aresample=48000,apad,atrim=end_sample={duration * 48},asetpts=N/SR/TB"
        )
        _ffmpeg(
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(concat_file),
            "-i",
            str(assembled_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-af",
            audio_filter,
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            str(output),
        )
    metadata = probe(output)
    if abs(metadata["duration_ms"] - duration) > 35 or abs(metadata["audio_duration_ms"] - duration) > 2:
        raise MediaError("The rendered media duration differs from the saved edit.")
    metrics = audio_metrics(output)
    metrics.pop("rms_envelope", None)
    return {
        **metadata,
        "path": str(output),
        "kind": kind,
        "plan_revision": plan["revision"],
        "plan_duration_ms": duration,
        "video_frame_count": frame_cursor,
        "audio": {
            "normalization_enabled": enabled,
            "preset": "speech_consistent",
            "role_gains_db": gains,
            "measurement": metrics,
        },
    }


def boundary_contact_sheet(
    path: str | Path, boundary: dict, duration_ms: int, output_dir: str | Path
) -> dict:
    """Decode eight consecutive 30 fps source frames in one seek and label their canonical times."""
    from PIL import Image, ImageDraw

    timestamp = boundary["timestamp_ms"]
    pivot = math.ceil(timestamp * FPS / 1000)
    last = max(0, math.ceil(duration_ms * FPS / 1000) - 1)
    indices = [max(0, min(last, pivot + offset)) for offset in range(-4, 4)]
    first, count = min(indices), max(indices) - min(indices) + 1
    size = 192
    result = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-threads",
            "1",
            "-ss",
            f"{first / FPS:.9f}",
            "-i",
            str(path),
            "-an",
            "-frames:v",
            str(count),
            "-vf",
            f"scale={size}:{size}:force_original_aspect_ratio=decrease,pad={size}:{size}:(ow-iw)/2:(oh-ih)/2",
            "-threads",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        timeout=30,
        binary=True,
    )
    frame_bytes = size * size * 3
    if len(result.stdout) != count * frame_bytes:
        raise MediaError("Boundary review needs every requested source frame.")
    sheet = Image.new("RGB", (size * 4, (size + 24) * 2), "black")
    draw = ImageDraw.Draw(sheet)
    timestamps = []
    for tile, frame_index in enumerate(indices):
        offset = (frame_index - first) * frame_bytes
        frame = Image.frombytes("RGB", (size, size), result.stdout[offset : offset + frame_bytes])
        x, y = tile % 4 * size, tile // 4 * (size + 24)
        sheet.paste(frame, (x, y))
        ms = round(frame_index * 1000 / FPS)
        timestamps.append(ms)
        side = "before" if frame_index * 1000 / FPS < timestamp else "at/after"
        draw.text((x + 4, y + size + 4), f"{ms} ms {side}", fill="white")
    destination = Path(output_dir) / f"{boundary['id']}.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, quality=80)
    return {
        "path": str(destination),
        "source_id": boundary["source_id"],
        "timestamp_ms": timestamp,
        "boundary_id": boundary["id"],
        "frame_timestamps_ms": timestamps,
    }
