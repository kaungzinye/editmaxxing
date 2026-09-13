# editmaxxing

A mobile video editor for tech creators. Upload a continuous talking-head body recording and receive one complete body cut. Develop four spoken hooks, each with four visual titles based on Vanessa's templates. Edit the timeline, titles, and captions, then export selected combinations targeting 90 to 180 seconds.

This repository contains the product plan, API contract, shared TypeScript types, and synthetic sample data. The app implementation is the next build step.

- [Product and build plan](PLAN.md)
- [API contract](docs/API.md)
- [Shared types](contracts/plan.ts)
- [Sample plan](fixtures/plan.json)

Stack: Expo with Expo Router, FastAPI, ffmpeg, hosted Whisper transcription, and `gpt-6-astra` analysis. Deployment target: Railway backend and Expo web app.

Kaung owns the backend and rendering. Vanessa owns the Expo app, visual hook title UI, and title templates.
