# API contract

Implementation specification. Routes use `/api/v1`. JSON uses snake_case and integer milliseconds. IDs are opaque strings. Project creation prioritizes one continuous body recording. The initial recording contains the body first and spoken hook attempts afterward. The app supports an optional editable starting script in its teleprompter. A second continuous recording supplies the four suggested spoken hooks. Register every recording before extracting audio. Audio and video belong to the same immutable source and canonical timestamp mapping.

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

States: `queued`, `running`, `succeeded`, `failed`. Source audio and video upload readiness are tracked independently from job state. Stages: `normalize`, `transcribe`, `analyze`, `plan`, `render`. Progress is an estimate between 0 and 1. Poll every two seconds while the app is active.

Initial analysis returns the body draft and hook suggestions together and initializes an empty timeline once. Subsequent analysis returns a proposal with its base revision. Hook analysis updates candidate records independently. Ranking returns a proposed plan and its base revision. Rendering returns a signed URL, expiration, output kind, and rendered plan revision. Persist job state. On worker restart, mark interrupted work failed with a retryable error. Run one worker for the hackathon deployment.

## Plan rules

- Target finished duration is an integer from 90000 to 180000 ms, default 120000.
- Source ranges are half-open and satisfy `0 <= start < end <= source duration`.
- Every source, line, take, and word reference belongs to the project. Clip IDs are unique.
- Each of four spoken hooks owns four visual title variations. `selected_visual_title_id` must belong to `selected_hook_id`. Leading hook clips reference the selected spoken take. Each title references a Vanessa-supplied template through `template_id`. Astra returns explicit slot values grounded in the transcript. The backend validates slot names and preserves fixed template wording when assembling titles. Manual title edits are creator-authored overrides. Each selected export combination uses the shared body cut.
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

The initial analysis produces a complete body cut and four spoken hook proposals based on the body and creator ideas. Astra writes grounded spoken suggestions with original wording. The creator edits suggestions in the teleprompter and records all four in one additional continuous clip. Register it with source role `hooks` and upload its audio and video separately. The analysis job matches recorded takes to suggestions and exposes uncertain matches for creator correction. Hook proposals have a null take ID until footage is matched.

Store visual title template IDs, slot values, and missing slot names with analysis. A slot without supporting transcript evidence requires creator input. Exclude incomplete variations from automatic export and validate readiness on render requests. The plan holds the creator's editable overlay. A null overlay represents deletion. `hold_ms` is editable and defaults to 12000. Each render request selects one or more spoken-hook/title combinations and creates an output for each against the captured body revision.

Caption editing persists overrides and deletion records anchored to clip occurrences alongside automatic captions. `caption_edits[].words` contains `word_id` and `text`; the server derives timing for canonical `captions[].words`. User-added caption words may have null transcript word IDs. Save preserves these edits when deriving captions. The shared types describe both canonical captions and source-anchored caption edits.

## Teleprompter and concurrent body editing

Starting scripts and teleprompter preferences are editable app state. Hook recording submits ordered hook IDs and the creator's edited suggestion text alongside footage so matching uses the words the creator intends to say.

Hook ingestion attaches recorded takes to the project's hook candidates and preserves the current saved body clip list. Keep body editing available during hook preparation. Applying a hook selection uses the plan revision check. Each render request accepts any nonempty subset of valid spoken-hook/title combinations, with unique combination IDs. Produce one MP4 per selection and associate every output with its combination and captured body revision.

## Hook placement

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

Project GET returns `project_id`, `name`, `sources`, `words`, `analysis`, `takes`, `hooks`, `templates`, `proposals`, `feedback`, `outputs`, `plan`, and `expires_at`. `sources` and `takes` are ID-keyed objects. `analysis` uses an immutable analysis hash as its key; each record contains its source ID. Source records expose separate `audio_state`, `video_state`, and `storage`. Verified processing storage contains `original_verified`, `sha256`, `size_bytes`, `verified_at`, `copy_kind: "processing"`, `expires_at`, and `restore_capable: false`. Available media has `{url, expires_at}` under `raw_audio_media`, `audio_media`, `editing_media`, or `original_media`.

A proposal contains `{id, base_revision, analysis_refs, plan}`. Apply it through plan save with `{base_revision, plan, proposal_id}`. A canonical plan includes `caption_edits`; each manual edit identifies `clip_id`, a source-time range, replacement word IDs, creator words, and a deletion flag. The source anchors apply to one clip occurrence and survive reorder operations. Save returns the canonical plan directly.

A spoken hook contains `id`, `proposed_text`, `take_id`, `visual_titles`, `candidates`, and `clips`. A recorded candidate contains `{take_id, source_id, confidence, reason}`. Render job results contain `{plan_revision, outputs}`. Each output includes `combination_id`, `plan_revision`, `hook_take_id`, `kind`, `metadata`, `url`, and `expires_at`. Fetching the project refreshes output URLs.

| Additional route | Request and behavior |
| --- | --- |
| `PUT /projects/{id}/templates` | `{templates: [{id, pattern, slots}, ...]}`, exactly four supplied templates |
| `PUT /projects/{id}/hooks/{hook_id}` | Edited `proposed_text`, selected candidate `take_id`, or both |
| `POST /jobs/{id}/cancel` | Cancel queued or running work; deletion completes through its own job |
| `GET /projects/{id}/sources/{source_id}/dependencies` | Current clip IDs, saved revisions, and hook references |
| `DELETE /projects/{id}/sources/{source_id}?confirm=true` | Explicit original deletion after inspecting dependencies; active use returns a conflict |
| `POST /projects/{id}/sources/{source_id}/fixture` | Enable synthetic analysis for a registered source before audio upload; requires `ENABLE_FIXTURES=true` |

Fixture mode labels synthetic transcript and editorial output explicitly. Its upload verification, normalization, canonical plan handling, and rendering process real media. The endpoint lab walkthrough and native validation boundaries are in [CLIENT.md](CLIENT.md).
