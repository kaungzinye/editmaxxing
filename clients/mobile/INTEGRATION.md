# Mobile integration

`App.tsx` presents Vanessa's four-step creator flow. `controller.ts` owns project creation, immutable source registration, concurrent audio/video uploads, job polling, recommendation edits, explicit retake selection, revision-checked body edits and render requests. `native.ts` supplies durable file finalization, AVFoundation inspection and extraction, secure token storage, alternating journal snapshots, and native export sharing.

`clients/shared` is the `@editmaxxing/client` workspace package. The mobile app and endpoint lab share its transport, checksums, resumable original upload, file helpers, journal utilities, and Swift audio module. Install dependencies from the repository root.

## Recommendations and capture

Project `hooks` and `titles` each contain zero to four independent recommendations. Canonical IDs publish after transcript editorial analysis. `recommendations.status` describes availability while body analysis can remain `queued/waiting_video`. Empty or short sets include an evidence-limit reason.

Every suggestion exposes generated wording, current wording, text revision, original rationale revision, curiosity mechanism and validated body word IDs. The UI derives source timestamps and excerpts from project words. Edited wording retains the original rationale and evidence labels. Rendering assesses current pairs against body evidence, including edits, and rejects unsupported, contradictory or repetitive pairs.

Physical cues use the shared four-action whitelist. Switching physical capture mode or changing active capture instructions increments `capture_revision`. Each hook source submits one script with that revision and optional creator-confirmed `action_start_ms`. Each retake receives a new source ID. Matching publishes reviewed candidates; the controller explicitly selects the newest matching source for each hook. Low-confidence matches request a clearer retake. A project permits twenty source recordings, including retakes.

## Rendering and recovery

The controller saves body passages with `base_revision`. A conflict preserves the draft, fetches the saved revision, and offers the saved body or the creator's selected passages applied to it for review.

Render manifests persist a unique request ID before submission. Repeating the same request ID and payload returns the same job and immutable inputs. Each manifest contains pair IDs, plan revision, hook take and capture revision, title revision, output kind, input hash and job ID. Playback requires a succeeded job and a complete match with current inputs. A text edit or retake during rendering leaves that output outside the current preview selection.

Drafts and exports use the same four-second title hold and 300 ms fade. Preview plays the server MP4. Export saving refreshes the signed URL, downloads the MP4, and invokes the native share sheet. A failed download refreshes the URL and retries once.

Restart recovery reads saved source and render job IDs even when interruption occurs before the first status fetch. The upload session's acknowledged parts determine remaining transfers. Audio and video completions merge into the same source journal. Failed or cancelled jobs offer retry using a separate job identity. Original media remains in Documents.

## Verification

Backend integration tests cover recommendations during `waiting_video`, creator edits through body completion, two spoken by three title combinations, immutable render snapshots, request replay, retakes, stale capture rejection, action retention, pair rejection, revision conflicts and cancelled-job recovery. Client tests cover transfer restart, explicit retake selection, lost render responses, current-output matching, signed-URL refresh and body-edit conflicts.

The AVFoundation probe exercises the shared iOS extraction core on macOS using actual media. Camera permissions, physical-device capture, provider editorial quality, perceived cut quality and native share destinations require device acceptance. Synthetic provider tests validate the contract and pipeline mechanics.
