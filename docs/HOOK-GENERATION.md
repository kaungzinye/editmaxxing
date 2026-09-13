# Hook generation

The backend uses a library of 20 fictional worked examples. Body analysis chooses two example IDs
from a compact catalogue containing each example's technique and subjects. A separate hook-writing
request receives those two complete examples and the transcript words retained by the initial body
selection. Each example contains a body excerpt, spoken and on-screen hooks, quoted evidence,
the questions they open, and a rationale.

The library is `backend/editmaxxing/hook_examples.json`. Vanessa's research is in
[HOOK-RESEARCH-EVIDENCE-BASE.md](HOOK-RESEARCH-EVIDENCE-BASE.md), sourced from her branch at
`53beb94de69c2887c5128875127bbb43ac6d82bb`. The examples apply the research's proposed mechanisms.
They are authored examples for writing guidance. Performance evidence comes from creator outcomes.

## Runtime sequence

1. Transcribe the uploaded body and select its takes. The model also selects exactly two distinct
   IDs from the 20-entry catalogue, matching the available evidence and preferring different
   techniques when both fit. Code validates those IDs against the library.
2. Save the body analysis so hook-generation retries reuse it. Compile the initial body selection
   at the requested duration to identify the footage available to support hooks.
3. Generate up to four spoken hooks and four independent titles using the two examples. Transcript
   word IDs identify the factual source. Example excerpts describe fictional source material.
4. Validate length, punctuation, evidence spans and payoff references. Publish recommendations
   while original video processing continues. Record the selected example IDs and policy version.
5. At export, resolve the actual spoken line and on-screen text, including creator edits and saved
   overlays. Check that each generated hook's promised answer remains intact in the body timeline.
   Assess current wording against the retained body in timeline order. Cache the result by the
   opening text, body clips, evidence and policy version.

Spoken hooks contain one to eleven whitespace-separated words and have estimated natural delivery
strictly below 3000 ms. One or two short sentences can fit that limit. The recorded-take check also
requires spoken duration below 3000 ms. Creator edits obey the same word limit. Hook and title text
use zero exclamation marks.

## Evidence and edits

Generated candidates carry `evidence_spans`, `payoff_word_ids` and `question_opened`. Each evidence
span is a consecutive run of selected body word IDs; several spans can support one candidate.
An opening question requires a payoff passage. Public records also contain the flattened
`evidence_word_ids` consumed by clients.

Export checks that the full payoff passage survives in order. A removed or partially trimmed
answer returns `422 payoff_missing`. Creator text revisions preserve their original evidence and
rationale; semantic assessment judges the revised wording against the retained body. Spoken-only
openings and creator-authored overlays receive the same assessment. Body edits and policy changes
produce different assessment cache keys.

The policy version hashes the accepted writing instructions and example-library contents. The
analysis cache includes that version. Projects retain their published recommendation identities
and creator edits through retries. Use a fresh project to evaluate a policy revision.

## Editing the examples

Keep 20 uniquely identified entries. Write the spoken hook within eleven words. Every evidence
quotation must appear verbatim in its example's body excerpt. Give speech and text different
questions that lead into the same body. Use `subjects` to describe the situation for catalogue
selection, and name the writing technique in `technique`.

Review natural spoken pace by reading the examples aloud. The library validator checks word counts
and quotations; editorial review checks the claims, questions and delivery.

## Evaluation

Ten separate transcripts live in `backend/tests/fixtures/hook_eval_cases.json`. They cover thin
evidence, hedges, separated supporting passages, and commands embedded in transcript content.
Each case includes editorial review requirements. The live generator receives its transcript;
the review requirements stay in the evaluation report.

Run the library and evaluation-set preparation locally:

```sh
.venv/bin/python scripts/evaluate_hooks.py
```

Run a real-model case using the configured backend credentials:

```sh
.venv/bin/python scripts/evaluate_hooks.py --live --case caption_alignment
```

Omit `--case` to evaluate all ten cases. Results go to `artifacts/hook-evaluation.json`, with selected
example IDs, generated candidates and review rules. Successful model responses receive
`requires_editorial_review`. Compare clarity, curiosity and spoken delivery across policy versions.
Use published-video outcomes to evaluate retention and sharing.

Automated checks exercise the two-request contract, library ID validation, selected-footage
grounding, eleven-word and three-second boundaries, payoff removal, body-sensitive assessment
caching and retry recovery. Run them with:

```sh
.venv/bin/pytest -q backend/tests/test_hook_generation.py backend/tests/test_mobile_integration.py
```
