# Mobile flow and backend integration

The fetched `origin/vanessa/mobile-hook-flow` branch contains the mobile UI in `clients/mobile/`. A Git merge-tree check against the visual-boundary branch completes without textual conflicts. The integration work concerns data and processing flow.

## Creator flow

1. Film or select the body video, preview it, and confirm the take.
2. Enter hook selection immediately. Choose among four verbal hooks and four independent on-screen hooks. Edit the wording and optionally include a physical action.
3. Record one take for each selected verbal hook, with its words and optional action displayed as prompts. Changing those words or the action invalidates the matching recorded take.
4. Preview every selected verbal/text pairing. Select which versions to keep and save each version when a real rendered URL is available.

`App.tsx` uses a demo progress timer. `hooks.ts` supplies labeled sample recommendations. `FinalVideoScreen.tsx` plays local hook and body sources sequentially and supports a server render URL. API uploads, actual processing jobs, authenticated project persistence and render requests require integration. The visible timeline switches between opening and body playback; clip trimming and captions require additional editor controls.

## Integration decisions

| Area | Frontend behavior | Backend requirement and integration work |
| --- | --- | --- |
| Hook readiness | Hook selection opens at body confirmation, while demo body processing runs. | Transcript analysis and visual cut review publish the initial draft and suggestions together. To offer grounded hooks earlier, expose hook suggestions when transcript analysis completes and keep boundary review running. The UI can display recommendation loading independently. |
| Title combinations | Four global on-screen choices combine with any selected verbal hook. | Stored title IDs belong to a particular spoken hook. Map titles per spoken hook or define global generated-title ownership. Creator-authored text can use the existing combination overlay field. |
| Hook recordings | One source clip per selected verbal hook. | Source registration accepts one to four hook scripts. Register each separate recording as a hooks source with one script and its backend hook ID; this already fits the matching API. |
| Progress | Percent is 0–100, driven by a timer. | Convert backend progress from 0–1 and handle `waiting_video`, `review_boundaries`, failure and cancellation. Start audio and original video uploads together. |
| Timing and identity | Local clip IDs and durations in seconds; camera duration uses elapsed wall time. | Probe actual media duration, convert to canonical integer milliseconds, hash the original and register immutable source IDs and timing manifests. |
| Output | Local source playback and an optional render URI. | Save the plan with its base revision, request each selected combination, and associate completed render URLs with the exact plan revision and combination. Refresh expiring media URLs through project reads. |
| Recovery | Media is held in component state; web storage retains hook choices. | Copy original recordings into durable app storage, persist project/source/upload journals and store native project tokens securely. |

The frontend branch remains separate from the backend merge. These findings describe source inspection and a Git merge dry run; device behavior requires its own validation.
