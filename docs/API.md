# API contract

Implementation specification. Routes use `/api/v1`. JSON uses snake_case and integer milliseconds. IDs are opaque strings. Confirm single-file or multi-file uploads before implementing project creation. Each uploaded file gets a normalized editing source.

## Routes

| Method and route | Request | Response |
| --- | --- | --- |
| `POST /projects` | Multipart `file`, `target_duration_ms` | 202 with `project_id`, `project_token`, `job_id` |
| `GET /jobs/{id}` | Project bearer token | Job state, stage, progress, result or error |
| `GET /projects/{id}` | Project bearer token | Sources, words, analysis, hook candidates, current plan |
| `POST /projects/{id}/analysis` | Project bearer token | 202 with job ID, supports analysis retry |
| `PUT /projects/{id}/plan` | `base_revision`, `plan` | Canonical saved plan with incremented revision |
| `POST /projects/{id}/rank` | `base_revision`, target duration, selected hook ID, dead-space setting | 202 with job ID, result contains proposed plan |
| `POST /projects/{id}/renders` | `plan_revision`, `kind` of draft or export | 202 with job ID |
| `DELETE /projects/{id}` | Project bearer token | 204 after canceling work and deleting project files |
| `GET /healthz` | Empty | 200 when storage and worker are available, otherwise 503 |

The app stores project IDs and tokens locally. Hash tokens on the server. Serve media through expiring signed URLs that native and web video players can open. Refresh URLs by fetching the project. Provider credentials stay on the backend.

## Job behavior

States: `queued`, `running`, `succeeded`, `failed`. Stages: `normalize`, `transcribe`, `analyze`, `plan`, `render`. Progress is an estimate between 0 and 1. Poll every two seconds while the app is active.

Analysis returns a project ID and saved plan revision. Ranking returns a proposed plan and its base revision. Rendering returns a signed URL, expiration, output kind, and rendered plan revision. Persist job state. On worker restart, mark interrupted work failed with a retryable error. Run one worker for the hackathon deployment.

## Plan rules

- Target finished duration is an integer from 90000 to 160000 ms. Confirm whether the upper bound includes 180000 ms before implementation.
- Source ranges are half-open and satisfy `0 <= start < end <= source duration`.
- Every source, line, take, and word reference belongs to the project. Clip IDs are unique.
- Each of four spoken hooks owns four visual title variations. `selected_visual_title_id` must belong to `selected_hook_id`. Leading hook clips reference the selected spoken take. Each title references a Vanessa-supplied template through `template_id`. Astra bases the title on that template and the recording. Confirm permitted template edits and batch-export behavior.
- The ordered clip list controls rendering. Repeated ranges represent distinct clip occurrences.
- On save, the server derives duration, target status, and captions from clip ranges. Caption words overlap the source range and their timing is clamped to its bounds, then offset into the assembled timeline.
- Each caption has one to four words and one emphasis word from that chunk. Prefer three or four words, splitting at punctuation or pauses.
- Text positions identify the block center in normalized canvas coordinates. Clamp the full block inside the output canvas.
- Reject a stale `base_revision` with 409. Applying a ranking proposal uses the save-plan route and its base revision.
- Ranking reuses stored analysis. The dead-space option reconstructs visible clip splits in the proposal.

Save edits before requesting a render. Reject a render request for a revision that differs from the current saved plan with 409. Capture an immutable plan snapshot when queuing the job. Return that revision with the output so the app can identify exports that differ from current edits.

Draft: 540x960. Export: 1080x1920. Both use 30 fps, H.264, AAC, and MP4 fast-start. Trim audio and video together, reset timestamps per clip, and concatenate in plan order. Include silence for sources without audio.

## Errors and limits

Errors use `{ "error": { "code": "invalid_plan", "message": "Clip c_1 ends beyond the source.", "retryable": false } }` with an optional request ID. Keep provider errors and secrets in server logs.

Stream multi-minute raw uploads to disk. Set configurable byte and source-duration limits after confirming expected footage size. Return 413 for byte limits and 422 for invalid media or footage exceeding the configured source-duration limit. Clean up partial uploads. Rate-limit public uploads and analysis, enforce a disk quota, configure explicit web CORS origins, and display a configurable retention period beside upload. Start with 24 hours for the demo.

The synthetic fixture contains clip and caption data. Integration supplies the corresponding source media, full transcript, and hook analysis.
