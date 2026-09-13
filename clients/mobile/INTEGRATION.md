# Frontend handoff to Kaung

This frontend lives at `clients/mobile/` in the shared repository. It does not replace the backend or `clients/endpoint-lab/`.

## Creator flow

1. Film or pick the body video and confirm the take.
2. Go directly to hook selection. Start body processing concurrently; do not make the creator wait for body editing to finish before interacting with available hooks.
3. Film one short take for each selected verbal hook. Physical actions are optional and part of that take, never an independent export dimension.
4. Preview the Cartesian product of selected verbal and selected on-screen hooks. Keep any subset of versions for download.

Recommendations still need transcript analysis before they can be truly grounded. The current sample hooks are labeled and are not generated from an uploaded clip. In production, show recommendation-loading/retry states independently of body-edit progress.

## Current boundaries

- `workflow.ts` defines `Clip`, `HookTake`, `VideoVersion`, and `EditProgress`.
- `App.tsx` starts `demoProgress()` at body confirmation. Replace that timer with actual job state. Screen changes must not restart the job.
- Fingerprints include spoken words and the enabled physical action. Changed words/action invalidate the recorded take. On-screen edits do not invalidate audio/video takes.
- Source playback is a local preview. Only set `VideoVersion.renderUri` after a real render succeeds for the current combination and plan revision.
- The final sheet exposes a Save action for each actual rendered URL. Batch ZIP/download orchestration and native photo-library saving are not implemented.
- Camera files and selected media are session-only. Finalize recordings into durable app storage and persist the project journal before production use. Do not label processing uploads as backups.

## Existing backend contract

Verified against upstream `docs/API.md`, `contracts/plan.ts`, and job routes at `0b3806ee347b9677c7a08fcf035fd071c59fe2be`.

- Register immutable sources using `POST /api/v1/projects/{id}/sources`, then submit audio/video through the documented separate upload routes. The current frontend does not extract audio or upload media.
- Poll `GET /api/v1/jobs/{id}` every two seconds while active, with the project bearer token. Job fields include `state`, `stage`, `progress`, `result`, and `error`.
- Backend progress is **0–1**, frontend percent is **0–100**. Clamp the conversion, distinguish queued/running/succeeded/failed/cancelled, and display completion only on success. Replace the demo badge with live status only once connected. Surface actionable error/retry states.
- Persist changes through revision-checked `PUT /api/v1/projects/{id}/plan` before requesting `POST /api/v1/projects/{id}/renders`.
- Render results include `plan_revision` and outputs with combination IDs, signed URLs, and expiry. Associate outputs with the exact combination and revision; refresh expired media via project GET.
- Keep provider credentials on the server. Project authorization tokens must use appropriate native secure storage rather than the hook-editor browser storage.

## Contract differences to resolve

The requested frontend has **four global verbal choices and four independent on-screen choices**. The current backend attaches four visual titles to each spoken hook and validates title ownership. Do not send frontend Cartesian pairs blindly to that API. Agree on a global-title adapter or update the backend ownership model while preserving grounding and creator edits.

The backend documents one continuous additional hook recording with ordered hook IDs; this UI captures one take per selected hook. Adapt source registration/matching to those separate takes, or deliberately change capture orchestration without altering the creator-facing selection rules.

No backend files were changed in this frontend branch.
