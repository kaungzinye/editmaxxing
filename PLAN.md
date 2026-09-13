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

Prioritize one continuous body recording containing multiple lines and retakes. The initial recording supports up to 20 minutes of footage. Demo capture uses portrait 1080p at 30 fps. Set a separate byte limit from a representative phone file. The project also accepts one additional continuous recording of the four suggested hooks. Stream to disk, enforce the byte limit during upload, and inspect duration with ffprobe. Normalize HEVC, orientation, and variable frame rate into an upright H.264/AAC editing source. Assign source IDs and a canonical media time origin before extraction. Preserve explicit timestamp mappings between captured video, extracted audio, and the server editing source. All transcript and clip ranges use canonical source time.

Use a 1080x1920 output canvas at 30 fps, center-cropping to fill. Show the same crop in preview. Provider keys live in backend environment variables. Use opaque project access tokens and signed media URLs for the public demo. Set a storage quota and configurable project retention.

## Original footage and recovery

Each project has an Originals library and an Edits view. Original recordings live in durable private app storage. Edits contain source references, clip ranges, captions, and effects. AI operations, timeline trims, and removal of clips change edit instructions while originals remain available. Save original to Photos is an explicit optional action. Final exports retain the save-to-Photos flow.

Immediately after recording stops, finalize the video, place it in durable app storage, and persist its source ID and project record before starting analysis. Save edit revisions locally as the creator works and synchronize them separately from media uploads. On app launch, reconcile finalized recording files, project records, and upload state so an interrupted save can recover completed footage. Keep originals through app restarts, offline sessions, failed uploads, and analysis failures.

Present recording storage status with plain language:

- Saved on this phone: the finalized original and project record are stored locally.
- Backing up, with percentage: a resumable upload is storing the full original under the durable backup policy.
- Backed up: the server has verified the full original and the project has a supported restore route and retention policy.
- Uploaded for processing, with expiry: the server holds a temporary working copy. The local original remains the recovery copy.

Audio and transcript readiness are separate from original-video protection. A backup requires a verified full-resolution original, its metadata, and a recoverable project record. Keep the captured original alongside server-generated editing media. Verify upload size and checksum before marking it complete. Resume interrupted uploads from acknowledged parts. Schedule background transfer where the mobile platform permits it, persist the queue, and resume on foreground launch. Show paused or failed transfer status truthfully.

For the hackathon, prioritize durable local originals, saved-project recovery, verified resumable transfers, and explicit deletion. The 24-hour server policy covers temporary processing files and is labeled with its expiry. Durable cloud backup requires separate retention and authenticated project recovery, such as account-linked restore after reinstall. Enable the Backed up label and device-space cleanup only when those capabilities exist and pass a restore check. Show the retained-until date for any time-limited remote copy. Before relying solely on remote storage, provide a clear retention commitment and expiry handling.

During active recording, investigate finalized recording segments as recovery checkpoints. Present segments as one continuous take with a common logical source timeline and tested timestamp mapping. Validate seamless video and audio joins. Device tests cover app termination, calls, camera interruption, low storage, and restarting after a crash. The recovery guarantee covers completed recordings and individually finalized checkpoints. Expose checkpoint recovery only after the recording implementation passes those tests. Display a saving state until the current recording is finalized.

Deletion actions have distinct meanings:

- Remove from edit changes the selected timeline and retains the original.
- Delete original recording lists affected edits and asks for explicit confirmation before removing source copies.
- Free device space is available after verified durable backup and restore access. It removes the local media copy, retains project metadata, and permits download on demand.
- Delete project clearly states which local files, remote originals, and edits it removes. Coordinate cancellation with uploads and analysis so completing jobs respect the deletion record.

Private app storage can be lost with device loss or app removal. Explain that limitation beside local-only status and offer optional Save original to Photos or durable backup when available. Routine cache cleanup removes reproducible previews and temporary files. Original deletion follows the explicit actions above.

## Cut construction

1. Use Whisper for the timestamped transcript. Apply deterministic timestamp and silence rules for mechanical cleanup, with an ffmpeg silence map and RMS envelope. Astra handles semantic cleanup and editorial choices.
2. Astra groups intended lines and takes. Repeated opening phrases can indicate retakes during continuous speech.
3. Select takes from the transcript first. For visually ambiguous candidates, sample a small capped set of frames to assess eye contact and visible delivery. Additional frame analysis returns a reviewable proposal.
4. Place boundaries in nearby silence with up to 150 ms padding, clamped to source bounds and neighboring speech.
5. Split interior silence longer than 700 ms into visible clips, retaining 250 ms total around the split. Keep analysis so the dead-space toggle can reconstruct the plan.
6. Rank body lines by necessity, preserve coherent order, and drop whole lines automatically to approach the target duration. Return one complete body cut and a restorable list of dropped lines.
7. Associate four visual title variations with each spoken hook. Build captions from words within the chosen clip ranges.

Astra returns editorial choices referencing word and take IDs. Deterministic code turns those choices into validated clip ranges. The first analysis returns one body draft and four spoken hook suggestions together. Changing target duration reuses stored analysis and returns a revision-bound proposal for explicit application.

## Responsive processing and edit ownership

1. Save the recording locally with an immutable source ID and timestamp manifest.
2. Extract compact audio, preserve its timing map, and prioritize its upload. Prototype extraction in the chosen Expo runtime before committing to the native capture implementation.
3. Start transcription and initial editing from the audio. Upload full video in parallel as bandwidth allows.
4. Open the first AI body draft against local phone video. The creator can edit and record hooks while video uploads. Show media-upload and analysis progress separately.
5. Analyze additional hook audio independently, then attach available takes to hook candidates. Selecting a hook prepends it to the current body edit.
6. Enable cloud draft and export once all source video required by the selected combinations is available and verified.

Keep immutable source analysis, revision-bound AI proposals, the user-owned timeline, and immutable render snapshots as separate records. The initial draft initializes an empty timeline once. Subsequent model results require explicit application. When edits occur during analysis, show a review action for the proposal and validate its base revision on application. A stale proposal requires review against the current timeline. Preserve caption overrides and removed material throughout.

Hook matching updates candidate records independently of body edits. A body change can make an existing hook suggestion less relevant, so offer an explicit refresh action while preserving recorded takes and edited suggestions. Capture hook takes, body revision, overlays, captions, and audio settings in each render snapshot.

Transcribe each immutable recording once. Cache analysis using source identity, analysis configuration, and prompt version. Use a separate task for each required analysis stage, and reuse results across all combinations. Target changes rerun line ranking. Trims, reorders, caption chunking, duration calculations, and visual slot assembly run deterministically. Small optional frame checks enrich a reviewable proposal while editing remains available.

## Audio normalization and delivery feedback

Enable automatic loudness matching by default, with a creator toggle. Measure hook and body speech, apply bounded gain to reduce the level jump at the join, and normalize the assembled soundtrack with true-peak control. Use a consistent project preset across combinations. Measure cached source audio once and remeasure assembled output when its edit or audio settings change. Keep sample alignment and duration stable through processing. Validate the preset on demo footage.

Use ffmpeg's documented [loudnorm filter](https://ffmpeg.org/ffmpeg-filters.html#loudnorm) for output loudness normalization. Device preview approximates per-section gain. The rendered draft includes the final audio treatment. Keep original audio available through the normalization toggle.

After hook recording, compare each hook's delivery with the opening body passage and summarize the wider body for context. Measure speaking rate, pauses, level, and vocal dynamics from audio. Give Astra those measurements and transcript context, plus a small frame sample when available. Describe pace and visible delivery with supporting evidence. Account for recording-level and microphone differences when interpreting loudness. Present uncertain judgments as suggestions.

Example feedback: "This hook is much faster than the opening body line. Try a calmer take for a smoother transition." Provide play-transition, keep-take, and record-again actions. Delivery feedback is advisory. A retake becomes a candidate that the creator can select. Changing the body opening makes the associated feedback stale and schedules a cached-metrics comparison against the current revision. Feedback carries the body revision and hook take ID it assesses.

Loudness matching adjusts playback level. Delivery feedback addresses performance choices such as pace and emphasis. Treat these as separate controls. Render work depends on available source media and valid selections. Advisory feedback can finish while the creator continues editing or exporting.

## Timeline contract

[docs/API.md](docs/API.md) specifies the API. [contracts/plan.ts](contracts/plan.ts) defines the plan and [fixtures/plan.json](fixtures/plan.json) provides synthetic data.

The ordered clip list is the edit. Each clip references a source and half-open source range in integer milliseconds. Timeline positions are cumulative clip durations. Repeated source ranges have distinct clip IDs.

Trim changes source bounds. Reorder changes list order. Automatic captions derive from words overlapping each range, clipped to its bounds and mapped to timeline time. The creator can edit, add, and delete captions. Persist manual edits and deletion records separately from automatic caption generation, then compose them into the canonical saved plan. Anchor manual captions to clip occurrences so they travel with reordered clips. Define partial-trim behavior during implementation. Render captures the saved plan revision and renders that exact clip list.

Build timeline gestures with react-native-gesture-handler and react-native-reanimated. Priority: trim handles, reorder, playhead scrub, hook-text drag, caption drag. Validate gestures against the fixture before upload integration.

Use expo-video for continuous source playback with seeks at clip boundaries and app overlays. Provide a server-rendered 540x960 draft to inspect joins. Export uses one ffmpeg render at 1080x1920, H.264/AAC, 30 fps, and MP4 fast-start metadata.

Verify thumbnail generation and Photos APIs against the installed Expo SDK. Native export downloads the file and requests Photos permission. Web export offers a download.

## Text layout

Use heavy white TikTok Sans captions with a black outline and a transparent background. Every word uses the same white fill. Balance continuous speech into three- or four-word caption groups. Split at pauses longer than 700 ms and at clip boundaries. Short recordings and unavoidable final remainders use the available spoken words. Captions share one lane; creator edits take priority during their anchored intervals, and later stored edits take priority when manual ranges overlap. Creator text with a null transcript word ID stays white.

Reserve approximately 270 px at the top, 480 px at the bottom, and 140 px on the right of the 1080x1920 canvas. These are layout assumptions to validate against the destination app UI.

Place the hook title in a translucent rounded dark box in the upper middle. The default hold is 12 seconds with a 300 ms fade, clamped to output duration. The creator can change the title text and duration, reposition it, or delete it. Place captions above the bottom reserved area. Store text positions as normalized canvas coordinates. Bundle the same font for app and render. Inspect title corners, caption outlines, and spoken-word transitions in rendered frames.

## Ownership and checkpoints

- Kaung: resumable upload, storage verification, project recovery API, transcription, Astra analysis, cut construction, captions, render, then timeline integration.
- Vanessa: Expo screens, durable local recording storage and recovery, camera and teleprompter, gestures, playback, projects, visual hook title UI, visual title templates, web deployment.
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
- Audio-first analysis opens a local-video draft while full video uploads. Cloud export waits for required media.
- An AI job completing during manual edits leaves the saved timeline intact and exposes a revision-bound proposal.
- Hook attachment preserves body edits and caption overrides.
- Audio normalization preserves timing and reduces a measured hook/body level jump. Its toggle persists in render snapshots.
- Delivery feedback identifies its hook take and body revision, supports keep or retake, and remains advisory.
- Captions align after clips move, shrink, or repeat. Hook text begins at timeline zero.
- Target changes expose dropped lines and actual duration.
- Completed originals and saved edits survive app restart, offline use, failed analysis, and interrupted upload.
- Editing and deleting timeline clips retain original files.
- Original upload completion requires a matching size and checksum. Temporary processing copies display expiry.
- Durable-backup status and Free device space require a verified restore path and explicit retention policy.
- Active-recording interruption tests establish which finalized checkpoints can recover, with continuous audio/video timing verified.
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

- A restricted backend API key has verified `gpt-6-astra` access through the live provider and HTTP checks. Service variables hold the hosted key; the local `.env` is ignored and permission-restricted.
- Vanessa's visual hook title templates and permitted talking-head footage. Kaung settles the filming schedule.
- Measure a representative portrait 1080p/30 phone file to set the byte limit.
- Use the caption default specified above for implementation.
- Railway and Expo deployment access.

The product scope is settled. Implementation choices use the defaults in this plan. Stretch work after the core flow passes: per-hook suggestion regeneration, color controls, sounds, and general multi-file body uploads.
