"""Exercise the iOS extractor's shared AVFoundation core on macOS."""
import array
import json
import math
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run(args, check=True, capture_output=True).stdout


def decode(path):
    samples = array.array('f')
    samples.frombytes(run('ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-ar', '16000', '-ac', '1', '-f', 'f32le', '-'))
    return samples


with tempfile.TemporaryDirectory(prefix='editmaxxing-native-clock-') as temporary:
    directory = Path(temporary)
    executable = directory / 'extract-audio'
    run('xcrun', 'swiftc', '-parse-as-library', str(ROOT / 'modules/source-audio/ios/AudioExtractor.swift'), str(ROOT / 'scripts/extract-audio.swift'), '-o', str(executable))
    source = directory / 'source.mov'
    run('ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x284:rate=30:duration=3', '-f', 'lavfi', '-i', 'anoisesrc=color=white:sample_rate=16000:duration=3:seed=177:amplitude=0.2', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'pcm_s16le', str(source))
    audio = directory / 'audio.m4a'
    manifest = json.loads(run(str(executable), str(source), str(audio)))
    reference, output = decode(source), decode(audio)
    correlation = lambda lag: sum(reference[i] * output[i + lag] for i in range(2000, 6000))
    lag = max(range(-512, 513), key=correlation)
    assert lag == 0, f'Decoded audio shifts by {lag} samples'
    assert abs(len(reference) - len(output)) <= 256, 'AAC trailing padding exceeds 16ms'
    assert manifest['timing']['media_origin_ms'] == 0
    assert manifest['timing']['encoder_delay_ms'] == 0
    offset_source = directory / 'offset.mov'
    run('ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x284:rate=30:duration=3', '-itsoffset', '0.2', '-f', 'lavfi', '-i', 'anoisesrc=color=white:sample_rate=16000:duration=2.8:seed=177:amplitude=0.2', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'pcm_s16le', str(offset_source))
    offset_audio = directory / 'offset.m4a'
    offset_manifest = json.loads(run(str(executable), str(offset_source), str(offset_audio)))
    delayed = decode(offset_audio)
    early_rms = math.sqrt(sum(x*x for x in delayed[:1600]) / 1600)
    speech_rms = math.sqrt(sum(x*x for x in delayed[4800:6400]) / 1600)
    assert early_rms < 0.001 and speech_rms > 0.05, 'The 200ms source-track delay must remain audible as leading silence'
    assert offset_manifest['timing']['duration_ms'] == 3000
    print(json.dumps({'runtime': 'macOS AVFoundation shared iOS core', 'alignment_samples': lag, 'reference_samples': len(reference), 'extracted_samples': len(output), 'source_offset_200ms_preserved': True, 'manifest': manifest['timing']}, indent=2))
