# API contract

Routes use `/api/v1`. JSON uses snake_case and integer milliseconds. IDs are opaque strings. Capture one body recording and one separate source per spoken-hook take. Probe each file, finalize its original in durable local storage, register the immutable source, then upload extracted audio and original video concurrently. Both transfers use the source's canonical timestamp mapping.

## Routes

| Method and route | Request | Response |
| --- | --- | --- |
| `POST /projects` | JSON project name and `target_duration_ms` | 201 with `project_id` and `project_token` |
| `POST /projects/{id}/sources` | JSON immutable source ID, role, duration, media fingerprint, timestamp manifest, optional ordered hook IDs and edited suggestions | 201 with source ID |
| `PUT /projects/{id}/sources/{source_id}/audio` | Compact audio file, checksum, extraction timing manifest | 202 with analysis job ID |
| `POST /projects/{id}/sources/{source_id}/video/uploads` | Expected original size and checksum | 201 with resumable upload ID and part size |
| `GET /projects/{id}/sources/{source_id}/video/uploads/{upload_id}` | Project authorization | Acknowledged parts, transfer state, and expiry |
| `PUT /projects/{id}/sources/{source_id}/video/uploads/{upload_id}/parts/{part}` | Part bytes and checksum | Acknowledged part, idempotent for matching content |
| `POST /projects/{id}/sources/{source_id}/video/uploads/{upload_id}/complete` | Ordered part manifest | 202 for whole-file verification and normalization |
| `GET /jobs/{id}` | Project bearer token | Job state, stage, progress, result or error |
| `GET /projects/{id}` | Project bearer token | Sources, words, analysis, hook candidates, current plan |
| `POST /projects/{id}/analysis` | Project bearer token | 202 with job ID, supports analysis retry |
| `PUT /projects/{id}/plan` | `base_revision`, `plan` | Canonical saved plan with incremented revision |
| `POST /projects/{id}/rank` | `base_revision`, target duration, selected hook ID, dead-space setting | 202 with job ID, result contains proposed plan |
| `POST /projects/{id}/renders` | `plan_revision`, `kind` of draft or export, selected combinations | 202 with job ID |
| `DELETE /projects/{id}` | Project authorization after explicit deletion choice | 202 with deletion job ID covering project work and remote files |
| `GET /healthz` | Empty | 200 when storage and worker are available, otherwise 503 |

The app stores project IDs and tokens locally. Hash tokens on the server. Serve media through expiring signed URLs that native and web video players can open. Refresh URLs by fetching the project. Provider credentials stay on the backend.

## Job behavior

States: `queued`, `running`, `succeeded`, `failed`, `cancelled`. Source audio and video upload readiness are tracked independently from job state. Stages include `normalize`, `transcribe`, `analyze`, `waiting_video`, `review_boundaries`, `plan`, `render`. Progress is an estimate between 0 and 1. Poll every two seconds while the app is active.

Transcript editorial analysis publishes canonical recommendations before video review. `recommendations.status` becomes `ready` with stable project hook and title IDs. Body analysis initializes an empty timeline after video normalization and cut review. Subsequent analysis returns a proposal with its base revision. Hook analysis updates candidate records independently. Ranking returns a proposed plan and its base revision. Rendering returns a signed URL, expiration, output kind, and rendered plan revision. Persist job state. On worker restart, mark interrupted work failed with a retryable error. Run one worker for the hackathon deployment.

## Plan rules

- Target finished duration is an integer from 90000 to 180000 ms, default 120000.
- Source ranges are half-open and satisfy `0 <= start < end <= source duration`.
- Every source, line, take, and word reference belongs to the project. Clip IDs are unique.
- Project `hooks` and `titles` contain independent sets of zero to four choices. A short set includes `recommendations.short_set_reason`. Each recommendation includes generated wording, current wording, text revision, original rationale revision, curiosity mechanism, rationale and body `evidence_word_ids`. `selected_visual_title_id` references a project title. Optional templates apply once to the body title set and require supported slots.
- Spoken hooks use fewer than twelve words with estimated natural delivery under three seconds. Capture scripts include `capture_revision` and a creator-confirmed `action_start_ms` when physical capture is enabled. Text changes and enabled action changes increment the capture revision and clear take selection. Rendering requires a reviewed candidate for that revision. The confirmed action remains continuous through the first spoken word.
- Render pair checks assess current wording against body evidence and reject unsupported claims, contradiction and substantial repetition. Pair decisions cache exact wording and evidence. Explicit creator overlays with a null title ID remain creator-authored text.
- The ordered clip list controls rendering. Repeated ranges represent distinct clip occurrences.
- On save, the server derives duration and target status from clip ranges. Generate automatic captions, then apply persisted creator edits, additions, and deletions. Caption words overlap the source range and their timing is clamped to its bounds, then offset into the assembled timeline.
- Automatic captions group continuous speech into three or four words, balancing six words as 3+3 and ten as 4+3+3. Gaps longer than 700 ms and clip boundaries separate groups; short clips and unavoidable remainders use fewer words. Every canonical caption word carries assembled `start_ms` and `end_ms` in a half-open interval. Source-linked manual words inherit transcript timing, clipped to the edit and clip bounds. Words outside those bounds drop from the cue; the saved edit retains them for further trimming. Creator words with a null transcript ID carry null timing.
- The `spoken_outline` preset draws white TikTok Sans text with a black outline and transparent background. Every word uses white fill for the full caption interval. `emphasis_word_id` records editorial metadata. The server accepts `classic_box` in deployed saved plans and canonicalizes caption styling to `spoken_outline` on save and render.
- Captions occupy a single lane. Manual edits take priority over automatic cues during their source-anchored ranges. Later entries in `caption_edits`, including deletions, take priority when manual ranges overlap. Automatic cues split around manual intervals, with word timing clipped to each visible segment. Balance automatic groups into three or four words between long pauses.
- Text positions identify the block center in normalized canvas coordinates. Clamp the full block inside the output canvas.
- Reject a stale `base_revision` with 409. Applying a ranking proposal uses the save-plan route and its base revision.
- Ranking reuses stored analysis. The dead-space option reconstructs visible clip splits in the proposal.

Save edits before requesting a render. Reject a render request for a revision that differs from the current saved plan with 409. Capture an immutable plan snapshot when queuing the job. Return that revision with the output so the app can identify exports that differ from current edits.

Draft: 540x960. Export: 1080x1920. Both use 30 fps, H.264, AAC, and MP4 fast-start. Trim audio and video together, reset timestamps per clip, and concatenate in plan order. Include silence for sources without audio.

## Errors and limits

Errors use `{ "error": { "code": "invalid_plan", "message": "Clip c_1 ends beyond the source.", "retryable": false } }` with an optional request ID. Keep provider errors and secrets in server logs.

Stream multi-minute raw uploads to disk. Accept initial recordings up to 20 minutes. Apply a configurable limit to the additional hook recording. Confirm the byte limit against representative footage. Return 413 for byte limits and 422 for invalid media or footage exceeding the configured source-duration limit. Retain acknowledged upload parts for the declared resume window, then expire abandoned parts. Rate-limit public uploads and analysis, enforce a disk quota, configure explicit web CORS origins, and display a configurable retention period beside upload. The demo processing-copy retention is 24 hours. Local originals remain in durable app storage until explicit deletion. Durable remote backup has a separate declared policy and restore capability.

The synthetic fixture contains clip and caption data. Integration supplies the corresponding source media, full transcript, and hook analysis.

## Editor and hook workflow details

Body analysis chooses two IDs from a catalogue of 20 worked examples. A separate hook-writing
request receives those examples and the transcript words retained by the initial body selection.
The `generate_hooks` job stage follows body analysis. Recommendation metadata includes `example_ids`
and `policy_version`. The backend stores body decisions before generation so retries reuse them.
See [HOOK-GENERATION.md](HOOK-GENERATION.md) for the library and evaluation workflow.

Transcript analysis publishes independent grounded recommendations while body video uploads. Record selected spoken hooks separately, each with one script. Matching appends reviewed candidates. Select a retake explicitly through the hook update route.

Templates accept exactly four records before recommendations publish. With an empty template list, the provider generates independent grounded titles. Persist title edits through `PUT /projects/{id}/titles/{title_id}` with `text` and `base_revision`. Original rationale and evidence remain associated with their generated revision.

The plan holds body cuts, captions and creator overlays. The default overlay hold is 4000 ms with a 300 ms fade. Set `use_title: false` to omit the title. Draft and export use the same assembly settings.

## Teleprompter and concurrent body editing

Starting scripts and teleprompter preferences are editable app state. Hook recording submits ordered hook IDs and the creator's edited suggestion text alongside footage so matching uses the words the creator intends to say.

Hook ingestion attaches recorded takes to the project's hook candidates and preserves the current saved body clip list. Keep body editing available during hook preparation. Applying a hook selection uses the plan revision check. Each render request accepts any nonempty subset of valid spoken-hook/title combinations, with unique combination IDs. Produce one MP4 per selection and associate every output with its combination and captured body revision.

## Hook placement

Generated recommendations include `evidence_spans`, `payoff_word_ids` and `question_opened`.
Each evidence span is consecutive within the source; a recommendation can cite several spans.
The flat `evidence_word_ids` list exposes their combined evidence. Exports require generated
payoff passages to survive intact in timeline order, returning `422 payoff_missing` when an
answer is cut. Semantic assessment receives retained body words, including for spoken-only
openings and creator overlays. Its cache includes the body clips and policy version.

Each assembled combination orders the selected recorded hook clips first, starting at timeline zero, followed by the saved body clips. Source recording order is independent of playback order. Selecting another hook replaces the leading hook clips and preserves body clip order and source ranges. Recompute body and caption timeline offsets from the selected hook duration. Anchor the visual hook title to timeline zero. Apply the same assembly rule to phone preview, draft render, and each exported combination.

## Media identity and readiness

Source roles are `body` and `hooks`. Store separate audio and video upload checksums plus the captured recording fingerprint and extraction manifest. Both derivatives belong to the same source identity. Validate their durations and timestamp mappings, including start offsets and encoder delay, before enabling server rendering. A mismatched upload returns an actionable media error. Persist partial upload state and support retry without repeating successful analysis. Immutable source replacements receive new source IDs.

The initial 20-minute duration cap applies to the registered body source and is verified against uploaded media. Enforce byte caps during each upload. Local playback maps canonical clip times back to device media time. Server normalization provides its mapping to that same canonical clock.

Render requests with unavailable required video return a retryable `media_pending` conflict. The UI keeps editing available and displays upload progress. Existing ready hook/body combinations can render independently of unrelated source uploads.

## Proposals and concurrency

Source analysis is immutable and keyed by source fingerprint, extraction configuration, and analysis version. AI output references word and take IDs. The server compiles and validates clip ranges deterministically.

Each proposal stores an ID, source analysis references, and `base_revision`. Initial draft creation uses an atomic empty-timeline check. Later proposals require an explicit apply action through the revision-checked save route. Return 409 when the base revision differs from the saved timeline. The client presents the proposal for review against current edits. Hook candidate updates and delivery feedback have separate records and preserve the user timeline.

Caption overrides and deletion records belong to the saved edit. Render snapshots include selected source ranges, body revision, hook take IDs, overlays, captions, and audio settings. Optional visual scoring and feedback can complete independently of render readiness.

## Audio and delivery feedback

Persist `audio.normalization_enabled` and `audio.preset` on the plan. The `speech_consistent` preset measures speech levels, applies bounded hook/body gain matching, and normalizes assembled audio with true-peak control. Keep duration and sample alignment stable. Cache measurements by immutable audio identity and analyzed range. Changes to edit ranges or audio settings invalidate assembled-output measurements.

Delivery feedback references hook take ID and body revision, includes measured evidence, confidence, and a suggested action. Compare the hook with the opening body passage using speaking rate, pauses, and acoustic measurements. Supply measured features and transcript context to Astra. Frame observations can enrich feedback when available. A volume difference alone requires recording-level context before interpreting performance.

Return feedback through project state as advisory results. Keep, play-transition, and record-again are creator actions. Body-opening changes mark associated feedback stale. Reuse source measurements for recomputation. Audio normalization and delivery feedback operate independently.

## Originals, resumable transfers, and recovery

The client finalizes and stores captured originals in durable app storage before analysis. Persist a local project journal and edit revisions independently of network calls. On launch, reconcile finalized files with source records and resume acknowledged uploads. Camera recording state distinguishes recording, finalizing, and saved. Segment checkpoints require verified native recording behavior and a common logical source timeline.

The server retains captured originals separately from normalized derivatives. Each upload session belongs to an immutable source ID and validates expected byte count, per-part checksums, and the assembled checksum. Retries with matching content are idempotent. Return a conflict for mismatching content under an existing part number. Persist acknowledged offsets or parts and upload expiry. Whole-original verification gates the source's verified-original state. Normalization has its own readiness state.

Expose storage metadata independently of AI job state: verified original checksum, verified byte count, verification timestamp, remote copy kind of `processing` or `durable_backup`, retention expiry, and restore capability. Durable backup may be marked complete only when the full original, source metadata, and recoverable project record are persisted under the declared retention policy. The app derives Saved on this phone from its local finalized-file state. Backed up additionally requires durable remote verification and a supported restore route. Temporary server media uses Uploaded for processing and an expiry label.

Project tokens support the demo processing API. Account-linked project discovery and authorized restore, or an equivalently recoverable identity mechanism, are prerequisites for cloud backup that survives app reinstall. Specify and test that capability before enabling durable-backup status or local-media eviction. A 24-hour processing copy supports the temporary render flow.

Routine cleanup targets derivatives, cache, and expired processing copies. The client retains local originals while cloud copies are temporary. Free device space requires verified durable storage and restore authorization, retaining the local project manifest for download on demand. Delete original checks dependent edits and requires an explicit source-deletion action. Removing a clip from a plan changes the plan alone.

Project deletion creates a tombstone, cancels work, and queues remote media and metadata deletion. Workers and upload finalization check the tombstone before publishing results. Return 202 with a deletion job ID and report success after remote deletion finishes. The client coordinates local deletion from the user's stated scope and persists pending remote deletion for retry. Expiry and deletion invalidate media access. Captured recordings shared across edits require dependency-aware deletion.

## Implemented transport and response fields

Send `Authorization: Bearer <project_token>` on project, source, and job requests. Project creation returns `{project_id, project_token, expires_at}`. Expiry values are Unix timestamps in seconds. Times inside media manifests and plans are integer milliseconds.

Audio and part uploads contain raw bytes with `Content-Type: application/octet-stream` and `X-Content-SHA256`, the lowercase SHA-256 of that request's bytes. Audio also sends `X-Timing-Manifest` containing a compact JSON timing manifest. Its SHA-256 describes the extracted audio. The source `fingerprint` and original upload `sha256` both describe the full captured original.

```json
{
  "source_id": "src_body_1",
  "role": "body",
  "duration_ms": 10000,
  "fingerprint": "<64 lowercase SHA-256 hex characters>",
  "timing": {
    "media_origin_ms": 0,
    "encoder_delay_ms": 0,
    "duration_ms": 10000,
    "sample_rate": 48000,
    "extractor": "original"
  },
  "hook_scripts": []
}
```

`timing.duration_ms` equals the registered source duration. The separate audio manifest describes decoded extracted audio. Its mapping is `canonical_ms = decoded_media_ms + media_origin_ms - encoder_delay_ms`. AAC packet priming and container duration can differ from decoded media. The AVFoundation adapter reports zero encoder delay because decoding applies its AAC skip-sample metadata. Server audio normalization measures decoded samples and preserves leading source silence.

Create an original upload with `{size_bytes, sha256}`. The response and upload GET contain `{upload_id, part_size, size_bytes, sha256, parts, state, expires_at}`. Parts use zero-based numbers and contain `{part, sha256, size_bytes}`. Acknowledged parts are authoritative. Verify their hashes against the selected local file, send missing ranges, and complete with `{parts: [{part: 0, sha256: "..."}, ...]}` in ascending order.

Queued operations return `{job_id}`. Project analysis retry also returns `job_ids` when it queues work for several sources. Job GET contains `id`, `project_id`, `state`, `stage`, `progress`, `result`, and `error`. It also exposes `kind` and timestamps. Cancellation uses state `cancelled`. Poll queued and running work while the app is active.

Project GET returns `project_id`, `name`, `sources`, `words`, `analysis`, `takes`, `hooks`, `titles`, `recommendations`, `templates`, `proposals`, `feedback`, `outputs`, `plan`, and `expires_at`. `sources` and `takes` are ID-keyed objects. `analysis` uses an immutable analysis hash as its key; each record contains its source ID. Source records expose separate `audio_state`, `video_state`, and `storage`. Verified processing storage contains `original_verified`, `sha256`, `size_bytes`, `verified_at`, `copy_kind: "processing"`, `expires_at`, and `restore_capable: false`. Available media has `{url, expires_at}` under `raw_audio_media`, `audio_media`, `editing_media`, or `original_media`.

A proposal contains `{id, base_revision, analysis_refs, plan}`. Apply it through plan save with `{base_revision, plan, proposal_id}`. A canonical plan includes `caption_edits`; each manual edit identifies `clip_id`, a source-time range, replacement word IDs, creator words, and a deletion flag. The source anchors apply to one clip occurrence and survive reorder operations. Save returns the canonical plan directly.

A spoken hook contains `id`, `proposed_text`, `generated_text`, `text_revision`, `rationale_revision`, `mechanism`, `rationale`, `evidence_word_ids`, `validation`, `movement`, `action_enabled`, `capture_revision`, `take_id`, `candidates`, and `clips`. Project titles share the recommendation fields and expose `text`, `template_id`, `slots` and `missing_slots`. Candidates include `capture_revision`, `take_id`, `source_id`, `confidence`, `reason` and reviewed `clips`.

Render requests accept an optional `request_id` for durable retry. Repeating that ID with identical payload returns the same `{job_id, inputs}`. Reusing it for a different payload returns `409 request_conflict`. Each input contains combination ID, take ID, capture revision, title revision and `input_hash`. Outputs also contain `render_job_id`, `plan_revision`, `kind`, metadata, URL and expiry. Clients attach outputs only after job success and a complete match with current request inputs. Project GET refreshes signed URLs.

| Additional route | Request and behavior |
| --- | --- |
| `PUT /projects/{id}/templates` | `{templates: [{id, pattern, slots}, ...]}`, exactly four supplied templates |
| `PUT /projects/{id}/hooks/{hook_id}` | `proposed_text`, `movement`, `action_enabled`, `base_revision`, or selected candidate `take_id` |
| `PUT /projects/{id}/titles/{title_id}` | `text` and `base_revision` persist a title revision |
| `POST /jobs/{id}/retry` | Failed or cancelled work queues a separate job with the captured inputs |
| `POST /jobs/{id}/cancel` | Cancel queued or running work; deletion completes through its own job |
| `GET /projects/{id}/sources/{source_id}/dependencies` | Current clip IDs, saved revisions, and hook references |
| `DELETE /projects/{id}/sources/{source_id}?confirm=true` | Explicit original deletion after inspecting dependencies; active use returns a conflict |
| `POST /projects/{id}/sources/{source_id}/fixture` | Enable synthetic analysis for a registered source before audio upload; requires `ENABLE_FIXTURES=true` |

Fixture mode labels synthetic transcript and editorial output explicitly. Its upload verification, normalization, canonical plan handling, and rendering process real media. The endpoint lab walkthrough and native validation boundaries are in [CLIENT.md](CLIENT.md).

## Integrated cut boundary review

Audio upload starts transcription and editorial selection. An analysis job with `state=queued` and `stage=waiting_video` retains its transcript and editorial results while the original uploads. Video normalization resumes that same job automatically. Clients start audio and video uploads together and poll the analysis job through `review_boundaries` to `succeeded` before displaying the initial draft. Waiting jobs support cancellation and survive process restart.

For each candidate clip start and end, the worker extracts four frames before and four at/after the boundary at 30 fps. Each contact sheet labels canonical source times. Astra receives nearby transcript words, selection reasons, cut positions, allowed adjustment ranges and the contact sheets in batches of up to 16 boundaries. Code accepts adjustments within 120 ms that preserve included words, exclude neighboring speech and respect adjacent clip ranges. Decisions below 0.7 confidence and out-of-range adjustments retain the candidate and set `needs_review=true`. Captions and timeline duration derive from the adjusted clips.

Both body analysis and recorded-hook matching run this review before publishing their clips. Duration ranking reviews generated body candidates. `POST /visual-review` reviews the body boundaries in its captured plan and returns a proposal for explicit application. Boundary-review results are cached by source identity, timing, transcript context, candidate ranges and model. The project `boundary_reviews` map contains decisions, applied times, confidence, reasons and sampled timestamps. Frames are temporary processing files.
