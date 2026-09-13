# Mobile integration status

The creator app, shared client package and backend implement independent grounded recommendations, early recommendation publication, separate hook sources, capture revisions, protected physical-action openings, explicit retake selection, resumable uploads, persisted project state, body-edit conflicts, immutable render identity and native MP4 sharing.

## Verification

- 120 backend tests pass, including seven mobile integration scenarios.
- 14 mobile controller/workflow tests and nine endpoint client tests pass.
- Both clients pass TypeScript checking. The mobile web bundle exports successfully.
- Ruff and Git whitespace checks pass.
- The shared AVFoundation audio probe reports zero sample shift and preserves a 200 ms source offset.
- The local fixture-backed API smoke runs real upload verification, normalization, cut-frame extraction, captions and ffmpeg rendering. It downloads two 540×960 drafts and one 1080×1920 export. Details and MP4s are in `artifacts/mobile-integration-smoke/`.
- The media-fixture generator runs with the project-level title contract.
- Expo prebuild and CocoaPods resolve the shared `SourceAudio` native module.

## Native device build

The signed Debug build succeeds with Xcode 26.6 and the installed iOS 26.5 platform. The app is installed and launched on the iPhone 13 Pro named `king kaung`, running iOS 26.6 with Developer Mode enabled. Its bundle identifier is `com.editmaxxing.mobile`.

The build uses two parallel jobs to limit memory pressure on this Mac. The workspace is `clients/mobile/ios/editmaxxing.xcworkspace`, scheme `editmaxxing`. Build output is `/tmp/editmaxxing-iphone-build/Build/Products/Debug-iphoneos/editmaxxing.app`; the successful build log is `/tmp/editmaxxing-iphone-build-limited.log`.

The creator screen runs on the phone. The app connects to the hosted Railway backend through build configuration. Its recording and review frame is 9:16, with portrait 1080p camera capture. Development builds load JavaScript from Metro on port 8088. Camera capture, in-app extraction and the iOS share sheet require device acceptance testing. Provider editorial quality and visual cut quality require real-media acceptance. The synthetic provider checks verify pipeline mechanics.

The shared native module and local journal are part of the development build; see `clients/mobile/README.md` and `clients/mobile/INTEGRATION.md`.
