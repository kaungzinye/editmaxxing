# editmaxxing mobile

The iOS development app captures a body recording, displays grounded spoken and on-screen recommendations, records separate hook takes, and previews and exports edited videos through the API.

Camera recording uses 1080p with portrait orientation and a 9:16 viewfinder. Take review uses the same frame. Drafts are 540×960 and exports are 1080×1920.

From the repository root:

```sh
npm ci
npm run ios --workspace editmaxxing-frontend
```

The first build generates the native Xcode project and installs CocoaPods. It includes the shared AVFoundation audio extractor. Expo Go cannot supply that module. The browser build supports UI inspection; media processing targets iOS.

The app connects directly to `https://editmaxxing-production.up.railway.app`. For local API development, set `EXPO_PUBLIC_API_URL` to a reachable API origin when starting Expo, such as `EXPO_PUBLIC_API_URL=http://192.168.0.92:8019 npm start --workspace editmaxxing-frontend`. Start that API with `uv run uvicorn editmaxxing.app:app --host 0.0.0.0 --port 8019` and set `PUBLIC_BASE_URL` to the same reachable origin. Project journals are scoped to the configured API origin. Expo embeds this public URL in the JavaScript bundle.

## Browser editor

`scripts/local_web.py` serves the exported web build, the editing API, and a loopback `/local/prepare` route that probes an uploaded video and extracts its audio with FFmpeg. `native.web.ts` replaces the AVFoundation extractor with that route on web. Build the web bundle against the loopback origin, then start the server from the repository root:

```sh
EXPO_PUBLIC_API_URL=http://127.0.0.1:8019 npm run build:web --workspace editmaxxing-frontend
PUBLIC_BASE_URL=http://127.0.0.1:8019 uv run uvicorn scripts.local_web:app --port 8019
```

Open `http://127.0.0.1:8019`. Camera recording stays iOS-only. The browser accepts an uploaded video, and **Save** downloads the exported MP4.

Use a real body recording, choose spoken and on-screen hooks, and record each selected spoken hook. For physical hooks, review the take and enter the action's source start time. Wait for uploads and matching, then select **Render previews**. Edit the shared body by keeping or removing passages. **Download selected** queues export-quality renders, and **Save** opens the iOS share sheet with the downloaded MP4.

Originals remain in the app's Documents directory. Project tokens use SecureStore. The project journal persists selections, recordings, transfers, jobs, pending body edits and render requests in alternating snapshots. Launching the app resumes transfers. Server media has processing retention; expiry appears in project state and expired project access requires a new project. Original files remain accessible through iOS file sharing.

```sh
npm run typecheck
npm test --workspace editmaxxing-frontend
npm run build:web --workspace editmaxxing-frontend
```

[Integration details](INTEGRATION.md) describe the API controller and verification boundaries. [Expo SDK 57 documentation](https://docs.expo.dev/versions/v57.0.0/) describes the native SDK used by the app.
