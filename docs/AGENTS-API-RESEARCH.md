# Agents API research

Checked September 13, 2026 against official OpenAI documentation.

The Agents API is a public beta released September 10, 2026. It gives applications access to the OpenAI-managed Codex harness. OpenAI runs session orchestration, context compaction, and recovery. [Release announcement in the API changelog](https://developers.openai.com/api/docs/changelog)

My recommendation is to keep Editmaxxing's Responses API integration for its present workflow. Its transcription, editorial analysis, hook matching, and delivery feedback are bounded operations with validated results. The application controls source timestamps, edit revisions, upload checks, retention, and FFmpeg rendering. An Agents API integration is useful for a conversational editor that chooses inspections, experiments with edits, and follows feedback across several turns. This recommendation is an architectural judgment based on the application and the documented capabilities below.

## What the API provides

| Concern | Documented behavior | Fit for Editmaxxing |
| --- | --- | --- |
| Model and execution | Agents configuration accepts a model, including `gpt-6-astra`. The managed harness runs the model/tool loop, supports mid-turn steering, and can delegate work to subagents. | Preserve the requested model if evaluating this API. Dynamic investigation benefits from this loop. |
| Session state | Sessions retain conversation and work state across turns. OpenAI handles context compaction and recovery. | Useful for repeated conversational editing. Project revisions and upload state remain application records. |
| Tools | Function tools execute in the application; remote MCP tools can execute through their servers. With `environment.type="none"`, the agent uses tools without an environment filesystem. | A small adapter could expose validated inspection, plan-proposal, and render-status functions. |
| Runtime | Environments support OpenAI-hosted sandboxes and self-hosted execution. The application owns self-hosted lifecycle and infrastructure. | Rendering can continue through the existing worker and storage. |

Sources: [Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview), [architecture](https://developers.openai.com/api/docs/guides/agents-api/architecture), [function tools](https://developers.openai.com/api/docs/guides/agents-api/tools/functions).

## SDK and access

The quickstart documents Python, JavaScript, Go, Java, Ruby, and REST examples. Python calls use `client.beta.agents.sessions.create(...)`. REST requests include `OpenAI-Beta: agents=v1`; supporting SDKs supply the header. An application API key needs `api.agents.read`, `api.agents.write`, and `api.responses.write` permissions. [Quickstart](https://developers.openai.com/api/docs/guides/agents-api/quickstart)

The repository's installed Python SDK is `openai==2.54.0`. A local inspection reports that `client.beta.agents` is absent. Evaluation therefore requires a supporting SDK release or the documented REST API. This research leaves dependencies unchanged. Agents API access for this project's key is unverified; successful Responses and transcription calls establish those integrations only.

## Files, persistence, and cost

OpenAI-hosted sandboxes provide Linux workspaces, configurable system/Python/npm packages, setup commands, and network controls. Each session has its own workspace. Files persist across turns while the sandbox exists. If activity and keep-alives stop for one hour, the sandbox can be deleted; this timeout is fixed. [Hosted sandboxes](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted)

Inputs can use Files API IDs or inline content. Outputs under `/workspace/outputs` become immutable artifacts when a turn completes and remain downloadable after sandbox expiry. Save required outputs before deleting the session. Self-hosted files use the application's filesystem or provider file API. [Files and artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files)

Each model call incurs the selected model's token charges, including reasoning, retries, and subagent calls. Session usage is best effort; cost comparisons should measure the whole completed task. [Observability and usage](https://developers.openai.com/api/docs/guides/agents-api/observability)

Hosted environments use standard container pricing. Listed prices per 20-minute container session are $0.03 for 1 GB, $0.12 for 4 GB, $0.48 for 16 GB, and $1.92 for 64 GB; the pricing page also describes per-minute billing for eligible sessions with a five-minute minimum. Model and applicable tool charges are separate. The selected environment's actual resources and billing eligibility need confirmation during an evaluation. [Container pricing](https://developers.openai.com/api/docs/pricing)

## Evaluation boundary

A useful trial is one conversational revision through an agent using `environment.type="none"` and narrowly scoped backend functions. Compare valid edit plans, latency, and complete-task cost against the current provider. Keep timestamps, authorization, revision checks, and deletion rules in application code.

The reviewed guides do not establish exact equivalence with the current Responses Pydantic parsing contract, a hard per-task spending cap, or production FFmpeg throughput for hosted environments. Validate those requirements before selecting an architecture. The documented hosted Agents API and the separately documented Agents SDK are distinct products. This report makes no migration or runtime changes.
