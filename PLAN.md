# editmaxxing build plan

13 September 2026. Build window: 10:30 to 15:30 SGT.

## Product

Tech creators record talking-head footage on a phone, upload, and receive an editable vertical cut. Astra selects takes, organizes spoken hooks and visual hook titles, ranks body lines, and selects caption emphasis. The creator trims and reorders clips in a CapCut-style timeline and exports one 1080x1920 MP4 to Photos.

Target finished length: 90 to 180 seconds, default 120 seconds. The target applies to the assembled talking-head video. Display actual duration and dropped lines. Produce one complete body cut automatically, including substantive content cuts where useful to reach the target. Keep removed material available for the creator to restore.

## Recording and hooks

The creator starts with an optional script in an editable teleprompter or records the body freely. The initial continuous recording contains the body first, then spoken hook attempts separated by a clear pause. It can contain multiple lines, retakes, pauses, and flubs. The app uses the body and those ideas to propose four spoken hook variations. The initial recording includes the creator's spoken hook attempts. Astra writes four spoken hook suggestions grounded in the body and those attempts. The creator edits the four suggestions in the teleprompter and records them in one additional continuous clip, advancing through the suggestions in order. The backend identifies and trims the four hook takes from that clip. Spoken suggestions permit original wording grounded in the recording.

Each spoken hook has four visual hook title variations, giving 16 spoken-hook/title combinations. Vanessa supplies visual title templates with explicit named slots. Astra fills those slots using transcript evidence. The backend assembles the title while preserving the template's fixed wording. A slot without supporting transcript evidence is marked for the creator to fill. Its variation stays out of automatic export until the creator supplies the value. The creator can edit the resulting visual title manually.

The app presents one complete body cut. The creator selects spoken-hook/title combinations to preview and export, each using that shared body cut. A selected combination identifies its spoken hook and visual title. The creator can select any subset of the 16 combinations, with one selected by default. Export produces a separate MP4 for each selected combination. Body editing is available while the creator prepares and records hooks. Attach recorded hooks to the current saved body edit. Prepend the selected spoken hook to the body at timeline zero, regardless of source recording order. Each combination plays its selected hook first, then the shared body. Recalculate body and caption timeline offsets using the selected hook duration. The visual hook title begins at timeline zero.

## Teleprompter

The recording screen supports an optional creator-supplied starting script. A creator can type or paste text, edit it, and read it while recording. Free recording is available from the same flow.

After body analysis, load the four spoken hook suggestions into the teleprompter. The creator can edit their wording before recording. Present one hook at a time with a visible hook number and next control, while recording one continuous clip. Preserve the edited suggestion text for take matching.

Keep the first implementation focused on readable text near the camera, adjustable text size and scroll speed, start/pause scrolling, and recording controls. Per-hook regeneration is stretch work. The editable teleprompter provides the core suggestion-editing control.

## Architecture

- Expo Router app with camera/teleprompter, upload, progress, projects, timeline, playback, and export screens.
- Proposed deployment: FastAPI and ffmpeg in one Railway container, with a persistent volume for project files and job state. Railway hosts the API, processing worker, storage, and renders. Local development runs on the laptop. Confirm hosting after checking account eligibility and resource needs.
- Hosted `whisper-1` transcription with word timestamps. `gpt-6-astra` handles semantic analysis with transcript text and timestamped sampled frames.
- Expo web export provides the judge's deployed app link. Validate native dependencies in Expo Go and verify the EAS Update distribution route on the demo phones.
- The app stores a local project list. The server stores each project's upload, normalized source, words, silence map, analysis, and saved plan.

## Upload and normalization

Prioritize one continuous body recording containing multiple lines and retakes. The initial recording supports up to 20 minutes of footage. Demo capture uses portrait 1080p at 30 fps. Set a separate byte limit from a representative phone file. The project also accepts one additional continuous recording of the four suggested hooks. Stream to disk, enforce the byte limit during upload, and inspect duration with ffprobe. Normalize HEVC, orientation, and variable frame rate into an upright H.264/AAC editing source. All transcript and clip times refer to this source.

Use a 1080x1920 output canvas at 30 fps, center-cropping to fill. Show the same crop in preview. Provider keys live in backend environment variables. Use opaque project access tokens and signed media URLs for the public demo. Set a storage quota and configurable project retention.

## Cut construction

1. Use Whisper for the timestamped transcript. Apply deterministic timestamp and silence rules for mechanical cleanup, with an ffmpeg silence map and RMS envelope. Astra handles semantic cleanup and editorial choices.
2. Astra groups intended lines and takes. Repeated opening phrases can indicate retakes during continuous speech.
3. Sample candidate frames at one per second, with a per-request cap. Astra scores eye contact and energy, selects a take with a gentle last-take preference, and explains the choice.
4. Place boundaries in nearby silence with up to 150 ms padding, clamped to source bounds and neighboring speech.
5. Split interior silence longer than 700 ms into visible clips, retaining 250 ms total around the split. Keep analysis so the dead-space toggle can reconstruct the plan.
6. Rank body lines by necessity, preserve coherent order, and drop whole lines automatically to approach the target duration. Return one complete body cut and a restorable list of dropped lines.
7. Associate four visual title variations with each spoken hook. Build captions from words within the chosen clip ranges.

Changing target duration reuses transcription, take scores, silence data, and visual hook titles. Rerun line ranking and return a proposed plan. Applying a proposal is an explicit action when the timeline contains manual edits.

## Timeline contract

[docs/API.md](docs/API.md) specifies the API. [contracts/plan.ts](contracts/plan.ts) defines the plan and [fixtures/plan.json](fixtures/plan.json) provides synthetic data.

The ordered clip list is the edit. Each clip references a source and half-open source range in integer milliseconds. Timeline positions are cumulative clip durations. Repeated source ranges have distinct clip IDs.

Trim changes source bounds. Reorder changes list order. Automatic captions derive from words overlapping each range, clipped to its bounds and mapped to timeline time. The creator can edit, add, and delete captions. Persist manual edits and deletion records separately from automatic caption generation, then compose them into the canonical saved plan. Anchor manual captions to clip occurrences so they travel with reordered clips. Define partial-trim behavior during implementation. Render captures the saved plan revision and renders that exact clip list.

Build timeline gestures with react-native-gesture-handler and react-native-reanimated. Priority: trim handles, reorder, playhead scrub, hook-text drag, caption drag. Validate gestures against the fixture before upload integration.

Use expo-video for continuous source playback with seeks at clip boundaries and app overlays. Provide a server-rendered 540x960 draft to inspect joins. Export uses one ffmpeg render at 1080x1920, H.264/AAC, 30 fps, and MP4 fast-start metadata.

Verify thumbnail generation and Photos APIs against the installed Expo SDK. Native export downloads the file and requests Photos permission. Web export offers a download.

## Text layout

Start with white heavy captions in a translucent rounded dark box. Use three or four words per chunk, with shorter chunks at punctuation and pauses. Aim for one to two seconds per chunk. Astra selects one existing word for static emphasis.

Reserve approximately 270 px at the top, 480 px at the bottom, and 140 px on the right of the 1080x1920 canvas. These are layout assumptions to validate against the destination app UI.

Place the hook in the upper middle. The default hold is 12 seconds with a 300 ms fade, clamped to output duration. The creator can change the title text and duration, reposition it, or delete it. Place captions above the bottom reserved area. Store text positions as normalized canvas coordinates. Bundle the same font for app and render. Compare rounded-box output visually, since basic ASS boxes use square corners.

## Ownership and checkpoints

- Kaung: upload, storage, transcription, Astra analysis, cut construction, captions, render, then timeline integration.
- Vanessa: Expo screens, camera and teleprompter, gestures, playback, projects, visual hook title UI, visual title templates, web deployment.
- By 11:00: agree on the contract, verify model access, select the Expo SDK, and confirm Railway storage.
- By 12:30: backend processes short footage, app edits fixture data, visual hook title selection is ready.
- By 13:30: connect upload, job polling, plan save, and render. Deploy.
- By 14:30: test phone and web export, caption alignment, project reload, and errors.
- By 15:20: record the demo and verify public links in a signed-out browser.
- By 15:30: submit deployed app, public GitHub repository, and public 90-second video.

## Acceptance checks

- A continuous body recording produces one complete body cut and four spoken hook proposals, each with four slot-filled visual title options.
- Starting-script and free-recording flows both reach body analysis. The hook teleprompter presents four editable suggestions and captures their takes.
- Body edits remain available during hook preparation and persist when recorded hooks attach.
- Hooks recorded after the body play at the start of preview and export. Switching hooks places the selected hook before the body and recalculates body and caption offsets.
- Any selected subset of the 16 combinations produces separate MP4 files using the saved body cut.
- Selected combinations reuse the body cut. Manual title and caption edits, additions, and deletions survive save and render.
- Trim and reorder survive reload and appear in the export.
- Captions align after clips move, shrink, or repeat. Hook text begins at timeline zero.
- Target changes expose dropped lines and actual duration.
- Oversized, overlong, and unreadable uploads produce actionable errors. Interrupted jobs support retry.
- Native export saves to Photos. Web export downloads a playable MP4.
- The public judge flow includes a labeled sample project using permitted footage.

## 90-second demo

1. 0:00 to 0:10: continuous body footage with retakes and pauses. State the editing problem.
2. 0:10 to 0:25: upload, complete body cut, and four spoken hook proposals.
3. 0:25 to 0:40: select a spoken hook and one of its four visual titles and choose a target duration. Show dropped lines.
4. 0:40 to 1:00: trim, reorder, and play the captioned edit on the phone.
5. 1:00 to 1:15: export and play the MP4 from Photos.
6. 1:15 to 1:30: explain Astra's take grouping, frame scores, ranking, visual hook titles, and emphasis selections.

## Implementation prerequisites

- A project API key with verified `gpt-6-astra` access. The task environment has no `OPENAI_API_KEY` configured.
- Vanessa's visual hook title templates and permitted talking-head footage. Kaung settles the filming schedule.
- Measure a representative portrait 1080p/30 phone file to set the byte limit.
- Use the caption default specified above for implementation.
- Railway and Expo deployment access.

The product scope is settled. Implementation choices use the defaults in this plan. Stretch work after the core flow passes: per-hook suggestion regeneration, color controls, sounds, and general multi-file body uploads.
