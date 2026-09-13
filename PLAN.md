# editmaxxing build plan

13 September 2026. Build window: 10:30 to 15:30 SGT.

## Product

Tech creators record talking-head footage on a phone, upload, and receive an editable vertical cut. Astra selects takes, organizes spoken hooks and visual hook titles, ranks body lines, and selects caption emphasis. The creator trims and reorders clips in a CapCut-style timeline and exports one 1080x1920 MP4 to Photos.

Target finished length: 90 to 160 seconds. The target applies to the assembled talking-head video. Display actual duration and dropped lines. Treat the target as a whole-line editing goal. Report when essential content exceeds it. Confirm whether 180 seconds should also be available, as the recording discussion includes that output length.

## Recording and hooks

Film four distinct spoken hooks first, then the body with retakes. Astra identifies hook candidates before the first body line and groups takes of each intended line.

Each of the four spoken hooks has four visual hook title variations, giving 16 spoken-hook/title combinations. A visual hook is the on-screen opening title. Spoken content comes from the recording. Vanessa supplies the visual hook title templates. Astra uses those templates to produce four title variations for each spoken hook, grounded in the recording. Confirm how much of each template Astra may change. Take-selection reasons appear in the editor.

Select a spoken hook, then one of its four visual title variations. Keep each title attached to its parent spoken hook. Confirm whether export produces one selected combination or a batch of variations.

## Architecture

- Expo Router app with upload, progress, projects, timeline, playback, and export screens.
- Proposed deployment: FastAPI and ffmpeg in one Railway container, with a persistent volume for project files and job state. Railway hosts the API, processing worker, storage, and renders. Local development runs on the laptop. Confirm hosting after checking account eligibility and resource needs.
- Hosted `whisper-1` transcription with word timestamps. `gpt-6-astra` handles semantic analysis with transcript text and timestamped sampled frames.
- Expo web export provides the judge's deployed app link. Validate native dependencies in Expo Go and verify the EAS Update distribution route on the demo phones.
- The app stores a local project list. The server stores each project's upload, normalized source, words, silence map, analysis, and saved plan.

## Upload and normalization

Raw footage spans multiple minutes and includes all hooks, retakes, pauses, and flubs needed for the finished edit. Set upload duration and byte limits independently from finished-video duration. Confirm the expected longest recording, file size, and whether a project accepts one recording or several files. Stream to disk, enforce the byte limit during upload, and inspect duration with ffprobe. Normalize HEVC, orientation, and variable frame rate into an upright H.264/AAC editing source. All transcript and clip times refer to this source.

Use a 1080x1920 output canvas at 30 fps, center-cropping to fill. Show the same crop in preview. Provider keys live in backend environment variables. Use opaque project access tokens and signed media URLs for the public demo. Set a storage quota and configurable project retention.

## Cut construction

1. Transcribe words and compute an ffmpeg silence map with an RMS envelope.
2. Astra groups intended lines and takes. Repeated opening phrases can indicate retakes during continuous speech.
3. Sample candidate frames at one per second, with a per-request cap. Astra scores eye contact and energy, selects a take with a gentle last-take preference, and explains the choice.
4. Place boundaries in nearby silence with up to 150 ms padding, clamped to source bounds and neighboring speech.
5. Split interior silence longer than 700 ms into visible clips, retaining 250 ms total around the split. Keep analysis so the dead-space toggle can reconstruct the plan.
6. Rank body lines by necessity, preserve coherent order, and drop whole lines to approach the target duration.
7. Associate four visual title variations with each spoken hook. Build captions from words within the chosen clip ranges.

Changing target duration reuses transcription, take scores, silence data, and visual hook titles. Rerun line ranking and return a proposed plan. Applying a proposal is an explicit action when the timeline contains manual edits.

## Timeline contract

[docs/API.md](docs/API.md) specifies the API. [contracts/plan.ts](contracts/plan.ts) defines the plan and [fixtures/plan.json](fixtures/plan.json) provides synthetic data.

The ordered clip list is the edit. Each clip references a source and half-open source range in integer milliseconds. Timeline positions are cumulative clip durations. Repeated source ranges have distinct clip IDs.

Trim changes source bounds. Reorder changes list order. Captions derive from the words overlapping each range, clipped to its bounds and mapped to timeline time. Server save returns canonical captions and duration. Render captures the saved plan revision and renders that exact clip list.

Build timeline gestures with react-native-gesture-handler and react-native-reanimated. Priority: trim handles, reorder, playhead scrub, hook-text drag, caption drag. Validate gestures against the fixture before upload integration.

Use expo-video for continuous source playback with seeks at clip boundaries and app overlays. Provide a server-rendered 540x960 draft to inspect joins. Export uses one ffmpeg render at 1080x1920, H.264/AAC, 30 fps, and MP4 fast-start metadata.

Verify thumbnail generation and Photos APIs against the installed Expo SDK. Native export downloads the file and requests Photos permission. Web export offers a download.

## Text layout

Start with white heavy captions in a translucent rounded dark box. Use three or four words per chunk, with shorter chunks at punctuation and pauses. Aim for one to two seconds per chunk. Astra selects one existing word for static emphasis.

Reserve approximately 270 px at the top, 480 px at the bottom, and 140 px on the right of the 1080x1920 canvas. These are layout assumptions to validate against the destination app UI.

Place the hook in the upper middle. Hold for 12 seconds and fade over 300 ms, clamped to output duration. Place captions above the bottom reserved area. Store text positions as normalized canvas coordinates. Bundle the same font for app and render. Compare rounded-box output visually, since basic ASS boxes use square corners.

## Ownership and checkpoints

- Kaung: upload, storage, transcription, Astra analysis, cut construction, captions, render, then timeline integration.
- Vanessa: Expo screens, gestures, playback, projects, visual hook title UI, web deployment.
- By 11:00: agree on the contract, verify model access, select the Expo SDK, and confirm Railway storage.
- By 12:30: backend processes short footage, app edits fixture data, visual hook title selection is ready.
- By 13:30: connect upload, job polling, plan save, and render. Deploy.
- By 14:30: test phone and web export, caption alignment, project reload, and errors.
- By 15:20: record the demo and verify public links in a signed-out browser.
- By 15:30: submit deployed app, public GitHub repository, and public 90-second video.

## Acceptance checks

- Footage with four spoken hooks and body retakes produces four visual title options per hook and selected-take reasons.
- Trim and reorder survive reload and appear in the export.
- Captions align after clips move, shrink, or repeat. Hook text begins at timeline zero.
- Target changes expose dropped lines and actual duration.
- Oversized, overlong, and unreadable uploads produce actionable errors. Interrupted jobs support retry.
- Native export saves to Photos. Web export downloads a playable MP4.
- The public judge flow includes a labeled sample project using permitted footage.

## 90-second demo

1. 0:00 to 0:10: phone footage with hooks, retakes, and pauses. State the editing problem.
2. 0:10 to 0:25: upload, analysis result, and selected-take reasons.
3. 0:25 to 0:40: select a spoken hook and one of its four visual titles and choose a target duration. Show dropped lines.
4. 0:40 to 1:00: trim, reorder, and play the captioned edit on the phone.
5. 1:00 to 1:15: export and play the MP4 from Photos.
6. 1:15 to 1:30: explain Astra's take grouping, frame scores, ranking, visual hook titles, and emphasis selections.

## Remaining inputs

- A project API key with verified `gpt-6-astra` access. The task environment has no `OPENAI_API_KEY` configured.
- Vanessa's visual hook title templates and permitted talking-head footage. Kaung settles the filming schedule.
- Output upper bound of 160 or 180 seconds, longest raw upload, single or multiple source files, and single or batch export.
- Exact caption reference. The default above supports initial layout work.
- Railway and Expo deployment access.

Stretch work after the core flow passes: color controls and sounds. Confirm batch hook export scope during the product interview.
