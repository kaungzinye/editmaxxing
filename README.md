# editmaxxing

A mobile video editor for tech creators. Upload phone footage, let Astra select takes and pair hooks, edit the timeline, and export a captioned vertical MP4.

This repository contains the product plan, API contract, shared TypeScript types, and synthetic sample data. The app implementation is the next build step.

- [Product and build plan](PLAN.md)
- [API contract](docs/API.md)
- [Shared types](contracts/plan.ts)
- [Sample plan](fixtures/plan.json)

Stack: Expo with Expo Router, FastAPI, ffmpeg, hosted Whisper transcription, and `gpt-6-astra` analysis. Deployment target: Railway backend and Expo web app.

Kaung owns the backend and rendering. Vanessa owns the Expo app and hook templates.
