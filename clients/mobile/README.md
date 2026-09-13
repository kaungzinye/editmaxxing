# editmaxxing frontend

A phone-first filming and hook-selection prototype for creators. Built with Expo, React Native, and TypeScript.

## Run locally

Use Node.js 22.13 or newer.

```sh
npm ci
npm run web
```

For the native development workflow, run `npm start`. The `ios` and `android` scripts launch the corresponding development targets when their prerequisites are available.

## Check and build

```sh
npm run typecheck
npm test
npm run build:web
```

The web build is written to `dist/`. To serve it locally:

```sh
python3 -m http.server 8081 --directory dist
```

## Current prototype

- Film → select hooks → film hooks → final videos.
- TikTok-inspired capture layout with native camera recording, video upload, review, and retakes.
- Permission-free demo clips for exploring the entire flow in a browser. Browser camera recording is not implemented; use upload or demo.
- A compact 0–100% body-editing indicator that continues while choosing and recording hooks. It is explicitly simulated, not backend progress.
- Four verbal and four independent on-screen hook options.
- Editable hook text with Save, Cancel, and Restore suggestion controls.
- Brief “Why it works” explanations, original sample-body evidence, and a psychology reference.
- Optional, editable physical hooks controlled by a project-level checkbox.
- Every selected verbal hook pairs with every selected on-screen hook: two × three produces six planned versions.
- Record one take per selected verbal hook. Editing its spoken words or enabled physical action requires a fresh take; editing on-screen text does not.
- Final-video previews with a version selector and independent keep-for-download controls.
- Real source clips can play hook then body. This is an unrendered preview, not a server-edited final video.
- A download sheet that only enables saving when the backend supplies real rendered URLs.
- Browser edits and selections persist on the current device. Native state currently lasts for the running session.

Hook recommendations and editing progress are sample data, including when a real clip is uploaded. Upload here means picking a local video; no media is sent to a server. Backend ingestion, transcription, generation, editing, and rendering are not connected. Demo clips have no media file, so they cannot be exported as videos.

Captured/selected clips and flow progress currently live only in the running session. Refreshing or closing the app loses this session; durable local recording storage and resumable uploads are required before production use. Native camera behavior still needs physical-device validation.

## Files

- `App.tsx`: four-stage flow, hook editing, selections, browser persistence, and progress presentation.
- `CaptureScreen.tsx`: body and hook capture/review interfaces.
- `FinalVideoScreen.tsx`: version previews and download-selection interface.
- `workflow.ts`: clip/take/version types, combination generation, and demo progress schedule.
- `scripts/test-workflow.cjs`: focused workflow checks.
- `hooks.ts`: typed sample recommendations and evidence.
- [HOOK-RULES.md](HOOK-RULES.md): product rules for verbal, on-screen, and optional physical hooks.
- [INTEGRATION.md](INTEGRATION.md): backend handoff and current contract differences.

The included Expo template license notice is retained in `LICENSE`.
