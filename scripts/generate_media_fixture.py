#!/usr/bin/env python3
"""Generate labeled synthetic source videos and compact-audio manifests."""

import argparse
import json
import subprocess
from pathlib import Path

from editmaxxing.editing import assemble_combination, clips_for_take, compile_draft
from editmaxxing.models import HookScript, Template
from editmaxxing.provider import FixtureProvider, assemble_title, fixture_words
from prepare_media import prepare


def generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests = {}
    for role, duration, count, frequency in (("body", 12, 3, 440), ("hooks", 8, 4, 660)):
        section = duration / count
        windows = "+".join(
            f"between(t,{section * (i + 0.12):.3f},{section * (i + 0.84):.3f})" for i in range(count)
        )
        audio = f"aevalsrc=0.1*sin(2*PI*{frequency}*t)*({windows}):s=48000:d={duration}"
        path = output_dir / f"synthetic-{role}.mp4"
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
                f"testsrc2=s=360x640:r=30:d={duration}",
                "-f",
                "lavfi",
                "-i",
                audio.replace(",", "\\,"),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(path),
            ],
            check=True,
        )
        manifests[role] = prepare(path, output_dir / role, source_id=f"source_{role}", role=role)
    provider = FixtureProvider()
    sources = {m["source"]["source_id"]: m["source"] for m in manifests.values()}
    body_words = fixture_words("source_body", 12000)
    hook_words = fixture_words("source_hooks", 8000, role="hooks")
    words = [w.model_dump() for w in body_words + hook_words]
    templates = [
        Template(id=f"fixture_title_{i + 1}", pattern=text, slots=[])
        for i, text in enumerate(
            [
                "Clear audio holds attention",
                "Trim pauses between ideas",
                "Put your hook first",
                "Clear audio, sharper ideas",
            ]
        )
    ]
    editorial = provider.analyze(body_words, templates)
    takes = {t.id: t.model_dump() for t in editorial.takes}
    titles = [
        {"id": f"title_fixture_{i + 1}", **assemble_title(choice.template, templates[i], body_words)}
        for i, choice in enumerate(editorial.titles)
    ]
    hooks = []
    scripts = [
        HookScript(hook_id=f"hook_fixture_{i + 1}", text=h.proposed_text)
        for i, h in enumerate(editorial.hooks)
    ]
    matches = provider.match_hooks(hook_words, scripts)
    for i, (hook, match) in enumerate(zip(editorial.hooks, matches.matches)):
        take = {
            "id": f"hook_take_fixture_{i + 1}",
            "line_id": f"hook_line_fixture_{i + 1}",
            "word_ids": match.word_ids,
            "role": "hook",
            "source_id": "source_hooks",
            "selected": True,
            "score": 100,
            "reason": "Synthetic fixture timing",
            "emphasis_word_ids": [],
        }
        takes[take["id"]] = take
        hooks.append(
            {
                "id": scripts[i].hook_id,
                "proposed_text": hook.proposed_text,
                "take_id": take["id"],
                "capture_revision": 1,
                "clips": clips_for_take(take, words, sources),
            }
        )
    sources["source_hooks"]["hook_scripts"] = [x.model_dump() for x in scripts]
    plan = compile_draft(words, editorial.model_dump(), sources)
    plan = assemble_combination(
        plan,
        hooks[0],
        titles[0],
        {
            "id": "fixture_combination",
            "hook_id": hooks[0]["id"],
            "visual_title_id": titles[0]["id"],
            "use_title": True,
        },
        words,
        sources,
        takes,
    )
    project = {
        "fixture": True,
        "media": "Generated test patterns and tones",
        "sources": sources,
        "words": words,
        "takes": takes,
        "hooks": hooks,
        "titles": titles,
        "templates": [t.model_dump() for t in templates],
        "plan": plan,
    }
    (output_dir / "project.json").write_text(json.dumps(project, indent=2) + "\n")
    (output_dir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    (output_dir / "README.txt").write_text(
        "Synthetic timing fixture. Video uses a generated test pattern; audio uses tones. Fixture analysis requires ENABLE_FIXTURES=true and explicitly selects the fixture provider. Provider-backed transcription uses recorded speech.\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(".local-media"))
    args = parser.parse_args()
    generate(args.output_dir)
    print(f"Synthetic body and hooks: {args.output_dir.resolve()}")
