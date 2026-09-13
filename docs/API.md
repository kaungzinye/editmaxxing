# API contract

Implementation specification. Routes use `/api/v1`. JSON uses snake_case and integer milliseconds. IDs are opaque strings. Project creation prioritizes one continuous body recording. Specify additional hook recording routes after confirming how spoken proposals become footage. Each uploaded file gets a normalized editing source.

## Routes

| Method and route | Request | Response |
| --- | --- | --- |
| `POST /projects` | Multipart `file`, `target_duration_ms` | 202 with `project_id`, `project_token`, `job_id` |
| `GET /jobs/{id}` | Project bearer token | Job state, stage, progress, result or error |
| `GET /projects/{id}` | Project bearer token | Sources, words, analysis, hook candidates, current plan |
| `POST /projects/{id}/analysis` | Project bearer token | 202 with job ID, supports analysis retry |
| `PUT /projects/{id}/plan` | `base_revision`, `plan` | Canonical saved plan with incremented revision |
| `POST /projects/{id}/rank` | `base_revision`, target duration, selected hook ID, dead-space setting | 202 with job ID, result contains proposed plan |
| `POST /projects/{id}/renders` | `plan_revision`, `kind` of draft or export, selected combinations | 202 with job ID |
| `DELETE /projects/{id}` | Project bearer token | 204 after canceling work and deleting project files |
| `GET /healthz` | Empty | 200 when storage and worker are available, otherwise 503 |

The app stores project IDs and tokens locally. Hash tokens on the server. Serve media through expiring signed URLs that native and web video players can open. Refresh URLs by fetching the project. Provider credentials stay on the backend.

## Job behavior

States: `queued`, `running`, `succeeded`, `failed`. Stages: `normalize`, `transcribe`, `analyze`, `plan`, `render`. Progress is an estimate between 0 and 1. Poll every two seconds while the app is active.

Analysis returns a project ID and saved plan revision. Ranking returns a proposed plan and its base revision. Rendering returns a signed URL, expiration, output kind, and rendered plan revision. Persist job state. On worker restart, mark interrupted work failed with a retryable error. Run one worker for the hackathon deployment.

## Plan rules

- Target finished duration is an integer from 90000 to 180000 ms, default 120000.
- Source ranges are half-open and satisfy `0 <= start < end <= source duration`.
- Every source, line, take, and word reference belongs to the project. Clip IDs are unique.
- Each of four spoken hooks owns four visual title variations. `selected_visual_title_id` must belong to `selected_hook_id`. Leading hook clips reference the selected spoken take. Each title references a Vanessa-supplied template through `template_id`. Astra returns explicit slot values grounded in the transcript. The backend validates slot names and preserves fixed template wording when assembling titles. Manual title edits are creator-authored overrides. Each selected export combination uses the shared body cut.
- The ordered clip list controls rendering. Repeated ranges represent distinct clip occurrences.
- On save, the server derives duration and target status from clip ranges. Generate automatic captions, then apply persisted creator edits, additions, and deletions. Caption words overlap the source range and their timing is clamped to its bounds, then offset into the assembled timeline.
- Each automatic caption has one to four words and one emphasis word from that chunk. Manual captions support creator-authored text and optional emphasis. Prefer three or four words, splitting at punctuation or pauses.
- Text positions identify the block center in normalized canvas coordinates. Clamp the full block inside the output canvas.
- Reject a stale `base_revision` with 409. Applying a ranking proposal uses the save-plan route and its base revision.
- Ranking reuses stored analysis. The dead-space option reconstructs visible clip splits in the proposal.

Save edits before requesting a render. Reject a render request for a revision that differs from the current saved plan with 409. Capture an immutable plan snapshot when queuing the job. Return that revision with the output so the app can identify exports that differ from current edits.

Draft: 540x960. Export: 1080x1920. Both use 30 fps, H.264, AAC, and MP4 fast-start. Trim audio and video together, reset timestamps per clip, and concatenate in plan order. Include silence for sources without audio.

## Errors and limits

Errors use `{ "error": { "code": "invalid_plan", "message": "Clip c_1 ends beyond the source.", "retryable": false } }` with an optional request ID. Keep provider errors and secrets in server logs.

Stream multi-minute raw uploads to disk. Expect 10 to 20 minutes of body footage, with a provisional 20-minute ceiling. Confirm the byte limit against representative footage. Return 413 for byte limits and 422 for invalid media or footage exceeding the configured source-duration limit. Clean up partial uploads. Rate-limit public uploads and analysis, enforce a disk quota, configure explicit web CORS origins, and display a configurable retention period beside upload. Start with 24 hours for the demo.

The synthetic fixture contains clip and caption data. Integration supplies the corresponding source media, full transcript, and hook analysis.

## Editor and hook workflow details

The initial analysis produces a complete body cut and four spoken hook proposals based on the body and creator ideas. A proposal may await recorded footage. Hook acquisition and its endpoints depend on the recording decision.

Store visual title template IDs and slot values with analysis. The plan holds the creator's editable overlay. A null overlay represents deletion. `hold_ms` is editable and defaults to 12000. Each render request selects one or more spoken-hook/title combinations and creates an output for each against the captured body revision.

Caption editing requires persisted overrides and deletion records, anchored to clip occurrences, alongside automatic captions. User-added caption words may have null transcript word IDs. The save implementation must preserve these edits when deriving captions. The shared types describe canonical captions, with the edit-request schema to be specified during implementation.
