# Visual cut boundary review

The editing sequence is Whisper transcription, Astra take selection, candidate clip ranges, Astra visual boundary decisions, validated ranges, then the published draft and captions. The pass covers each clip's start and end, including internal silence cuts and recorded hooks.

Each boundary gets four frames before and four at/after its source timestamp at 30 fps, covering about 0.13 seconds on either side. Source edges repeat available frames and label their actual times. Eight 192-pixel tiles form a labeled contact sheet. Four extraction workers prepare up to 16 boundary sheets per Astra request with low image detail and low reasoning effort. The request includes nearby transcript words, original cut positions, selection reasons and permitted ranges. Adjustments are limited to 120 ms and preserve timestamped speech and adjacent clip ranges. Low-confidence and unsafe decisions retain their candidate and expose a playback flag. Results are cached against the source, timing and candidate context.

Audio and original video upload concurrently. `waiting_video` keeps analysis queued with its transcript and editorial decisions saved. Normalization wakes that same job, which reports `review_boundaries` before publishing the draft. Hook candidate selection preserves its reviewed clip ranges. Manual timeline edits remain creator-controlled, and explicit visual review returns a revision-bound proposal.

## Verification

The backend suite passes 113 tests. The endpoint client passes TypeScript checking and nine tests. The local HTTP smoke passes 18 checks with real Whisper/Astra and ffmpeg, including body and hook boundary review, two draft renders and one 1080p export. The complete synthetic recording-to-export smoke takes 124.4 seconds.

A live benchmark with high image detail reviews eight boundaries using 64 source frames in one request: extraction takes 0.305 seconds, Astra takes 15.918 seconds, and the complete review takes 16.224 seconds. This is one local measurement; larger edits require additional batches. Identical candidate reviews use the cache.

A low-detail recheck of the same eight-boundary workload takes 0.328 seconds for extraction and 15.768 seconds for Astra, totaling 16.097 seconds. These single runs show similar latency. Evidence is in `artifacts/boundary-smoke-live/review-benchmark-low.json`.

The smoke uses generated video with synthetic speech and no human face. Astra marks visual judgments as uncertain. The smoke verifies the pipeline and image inputs; representative talking-head footage is required to assess perceptual cut quality. Local evidence is in `artifacts/boundary-smoke-live/report.json` and `artifacts/boundary-smoke-live/review-benchmark.json`.
