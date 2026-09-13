# Railway deployment

The backend uses a single Docker service and persistent `/data` volume. Configure it through Railway's dashboard. Dockerfile detection provides the build; the container command runs one uvicorn process and one durable queue consumer.

Project: `editmaxxing`, ID `d08e0b5f-dad8-46d5-a21b-fcd88990faa8`. Service: `editmaxxing`, ID `49d95c16-45da-4a38-b6da-383ea6565cc0`. Region: Singapore. Public API origin: `https://editmaxxing-production.up.railway.app`.

| Setting | Value |
| --- | --- |
| Repository | `kaungzinye/editmaxxing` |
| Branch | `feat/kaung-backend` |
| Root directory | Repository root |
| Replica count | 1 |
| Health check | `/healthz` |
| Domain target port | 8000 |
| Volume mount | `/data` |
| `PORT` | `8000` |
| `STORAGE_ROOT` | `/data` |
| `EDITOR_MODEL` | `gpt-6-astra` |
| `OPENAI_API_KEY` | Restricted backend key, configured privately |
| `PUBLIC_BASE_URL` | `https://editmaxxing-production.up.railway.app` |
| `CORS_ORIGINS` | Exact Expo web origins as a JSON array |
| `RETENTION_HOURS` | `24` |
| `ENABLE_FIXTURES` | `false` |
| `MAX_VIDEO_BYTES` | `134217728`, 128 MiB per original |
| `STORAGE_QUOTA_BYTES` | `450000000` |

The trial exposes 2 vCPU and 1 GB memory per service. Hosted byte and storage caps target the trial volume. Local defaults allow 2 GiB originals and 20 GiB storage. A representative twenty-minute phone recording needs storage and bandwidth sizing before increasing the hosted caps. Expiring server copies are processing media; the capture app retains local originals.

Add Vanessa's deployed web origin to `CORS_ORIGINS` when its URL is available. Native clients use bearer authorization independently of browser CORS. Keep provider keys in service variables. The current backend key expires on 20 September 2026.

A deployment health check confirms the process, ffmpeg, SQLite, and worker are available. Run the live smoke against the HTTPS origin to exercise hosted upload, AI, edit, and export behavior:

```sh
uv run python scripts/smoke.py --base-url https://editmaxxing-production.up.railway.app --synthetic --output-dir artifacts/railway-smoke
```

Project and source deletion are explicit API operations. Automatic cleanup enforces processing retention. Worker restart records interrupted work as retryable failures. Retrying upload finalization retains acknowledged parts and verified original bytes.
