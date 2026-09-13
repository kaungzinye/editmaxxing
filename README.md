# editmaxxing

A mobile video editor for tech creators. Record a continuous talking-head body with an optional script teleprompter and receive one complete body cut. Edit and record four suggested spoken hooks through the teleprompter, each with four visual titles based on Vanessa's templates. Edit the timeline, titles, and captions, then export selected combinations targeting 90 to 180 seconds.

This repository contains the product plan, API contract, shared TypeScript types, and synthetic sample data. The app implementation is the next build step.

- [Product and build plan](PLAN.md)
- [API contract](docs/API.md)
- [Shared types](contracts/plan.ts)
- [Sample plan](fixtures/plan.json)

Stack: Expo with Expo Router, FastAPI, ffmpeg, hosted Whisper transcription, and `gpt-6-astra` analysis. Deployment target: Railway backend and Expo web app.

Kaung owns the backend and rendering. Vanessa owns the Expo app, visual hook title UI, and title templates.

The processing design prioritizes audio upload and local-video editing while full video uploads. AI proposals reference timeline revisions. Audio normalization matches listening levels, and advisory hook/body delivery feedback offers a retake when useful.

Original recordings stay in a private project library. Edits reference those originals. The design includes durable local saves, resumable verified uploads, explicit deletion, and storage status that distinguishes temporary processing copies from recoverable cloud backups.
