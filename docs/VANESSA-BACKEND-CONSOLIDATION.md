# Vanessa mobile and backend consolidation

Review date: 13 September 2026.

Vanessa's creator flow fits the backend's source upload, hook matching, shared body and batch render design. The main integration work is a shared recommendation model, earlier publication of hook suggestions, explicit retake selection, and a mobile API controller. Physical actions also need protection in the exported cut.

I recommend keeping her four-step flow and making spoken hooks and on-screen hooks independent project-level records. Use the existing source, upload, plan and render machinery underneath it.

This review compares `vanessa/mobile-hook-flow` at `d9a336740bcc5d8b02bf4a233b63d6d5b4625e10` with the backend at `e2118c7433185fed48d6b96172d027de434220ad`, including visual cut boundary review. Vanessa's branch shares the backend base `0b3806e`. Its diff adds `clients/mobile/` and a README link across 26 files. A Git merge-tree check against `e2118c7` succeeds with zero textual conflicts. The analysis uses pinned local snapshots. Hosted deployment and device behavior require separate verification.

The mobile app makes zero backend API calls. `hooks.ts` supplies sample recommendations, `demoProgress` completes after 65 seconds, and capture retains local media URIs. The report therefore compares the data her UI consumes with the data our API accepts and returns. [Mobile workflow](https://github.com/kaungzinye/editmaxxing/blob/d9a336740bcc5d8b02bf4a233b63d6d5b4625e10/clients/mobile/workflow.ts#L1), [app state](https://github.com/kaungzinye/editmaxxing/blob/d9a336740bcc5d8b02bf4a233b63d6d5b4625e10/clients/mobile/App.tsx#L17).

The contract comparison follows.

| Area | Vanessa's UI expects or holds | Backend accepts or returns | Consolidation |
| --- | --- | --- | --- |
| Project | Local hook choices, selected IDs and physical-action toggle | `project_id`, bearer token, expiry, sources, hooks, plan, jobs and outputs | Add a persisted project controller and secure native token storage. |
| Media identity | `Clip {id, uri, duration, demo, name}`, duration in seconds | Immutable `SourceCreate` with role, integer `duration_ms`, original SHA-256 and timing manifest | Probe the actual file and register each recording. Keep local capture records separate from backend timeline clips. |
| Upload | Camera or picker URI | Extracted audio bytes plus timing/checksum headers, and a separate resumable original-video upload | Start both transfers after registration. Persist acknowledged upload parts and job IDs. |
| Spoken hooks | `id`, `line`, `mechanism`, `reason`, `source`, `evidence`, `movement` | `id`, `proposed_text`, `take_id`, `visual_titles`, `candidates`, `clips` | Map `proposed_text` to display text. Add explicit rationale and body-evidence fields to recommendations. Store physical cues as capture instructions. |
| On-screen hooks | Four independent text choices, each usable with every spoken hook | Four title variations per spoken hook when four templates are supplied | Define project-level titles and validate project ownership for combinations. |
| Recommendation readiness | Hook screen opens at body confirmation | Canonical `hooks` publish after transcript analysis, video readiness and boundary review | Publish canonical recommendations when transcript editorial analysis completes. Keep body-cut readiness separate. |
| Hook recording | One take per selected spoken hook | A `hooks` source with one to four existing hook IDs and scripts | Register each take as a separate source with one script. The API supports this. |
| Progress | `percent` from 0 to 100 and `idle/running/complete/error` | `progress` from 0 to 1 and `queued/running/succeeded/failed/cancelled` | Convert units and map states explicitly. Track upload, recommendations, body analysis and render jobs separately. |
| Edited text | Local edits preserve hook IDs; spoken/action changes invalidate local takes | Hook text updates retain the selected server take. Title overrides live in plan or render overlays | Persist text revisions and require a matching selected take before render. Persist each independent title edit. |
| Versions | `spokenId--textId`, local take and optional `renderUri` | Up to 16 unique combinations, saved `plan_revision`, output `hook_take_id`, `kind`, URL and expiry | Track render identity beyond the pair ID. Attach outputs only to the matching request inputs. |
| Preview and save | Whole hook source followed by whole body source; title appears for four seconds; native Save opens a URL | Edited source ranges, captions, audio normalization, default 12-second title hold, 300 ms fade; draft/export MP4s | Preview server drafts and use the same overlay settings for export. Implement native file/photo saving as a separate operation. |

The backend types are in [contracts/plan.ts](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/contracts/plan.ts#L1). The mobile playback and save behavior is in [FinalVideoScreen.tsx](https://github.com/kaungzinye/editmaxxing/blob/d9a336740bcc5d8b02bf4a233b63d6d5b4625e10/clients/mobile/FinalVideoScreen.tsx#L12).

The following details affect the implementation order.

1. **Independent titles need a shared model.** The backend checks title ownership in both plan saves and render requests. A title from spoken hook B paired with spoken hook A returns `422` with `invalid_selection`. Also, a fresh project has an empty template list. Its analysis can return four spoken hooks with empty title arrays. Vanessa's four literal sample strings are display content; the template endpoint expects exactly four `{id, pattern, slots}` records. Our generated title slots require transcript evidence. Keep that grounding requirement when introducing global titles. [Selection and render validation](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/service.py#L353), [template registration](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/service.py#L542).

2. **Recommendation publication controls when hook recording can start.** During `queued/waiting_video`, project state contains cached editorial analysis, but canonical `project.hooks` is empty. Source registration requires hook IDs from that canonical list. Reading raw `analysis.editorial.hooks` gives suggestion text without usable canonical IDs. Publish the records before the video gate, preserve their IDs and creator edits through later completion, and expose recommendation status separately. Hook selection can then proceed while the body upload and cut review continue. Hook footage still needs matching and review before render. [Analysis publication order](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/worker.py#L452).

3. **Separate takes work, but retakes require selection.** Registration accepts a one-item `hook_scripts` list. Matching appends candidates and auto-selects a sufficiently confident candidate only while `take_id` is null. After a retake, call `PUT /projects/{id}/hooks/{hook_id}` with the candidate `take_id` from that new source. Editing `proposed_text` also preserves the selected server take. The mobile fingerprint checks words and enabled movement; the API has no equivalent capture-intent check. Give captured takes a script/action revision and gate rendering against it. [Registration](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/service.py#L123), [candidate selection](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/worker.py#L419), [hook update route](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/app.py#L271).

4. **Physical actions need an explicit retained range.** Vanessa prompts an action before the first spoken word. `clips_for_take` starts near the first word, with up to 150 ms of padding, subject to silence detection. Boundary review adjusts within a further bounded window. A gesture at source time zero followed by speech at 1000 ms can fall outside the cut. Define a creator-confirmed action start and preserve the continuous action-plus-speech opening. The action remains part of the spoken take and does not multiply the number of versions. [Hook rules](https://github.com/kaungzinye/editmaxxing/blob/d9a336740bcc5d8b02bf4a233b63d6d5b4625e10/clients/mobile/HOOK-RULES.md#L33), [clip construction](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/editing.py#L59).

5. **The explanations need backend data.** The canonical hook response lacks the UI's curiosity mechanism, recommendation rationale and body evidence span. Candidate `reason` describes a recorded-take match. Delivery feedback describes performance relative to the body. Neither field answers why a suggested hook works. Add rationale and validated `evidence_word_ids` for spoken and on-screen suggestions. Derive source labels, excerpts and timestamps from project words. Preserve generated wording separately from creator edits so each rationale names the text revision it explains. [Mobile recommendation fields](https://github.com/kaungzinye/editmaxxing/blob/d9a336740bcc5d8b02bf4a233b63d6d5b4625e10/clients/mobile/hooks.ts#L1), [provider response models](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/models.py#L244).

6. **A pair ID and plan revision are insufficient render identity.** Changing an on-screen line preserves the mobile pair ID. Changing the selected server hook take preserves the plan revision. Two renders can therefore share both values while using different footage or text. Store each submitted combination with its render job ID, selected take ID, title revision or overlay hash, plan revision and output kind. Require `succeeded` and matching inputs before assigning a playable output. Refresh signed URLs through project GET. [Version construction](https://github.com/kaungzinye/editmaxxing/blob/d9a336740bcc5d8b02bf4a233b63d6d5b4625e10/clients/mobile/workflow.ts#L32), [render snapshots](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/service.py#L387).

7. **Product rules need enforcement on both sides.** Vanessa's `HOOK-RULES.md` permits fewer than four suggestions when evidence is limited and rejects contradictory or substantially repetitive pairings. Her component state assumes exactly four sample IDs, and `buildVersions` forms every pair. The provider validator requires exactly four spoken hooks, and render validation checks ownership and readiness. Define zero-to-four supported choices with a reason for a short set, plus pair validation tied to text revisions. Replace sample-ID lookups used for labels, persistence and original rationales. Her rules also request spoken hooks under 12 words and three seconds; the API currently validates text length, not that editorial constraint. [Product rules](https://github.com/kaungzinye/editmaxxing/blob/d9a336740bcc5d8b02bf4a233b63d6d5b4625e10/clients/mobile/HOOK-RULES.md#L1), [editorial validator](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/backend/editmaxxing/provider.py#L102).

The existing API supports independent creator-authored overlays. This concrete request queues a draft once the saved body and selected hook media are ready. `h_example` represents an actual backend hook ID; `7` represents the current saved revision.

```json
{
  "plan_revision": 7,
  "kind": "draft",
  "combinations": [
    {
      "id": "pair_1",
      "hook_id": "h_example",
      "visual_title_id": null,
      "use_title": true,
      "overlay": {
        "text": "The creator's chosen on-screen line",
        "position": { "x": 0.5, "y": 0.24 },
        "hold_ms": 4000,
        "fade_ms": 300
      }
    }
  ]
}
```

This uses the explicit overlay field. Generated global titles still need persistent identity, evidence, edits and pair validation. A null `visual_title_id` with arbitrary text expresses a creator overlay. It does not establish transcript support. Send `use_title: false` to remove the title; a null overlay alone participates in the saved/generated overlay selection rules.

I would consolidate in this order, with Kaung owning backend/shared contracts and Vanessa owning capture and presentation.

1. Agree on the recommendation records in `contracts/plan.ts` and Pydantic. Keep four spoken and four independent on-screen choices as the normal case, with evidence-limited results. Include generated text, creator text, text revision, rationale, evidence IDs and readiness. Keep movement with the spoken capture intent. Put generated titles at project scope. Update provider prompts, validation, plan selection and render validation together. If title templates remain the product choice, apply four templates once to the body recommendation set.

2. Publish recommendations after transcript editorial analysis. Expose their stable IDs while body-cut work continues. Keep source transfer state and job state distinct. Map `queued/waiting_video` to a waiting label, `succeeded` to completion, and failed/cancelled states to explicit recovery actions. Poll active jobs every two seconds. Convert progress with `round(clamp(progress, 0, 1) * 100)`.

3. Share the endpoint lab's transport and persistence code through a client package. Reuse checksum calculation, resumable uploads and journal behavior. Its native audio extractor is an iOS module requiring a development build. Android and browser capture need an extraction implementation or a deliberate product scope. Extend file finalization to camera/picker URIs, then persist originals before uploading. Store the media SHA-256 separately from the mobile script/action fingerprint. Probe media duration; camera elapsed wall time is a display estimate. [API helper](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/clients/endpoint-lab/src/api.ts#L1), [journal](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/clients/endpoint-lab/src/journal.ts#L1), [native extraction boundary](https://github.com/kaungzinye/editmaxxing/blob/e2118c7433185fed48d6b96172d027de434220ad/clients/endpoint-lab/modules/source-audio/index.ts#L1).

4. Connect one body and one selected hook end to end. Create the project, register the body, upload audio/video, display grounded recommendations, record a hook, register its one-item script list, upload it, and explicitly select the matched candidate. Preserve the action range when enabled. Treat source IDs as immutable and give each retake a new ID. The project limit is 20 registered sources, including retakes, so the UI needs an actionable limit state.

5. Save body edits with `base_revision`, then queue combinations against the returned revision. Handle `409 revision_conflict` by fetching current state and reconciling edits. Handle `hook_pending` and `media_pending` through source/job readiness. Show the server draft for edited preview, render the kept subset at export quality, and attach results using complete render identity. Implement native save-to-library or file sharing and URL-expiry recovery. Choose one overlay hold duration for preview and export. Capture limits and output targets are separate settings: her camera offers short takes, while the API target duration is 90 to 180 seconds and source ingestion supports up to 20 minutes.

6. Verify restart recovery and representative media. Persist jobs, upload sessions, source-to-hook mappings, selections, edits and render manifests outside component state. Keep local originals under the app's durable storage policy. The server exposes processing-copy expiry, normally 24 hours. Exercise a restart during upload, two spoken by three text selections, a retake, a text edit during render, an action before speech, a revision conflict and expired media URLs.

Verification for this report uses 50 existing backend API/editing tests, eight mobile workflow tests and five focused contract probes. The probes cover separate hook sources and retake selection, cross-hook title rejection and explicit overlay acceptance, spoken-edit take retention, recommendation state during `waiting_video`, and the cut range around a delayed first word. Backend fixture checks use synthetic transcription and simulated video readiness/contact sheets. They verify API behavior and snapshot construction. Actual camera operation, provider quality and final media appearance remain device and real-media acceptance work.
