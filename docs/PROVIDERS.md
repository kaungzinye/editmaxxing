# AI providers

The backend uses `whisper-1` for word timestamps and `gpt-6-astra` for editorial choices, recorded hook matching, and advisory delivery feedback. Credentials belong in the backend environment.

```dotenv
OPENAI_API_KEY=your-project-key
EDITOR_MODEL=gpt-6-astra
ENABLE_FIXTURES=false
```

The OpenAI project needs billing and access to both models. The factory validates the exact editor model and reports `provider_unconfigured` when the key is empty. The worker persists successful transcription and source analysis so timeline changes can reuse them. `PROMPT_VERSION` identifies the editorial prompt configuration.

## Transcription and time

The provider requests `response_format="verbose_json"` and `timestamp_granularities=["word"]`. Word timestamps use `whisper-1`, as described in the [OpenAI file transcription guide](https://developers.openai.com/api/docs/guides/speech-to-text). The extracted audio file must fit the provider's 24 MB limit. Compact mono audio covers the 20-minute source limit.

`transcribe(audio_path, source_id, timing, duration_ms)` maps each word to the project's canonical clock with `canonical_ms = round(provider_seconds * 1000) + media_origin_ms - encoder_delay_ms`. The normalized-audio worker supplies a zero-origin manifest. Stable word IDs include a hash of the source ID and transcript position. Validation checks finite, ordered timestamps and source bounds. Rounding overshoot within 250 ms is clamped to the source; larger discrepancies fail analysis for timing review.

## Editorial decisions

The Responses API uses `responses.parse`, Pydantic strict schemas, `reasoning.effort="low"`, and `store=false`. Astra supports structured outputs and image input in its [model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra). The SDK parsing form follows [OpenAI structured outputs guidance](https://developers.openai.com/api/docs/guides/structured-outputs).

`analyze(words, templates, target_duration_ms, frames=None)` groups takes by intended line, chooses a complete body take per line, scores line necessity, identifies caption emphasis, and returns four spoken hook suggestions. Each take references consecutive words in one source. Validation checks identifiers, source order, overlap, selected takes, emphasis, and title templates before clip construction.

Supply four visual templates with declared `{slot}` names. A hook gets one title choice per template. An empty template list supports body analysis and spoken suggestions while template entry remains pending. `assemble_title(choice, template, words)` assembles the template's fixed wording. A supported slot uses a verbatim phrase from consecutive cited words. Unsupported values become visible `{slot}` placeholders with `missing_slots` and `ready=false`; the creator supplies their text before export. The returned `slots` dictionary records the accepted values.

`match_hooks(words, scripts)` uses the creator's edited suggestion text and recording order. Each supplied hook ID receives one assessment. Matched takes use distinct consecutive words. An unmatched hook receives an empty word list and zero confidence. The API exposes confidence for creator review.

`feedback(context, frames=None)` accepts measured pace, pauses, audio levels and dynamics, transcript context, and the assessed hook/body identity. It returns concise advice, confidence, and `keep_take`, `play_transition`, or `record_again`. The worker owns body-revision and hook-take association. Volume comparisons account for microphone placement and recording gain.

Optional `frames` entries contain `path`, `source_id`, and canonical `timestamp_ms`. Each request includes at most eight images of up to 512 KiB each, sent as low-detail image inputs with timestamp labels. Frame selection belongs to the media layer. Results remain reviewable proposals through the API's revision controls.

## Errors and limits

The SDK allows two retries for eligible connection and service errors, a 10-second connection timeout, and a 90-second request timeout. Responses have a 32,000-token output cap. Invalid or incomplete structured output becomes a retryable `provider_invalid_response` error. Authentication and model-access errors require backend configuration. Rate-limit errors are retryable.

Client-visible errors use fixed messages. Provider logs contain the exception category and HTTP status. Response bodies, credentials, and transcript text stay outside these error messages and logs.

## Explicit synthetic fixtures

`get_provider(settings, fixture=True)` requires `ENABLE_FIXTURES=true`. Normal audio requests select `OpenAIProvider`. The dedicated fixture endpoint identifies synthetic analysis on its source record, and the worker selects `FixtureProvider` for that explicit source.

`fixture_words(source_id, duration_ms=12000, role="body")` provides declared word timing for synthetic test media. Body lines are "Clear audio holds attention.", "Trim pauses between ideas.", and "Put your hook first." Each line occupies 72% of an equal source segment, beginning 12% into the segment. Each word occupies 82% of its allocated interval. The hooks role supplies four separate lines. Timing scales with the registered media duration, so short integration recordings remain inside their source bounds.

Fixture decisions and feedback carry synthetic labels. Fixture template slots require creator values, while static templates can provide complete test titles. Fixture checks prove the API, source timing, revision, and render pipeline. A live speech/model check uses uploaded spoken footage and the configured OpenAI account.

Run provider validation checks with:

```sh
uv run pytest backend/tests/test_provider.py -q
```

## Live verification

On 13 September 2026, the configured OpenAI account passed a complete provider check using synthetic macOS speech. `whisper-1` returned 32 words from a 10.657-second body recording. `gpt-6-astra` returned four body takes, four spoken hook suggestions, and 16 titles whose slots passed transcript-evidence validation. A separate 16.891-second hook recording produced 41 words and four hook matches with confidence scores of 1.0, 1.0, 0.8, and 1.0. Delivery feedback referenced the measured pace difference and recommended playing the transition. The full check took 52 seconds.

The local `artifacts/provider-live/` directory contains the generated audio, timestamped transcripts, structured results, and `report.json`. This ignored directory keeps verification media outside source control. The check proves live transcription and structured output integration on the configured account; rendered timing and device playback have their own acceptance checks.

The full HTTP smoke check passes 17 checks in 100.1 seconds against the local API. It creates an audio-first body draft, saves a trim/reorder/manual-caption edit, verifies stale-revision rejection, attaches recorded hooks while preserving the saved body, verifies both chunked original uploads, and downloads two 540x960 drafts plus one 1080x1920 export. Each MP4 uses H.264/AAC at 30 fps and carries the captured plan revision. Project reload and advisory feedback retain that revision. Outputs and the report are in `artifacts/api-smoke-live/`. The explicit fixture mode passes the same 17 checks with the endpoint client's nested manifests and measured decoded-audio timing; its report is in `artifacts/api-smoke-fixture-v2/`.

## Media preparation and smoke commands

Prepare one finalized original for the endpoint lab:

```sh
uv run python scripts/prepare_media.py /path/to/recording.mov --output-dir artifacts/prepared
```

The command creates compact mono AAC audio plus JSON containing the original fingerprint, source registration, audio checksum, and timing manifests. It preserves the original file. A hooks source accepts `--role hooks --hook-scripts /path/to/scripts.json`, where the JSON contains edited `hook_id` and `text` pairs from the current project.

Run the live provider and render check against a configured API:

```sh
uv run python scripts/smoke.py --synthetic --base-url http://127.0.0.1:8000
```

The synthetic mode uses macOS `say` for spoken input. It creates a test project and writes its local recovery token into a permission-restricted `session.json` inside the output directory. Add `--fixture` to request deterministic fixture analysis on a backend with `ENABLE_FIXTURES=true`. The `--timeout` option bounds the full workflow, with a 900-second default.

## Container deployment

`Dockerfile` installs the locked Python dependencies and ffmpeg, bundles TikTok Sans Bold from the backend package, and launches one Uvicorn worker on the `PORT` environment variable. `STORAGE_ROOT=/data` holds project records, upload parts, originals, and renders. The image build excludes local credentials and media artifacts.

Configure the Railway service dashboard to use the repository Dockerfile, a `/healthz` startup check, and one replica. Attach a persistent volume at `/data`, set `OPENAI_API_KEY`, and set `PUBLIC_BASE_URL` to the service's public HTTPS URL. Set `CORS_ORIGINS` to the exact Expo web origins. The volume needs space for originals, temporary uploads, normalized sources, and renders; set `STORAGE_QUOTA_BYTES` to the chosen capacity. The [Railway volume guide](https://docs.railway.com/volumes) describes volume attachment. This service keeps its deployment configuration in the dashboard.

Build the container locally with `docker build -t editmaxxing .`. The packaging check verifies app startup, bundled TikTok Sans, ffmpeg subtitle/loudness filters, and project recovery through a container restart using a mounted data directory.

## Cut boundary decisions

`review_boundaries(boundaries, frames)` returns a strict `BoundaryReview` with one decision per boundary. Each decision identifies the boundary, an integer canonical timestamp, confidence and a brief reason. Each frame input is a labeled eight-frame contact sheet with its boundary ID and exact timestamps. A request contains at most 16 sheets, uses low image detail and low reasoning effort, and caps text output at 5,000 tokens. Frame extraction uses four concurrent workers and one short video decode per boundary. Identical review requests reuse cached results.

The worker enforces word coverage and adjustment limits independently of the model. Visual judgments concern visible movement; source word timestamps supply the speech constraints. Uncertain decisions are exposed for creator playback.
