# Endpoint lab

`clients/endpoint-lab` is a standalone Expo SDK 57 integration client for Kaung's backend. Vanessa owns the production recording, teleprompter, and timeline experience. The lab provides file selection, raw controls, JSON inspection, clip trim/reorder controls, caption overrides, and video playback. Every app text element uses the official [TikTok Sans v4.000 files](https://github.com/tiktok/TikTokSans/releases/tag/v4.000) under the included SIL Open Font License.

## Run

```sh
cd clients/endpoint-lab
npm ci
npm run web
```

Enter the API origin, such as `http://localhost:8000`. The client appends `/api/v1`. The backend must include the web app's exact origin in `CORS_ORIGINS`. A phone uses the computer's LAN address, with the backend listening on `0.0.0.0`. Project credentials belong in the project ID and token fields. Provider credentials belong in backend environment variables.

`npm start` opens Expo's development server. SDK 57 Expo Go can exercise prepared file uploads. Native audio extraction uses the local Swift module in a development build:

```sh
npm run ios
```

Expo SDK 57 requires Xcode 26.4 or later and iOS 16.4 or later. The implementation machine has Xcode 26.6 installed through Apple's App Store. The mobile creator app builds, installs and launches on an iPhone 13 Pro. The extraction core compiles for the iOS SDK, and its macOS runtime probe passes. Device extraction, device termination recovery, Photos export, Android extraction, and EAS Update distribution require their own device checks. [Expo SDK requirements](https://docs.expo.dev/versions/latest/), [local Expo modules](https://docs.expo.dev/modules/get-started/).

## Body, edit, hooks, and render

1. Create a project. The lab saves its token locally. Native tokens use SecureStore; browser tokens use local storage. Saved-project buttons reopen source journals and the saved local draft.
2. Supply Vanessa's four title templates with the templates JSON control. Each object has `id`, `pattern`, and `slots`. Patterns use named placeholders such as `{topic}`. The template route requires exactly four templates.
3. Select the original video. Native selection copies the file to durable `Documents/originals`, then computes its SHA-256 in chunks. Set its duration and original timing JSON. A loaded iOS extraction module reads the duration directly. Register the source, whose fingerprint is the full original SHA-256.
4. Extract audio on iOS, or pick prepared audio from the same original. Paste the audio extraction manifest into its JSON field. Upload audio to begin analysis. Upload the original separately; these actions can run together.
5. For deterministic fixture testing, enable `ENABLE_FIXTURES=true` on the backend and press **Mark source as synthetic fixture** after registration and before audio upload. This route uses synthetic words and editorial choices. It still verifies, normalizes, and renders the selected media.
6. Inspect jobs or leave active-job polling enabled. Inspect the project for separate audio, video, and storage state. The `waiting_video` stage means the original upload must finish; normalization resumes the same analysis job. The `review_boundaries` stage checks candidate cuts with source frames. Load the server plan into the editor when analysis succeeds.
7. Trim clip bounds, reorder or remove clips, and edit caption text. The JSON control covers the full plan, including audio normalization, overlay timing, caption position, and manual caption additions/deletions. Save the plan. A 409 displays the server's conflict response and preserves the local draft. Load the server plan deliberately when reviewing the conflict.
8. Inspect hook suggestions. Edit and save their text, then create a hooks source. Its registration contains the ordered hook IDs and intended script text. Select the continuous hook recording, register it, and upload audio and original video. Hook matching updates candidates while the body edit remains saved. Candidate buttons apply an explicit take selection.
9. Toggle hook/title combinations. The combination JSON also accepts manual title overlays. Save edits before requesting a draft or export. A render captures the supplied saved revision and produces one URL per combination. A hook starts at timeline zero before the saved body clips.
10. Play the returned video or open its signed URL. Fetch project state to refresh expiring URLs. The raw player shows one media file at a time.

The source-duration field and `timing.duration_ms` must agree. All clip and caption times use integer milliseconds. `expires_at` values use Unix seconds. [API.md](API.md) describes the request headers and response shapes; [contracts/plan.ts](../contracts/plan.ts) exports the shared types.

## Prepare fixture audio

The development command writes compact AAC and a matching manifest:

```sh
uv run python scripts/prepare_media.py /path/video.mp4 --output-dir .local-media/body --source-id source_body --role body
```

`compact.m4a` contains mono 16 kHz audio. `manifest.json` contains `source`, `video`, and `audio` objects with checksums and separate timing maps. Use `source.duration_ms`, `source.timing`, and `audio.timing` in the lab fields. Create matching body and hooks test media with:

```sh
uv run python scripts/generate_media_fixture.py --output-dir .local-media
```

These files contain test patterns and tones for explicitly selected fixture analysis.

## Local files and transfer recovery

The lab hashes original files in 4 MiB reads and uploads server-sized parts. It stores the upload ID before sending a part. Resume fetches acknowledged parts, verifies their checksums against the selected file, sends missing ranges, and submits the ordered part manifest. Pause takes effect after the in-flight request. Moving the app into the background pauses foreground transfer; the resume button continues it after return.

Native project journals alternate between two JSON snapshots in Documents. On launch, the reader selects the highest valid sequence. Files in `Documents/originals` that lack a journal entry appear as recovery actions. Original files remain in private app storage; device loss and app removal can remove that storage. Native file sharing exposes the lab's Documents directory in Files for manual inspection.

Browser reload preserves project metadata, local plan drafts, and upload IDs. Select the matching browser file again to resume its transfer. The lab labels the server's verified copy as temporary processing storage with an expiry. Account-linked restore and durable remote backup belong to a separate storage implementation.

## Native extraction contract and evidence

`clients/shared/source-audio/ios/AudioExtractor.swift` reads the original's decoded audio through AVFoundation and writes mono AAC at 16 kHz and 48 kbit/s. Extraction returns `{uri, source_duration_ms, timing}`. The timing map uses `canonical_ms = decoded_media_ms + media_origin_ms - encoder_delay_ms`. AAC decoding applies skip-sample metadata; the adapter reports `encoder_delay_ms: 0`. Leading source silence remains in the output. A discontinuity exceeding 25 ms rejects extraction.

Run the shared-core probe on macOS with Xcode command-line tools and ffmpeg:

```sh
python3 clients/endpoint-lab/scripts/probe-native-audio.py
```

The probe compiles the Swift extractor, synthesizes a three-second noise/video source, extracts AAC, decodes both audio files with ffmpeg, and compares their sample positions. It also tests a source with a 200 ms audio-track offset. The measured result is zero sample shift, 48,000 reference samples, 48,064 extracted samples, and preserved leading silence for the offset source. The 64 extra samples are four milliseconds of trailing AAC padding. The server clamps normalized audio to the registered source duration.

The same core compiles with `xcrun swiftc` targeting `arm64-apple-ios16.4`. This is a native core check on the host and an iOS compilation check. The full Expo wrapper requires the compatible Xcode development build and a device exercise. [Expo FileSystem](https://docs.expo.dev/versions/latest/sdk/filesystem/) and [expo-video](https://docs.expo.dev/versions/latest/sdk/video/) document the file and playback APIs used by the lab.

## Verification

```sh
cd clients/endpoint-lab
npm run typecheck
npm test
npm run export
npx expo install --check
```

The nine tests verify acknowledged-part resume, checksum mismatch rejection, preserved 409 response details, browser fetch binding, concurrent audio preparation and upload journaling, and caption timing after clip reorder and trim. Caption checks cover per-word timestamps, repeated source occurrences, removal of empty cues, and stored words with null timing. The real-backend smoke command accepts prepared fixture media and a fixture-enabled API:

```sh
npm run smoke -- http://localhost:8012 /path/to/original.mov /path/to/audio.m4a 3000
```

It registers body and hooks sources, uploads both media kinds, saves a body trim, checks that hook analysis preserves body clips, renders a selected hook plus body, and downloads the MP4 to `/tmp/editmaxxing-endpoint-smoke.mp4`. Synthetic fixture analysis is explicit in this command.

The 13 September verification passes TypeScript, all nine client tests, web export, dependency checks, and the smoke flow against a fresh local API. Apple autolinking resolves `SourceAudio`; the generated CocoaPods provider imports its Swift module for debug and release builds. The full native build remains gated by the displayed Xcode SDK agreement.
