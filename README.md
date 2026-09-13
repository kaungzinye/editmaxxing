# editmaxxing

Hosted backend: [API documentation](https://editmaxxing-production.up.railway.app/docs) and [health](https://editmaxxing-production.up.railway.app/healthz). [Acceptance evidence](docs/ACCEPTANCE.md) records local checks, the live Railway flow, and restart recovery.

FastAPI and ffmpeg turn talking-head recordings into editable vertical videos. Whisper supplies canonical word timestamps. `gpt-6-astra` selects takes, proposes independent spoken and on-screen hooks with body evidence, and gives advisory delivery feedback. Code constructs candidate clip ranges. Astra reviews four frames before and four at/after each boundary, then code validates timestamp adjustments and builds captions, revision-bound proposals, and immutable render snapshots.

The API lives in `backend/`. Vanessa's integrated creator app lives in `clients/mobile/`; the endpoint lab lives in `clients/endpoint-lab/`. Both apps share `clients/shared/`. Rendered text uses [TikTok Sans](https://github.com/tiktok/TikTokSans).

The creator app connects directly to the hosted API and records portrait 1080p video in a 9:16 frame. Start it with `npm run start --workspace editmaxxing-frontend`; its native audio extractor requires the iOS development build. [Mobile setup](clients/mobile/README.md) covers device builds and local API configuration. Railway deploys the backend from `main`.

## Run locally

Install Python 3.12–3.14, [uv](https://docs.astral.sh/uv/), and ffmpeg. From this directory:

```sh
uv sync
cp .env.example .env
# Set OPENAI_API_KEY in .env.
uv run uvicorn editmaxxing.app:app --host 0.0.0.0 --port 8000
```

Open [API docs](http://localhost:8000/docs) and [health](http://localhost:8000/healthz). The API uses `/api/v1`. Keep one API process and one replica per storage volume. SQLite records projects, upload acknowledgements, jobs, and edit revisions. Originals and reproducible derivatives use separate directories under `STORAGE_ROOT`.

Start the endpoint lab in another terminal:

```sh
npm ci
npm run web --workspace endpoint-lab
```

Enter `http://localhost:8000` as the API origin. A phone needs the computer's LAN address. Set exact web origins in `CORS_ORIGINS`. [Client walkthrough](docs/CLIENT.md) covers file preparation, native extraction, upload recovery, editing, hooks, and playback.

## Exercise the complete pipeline

The live smoke creates explicitly synthetic spoken media using macOS `say`, then calls real Whisper/Astra and ffmpeg endpoints. It checks transcription and visual boundary review, trim/reorder/caption saves, revision conflicts, hook attachment, verified upload retries, two draft combinations, one 1080p export, signed media, and delivery feedback.

```sh
uv run python scripts/smoke.py --base-url http://localhost:8000 --synthetic --output-dir artifacts/smoke
```

For deterministic analysis, start the API with `ENABLE_FIXTURES=true` and add `--fixture` to the smoke command. The fixture route marks each source explicitly before audio upload. Ordinary audio uploads use OpenAI. Generated source media and transcripts are described in [fixtures](fixtures/README.md).

```sh
uv run pytest backend/tests -q
uv run ruff check backend scripts
cd clients/endpoint-lab
npm run typecheck
npm test
npm run export
```

## Deploy

The Dockerfile includes Python, ffmpeg, the backend, and TikTok Sans. Mount persistent storage at `/data`, expose `PORT`, use `/healthz` for readiness, and run one replica. The image excludes `.env`, originals, test artifacts, and the client build. [Deployment settings](docs/DEPLOYMENT.md) lists the Railway configuration and resource limits.

```sh
docker build -t editmaxxing .
docker run --rm -p 8000:8000 --env-file .env -v editmaxxing-data:/data editmaxxing
```

Projects receive opaque bearer tokens. Media URLs expire and refresh through project reads. Server copies carry an explicit processing expiry, default 24 hours. Durable cloud backup and account-linked restore require a separate implementation. Local original protection belongs to the capture app.

## Integration references

- [Product plan and ownership](PLAN.md)
- [API routes, transport, and concurrency](docs/API.md)
- [Shared TypeScript contracts](contracts/plan.ts)
- [Provider requests and live verification](docs/PROVIDERS.md)
- [Endpoint client and native extraction evidence](docs/CLIENT.md)
- [Source-backed fixture](fixtures/project.json)

The API generates up to four spoken hooks and four independent on-screen titles. Optional title templates are configured before body analysis. Creator text revisions, capture instructions and original recommendation evidence persist separately. The [iOS app guide](clients/mobile/README.md) covers capture, restart recovery, previews and export saving.
