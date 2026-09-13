# Synthetic media fixture

`project.json` contains matching source manifests, words, takes, four hook candidates, sixteen static test titles, and the canonical plan in `plan.json`. The timings describe a 12-second body source and an 8-second hook source. The first hook leads the body.

Generate the corresponding test-pattern videos, tone audio, compact audio, and source-backed JSON:

```sh
uv run python scripts/generate_media_fixture.py --output-dir artifacts/contract-fixture
```

The generated `project.json` records checksums for that ffmpeg build’s exact files. Use its manifests when uploading the generated originals. The checked-in JSON supports offline timeline development. Source timestamps, roles, and word IDs match the generated fixture. SHA-256 values identify the generation that produced this checked-in fixture.

These media contain synthetic tones. Select fixture analysis explicitly to exercise the pipeline. The live provider smoke uses synthesized speech with Whisper and Astra.
