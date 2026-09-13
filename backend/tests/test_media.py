import math
import shutil
import struct
import subprocess
import wave
from array import array

import pytest
from editmaxxing.media import (
    MediaError,
    audio_metrics,
    normalize_audio,
    normalize_video,
    render_plan,
    silence_detect,
    write_subtitles,
)
from editmaxxing.models import Plan

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg and ffprobe are required"
)


def ffmpeg(*args):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
        check=True,
        capture_output=True,
    )


def write_wave(path, duration_ms, audible_start=0, audible_end=None, amplitude=0.1):
    rate = 48000
    audible_end = duration_ms if audible_end is None else audible_end
    samples = array(
        "h",
        (
            round(amplitude * 32767 * math.sin(2 * math.pi * 440 * sample / rate))
            if audible_start <= sample / 48 < audible_end
            else 0
            for sample in range(duration_ms * 48)
        ),
    )
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(samples.tobytes())


def create_video(path, audio_path, duration_ms, color="red"):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=320x240:r=30:d={duration_ms / 1000}",
        "-i",
        audio_path,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        path,
    )


def timing(duration_ms, origin=0, delay=0):
    return {
        "duration_ms": duration_ms,
        "media_origin_ms": origin,
        "encoder_delay_ms": delay,
        "sample_rate": 48000,
        "extractor": "fixture",
    }


def clip(id, source, start, end, role="body"):
    return {
        "id": id,
        "source_id": source,
        "line_id": id,
        "take_id": id,
        "role": role,
        "source_start_ms": start,
        "source_end_ms": end,
        "selection_reason": "Fixture",
    }


def test_canonical_audio_clock_applies_origin_and_delay_at_sample_boundaries(tmp_path):
    raw = tmp_path / "raw.wav"
    write_wave(raw, 2200, audible_start=400, audible_end=1800)
    output = tmp_path / "canonical.wav"
    result = normalize_audio(raw, output, timing(2200, origin=100, delay=300), 2000)
    assert result["duration_ms"] == 2000
    assert result["timing"]["canonical_shift_ms"] == -200
    with wave.open(str(output), "rb") as file:
        samples = array("h", file.readframes(file.getnframes()))
    assert len(samples) == 96000
    first = next(i for i, value in enumerate(samples) if abs(value) > 100)
    assert abs(first / 48 - 200) < 1
    metrics = audio_metrics(output)
    assert metrics["silences"][0]["end_ms"] == pytest.approx(200, abs=2)
    assert metrics["rms_dbfs"] is not None
    assert metrics["true_peak_dbtp"] < 0


def test_audio_manifest_mismatch_rejects_and_aac_priming_decodes_once(tmp_path):
    raw, aac, output = (tmp_path / name for name in ("raw.wav", "compact.m4a", "canonical.wav"))
    write_wave(raw, 3000, audible_start=400)
    ffmpeg("-i", raw, "-c:a", "aac", "-ar", "16000", "-b:a", "48k", aac)
    result = normalize_audio(aac, output, timing(3000), 3000)
    assert result["duration_ms"] == 3000
    assert audio_metrics(output)["silences"][0]["end_ms"] == pytest.approx(400, abs=15)
    with pytest.raises(MediaError, match="timing manifest"):
        normalize_audio(aac, output, timing(2000), 2000)


def test_positive_origin_prepends_canonical_silence(tmp_path):
    raw, output = tmp_path / "raw.wav", tmp_path / "out.wav"
    write_wave(raw, 1000)
    normalize_audio(raw, output, timing(1000, origin=300), 1300)
    silent = silence_detect(output)
    assert silent[0]["start_ms"] == 0
    assert silent[0]["end_ms"] == pytest.approx(300, abs=2)


def test_video_normalization_handles_rotation_and_silent_sources(tmp_path):
    raw, rotated, output = (tmp_path / name for name in ("raw.mp4", "rotated.mp4", "editing.mp4"))
    ffmpeg("-f", "lavfi", "-i", "color=blue:s=320x240:r=24:d=1", "-c:v", "libx264", raw)
    movie = bytearray(raw.read_bytes())
    track_header = movie.index(b"tkhd")
    assert movie[track_header + 4] == 0
    matrix_offset = track_header + 44
    movie[matrix_offset : matrix_offset + 36] = struct.pack(
        ">9i", 0, 65536, 0, -65536, 0, 0, 0, 0, 1073741824
    )
    rotated.write_bytes(movie)
    result = normalize_video(rotated, output, timing(1000), 1000)
    assert (result["width"], result["height"]) == (240, 320)
    assert result["rotation"] == 0
    assert result["fps"] == 30
    assert result["video_codec"] == "h264" and result["audio_codec"] == "aac"
    assert audio_metrics(output)["rms_dbfs"] is None


def test_render_allocates_frames_globally_and_matches_hook_body_levels(tmp_path):
    quiet, loud = tmp_path / "quiet.wav", tmp_path / "loud.wav"
    write_wave(quiet, 4000, amplitude=0.08)
    write_wave(loud, 4000, amplitude=0.16)
    body_video, hook_video = tmp_path / "body.mp4", tmp_path / "hook.mp4"
    create_video(body_video, loud, 4000, "blue")
    create_video(hook_video, quiet, 4000, "red")
    sources = {
        "body": {"duration_ms": 4000, "editing_path": str(body_video), "audio_path": str(loud)},
        "hook": {"duration_ms": 4000, "editing_path": str(hook_video), "audio_path": str(quiet)},
    }
    plan = Plan(revision=9).model_dump()
    plan["clips"] = [
        clip("hook", "hook", 13, 1014, "hook"),
        clip("b1", "body", 20, 1021),
        clip("b2", "body", 1111, 2112),
        clip("b3", "body", 2011, 3012),
    ]
    plan["duration_ms"] = 4004
    plan["captions"] = [
        {
            "id": "caption",
            "clip_id": "hook",
            "start_ms": 100,
            "end_ms": 800,
            "words": [{"word_id": "w1", "text": "TikTok"}, {"word_id": "w2", "text": "captions"}],
            "emphasis_word_id": "w2",
        }
    ]
    plan["hook_overlay"] = {
        "text": "A measured edit",
        "position": {"x": 0.44, "y": 0.24},
        "hold_ms": 2000,
        "fade_ms": 300,
    }
    output = tmp_path / "draft.mp4"
    result = render_plan(plan, sources, output)
    assert (result["width"], result["height"], result["fps"]) == (540, 960, 30)
    assert result["video_frame_count"] == 120
    assert result["audio_duration_ms"] == 4004
    assert abs(result["duration_ms"] - 4004) <= 34
    assert result["plan_revision"] == 9
    assert result["audio"]["role_gains_db"]["hook"] == 6
    first = audio_metrics(output, 150, 850)
    second = audio_metrics(output, 1200, 1900)
    assert abs(first["rms_dbfs"] - second["rms_dbfs"]) < 1
    assert result["audio"]["measurement"]["true_peak_dbtp"] <= -1.2
    assert abs(result["audio"]["measurement"]["integrated_lufs"] + 16) < 1
    assert b"moov" in output.read_bytes()[:4096]
    # Pixel evidence distinguishes the leading hook from the body after the join.
    pixels = []
    for second in (0.05, 1.15):
        process = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(second),
                "-i",
                str(output),
                "-frames:v",
                "1",
                "-vf",
                "crop=2:2:0:0,format=rgb24",
                "-f",
                "rawvideo",
                "-",
            ],
            check=True,
            capture_output=True,
        )
        pixels.append(tuple(process.stdout[:3]))
    assert pixels[0][0] > pixels[0][2] + 100
    assert pixels[1][2] > pixels[1][0] + 100


def test_export_canvas_and_audio_toggle(tmp_path):
    audio, video, output = (tmp_path / name for name in ("audio.wav", "video.mp4", "export.mp4"))
    write_wave(audio, 1200, amplitude=0.04)
    create_video(video, audio, 1200)
    plan = Plan().model_dump()
    plan.update(clips=[clip("a", "s", 0, 1000)], duration_ms=1000)
    plan["audio"]["normalization_enabled"] = False
    result = render_plan(
        plan,
        {"s": {"duration_ms": 1200, "editing_path": str(video), "audio_path": str(audio)}},
        output,
        "export",
    )
    assert (result["width"], result["height"]) == (1080, 1920)
    assert result["audio"]["measurement"]["rms_dbfs"] == pytest.approx(
        audio_metrics(audio, 0, 1000)["rms_dbfs"], abs=0.2
    )


def test_subtitle_uses_bundled_tiktok_font_rounded_box_and_clamped_hold(tmp_path):
    plan = Plan().model_dump()
    plan.update(
        duration_ms=2000,
        hook_overlay={
            "text": "Title at the edge",
            "position": {"x": 0, "y": 0},
            "hold_ms": 12000,
            "fade_ms": 300,
        },
    )
    content = write_subtitles(plan, tmp_path / "captions.ass").read_text()
    assert "Style: Text,TikTok Sans," in content
    assert "0:00:02.00" in content and "0:00:12.00" not in content
    assert "\\fad(0,300)" in content and "\\p1" in content
