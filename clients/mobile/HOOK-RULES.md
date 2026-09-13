# Hook rules

## Purpose

Hooks are generated from the uploaded body transcript. They maximize the chance of stopping a scroll before the body begins; they are not a summary of the body and do not need to describe the same idea as one another.

## Three independent curiosity vectors

Every opening combines one spoken hook and one on-screen hook. Creators can also include a physical hook. The enabled elements are deliberately non-redundant, with each creating its own curiosity. Spoken hooks and on-screen hooks are generated as independent sets, then mixed only at preview and export.

| Layer | Source | Job | Relationship to the other layers |
| --- | --- | --- | --- |
| Spoken hook | Body transcript | A sharp reframing, callout, or surprising claim | Tangentially grounded in the body; must not explain or restate the on-screen hook |
| On-screen hook | Body transcript | The most mysterious, concrete, or outlandish body-supported consequence | Tangentially grounded in the body; must not caption or paraphrase the spoken hook |
| Physical hook | Creator performance | A small visual interruption before the first word | Semantically unrelated to the spoken and on-screen hooks |

The spoken and on-screen hooks may draw on different moments from the same body. They must be traceable to the transcript; no invented claims, stakes, outcomes, or details. Generate four of each when the body provides enough distinct evidence; return fewer, with a reason, rather than pad the set with weak or duplicate options.

## Spoken hook

- Under 12 words and under three seconds at a natural pace.
- Use a body-supported reframing, reversal, behaviour callout, cost, or result.
- Lead with the actual subject. No throat-clearing or connective opening.
- Create a distinct tension rather than answer the on-screen hook.
- No empty suspense, generic superlatives, or claims the body cannot back.

**Calibration example:** `The app did not lose my notes. I did.`

## On-screen hook

- This is the strongest curiosity layer.
- Use an unresolved, concrete, high-stakes, unusual, or apparently outlandish claim taken from the body.
- Prefer consequence, loss, confession, taboo, unusually precise outcome, or reversal.
- Give it enough context to create a real question: usually one or two short clauses, roughly 10–22 words. It may be more detailed than the spoken hook, but should still scan in two or three lines at phone size. Keep it high contrast and safely inside the visible canvas.
- It cannot caption, paraphrase, or resolve the spoken hook. It remains unexplained during the opening stack.
- Never invent drama. The body must contain the evidence behind the text.

**Calibration example:** `I nearly sent a client the wrong document because I treated my notes like a dumping ground.`

## Physical hook

- Begins before the first word and needs zero props, setup, or special location.
- Use one small, visible human action: crack knuckles once, tuck hair behind an ear, run fingers through hair, inspect or tap nails, adjust a collar, lean toward then back from camera, glance off-camera then return to lens, rub hands once, tilt the head, or roll one shoulder.
- It is intentionally unrelated to the spoken and on-screen hooks.
- One action only. It must not cover the face or interfere with readability.
- No product handling, tools, food, glasses, makeup application, stunts, elaborate gestures, or visual explanation.

Physical hooks are optional. A project-level **Include physical hooks** checkbox controls whether physical cues appear in recommendations and planned combinations. Preserve saved actions when switched off, so enabling them again restores the creator's edits. This setting does not change the spoken × on-screen combination count. When enabled, the physical action is performed and recorded with its spoken hook and travels with it across text pairings.

## Selection and export

- Generate four independent spoken-hook candidates and four independent on-screen-hook candidates when evidence permits.
- The creator selects any nonempty subset of recorded spoken hooks and any nonempty subset of on-screen hooks.
- Each selected spoken hook can pair with every selected on-screen hook. The number of downloadable videos is `selected spoken hooks × selected on-screen hooks`.
- Example: two selected spoken hooks and three selected on-screen hooks produce six finished videos, all sharing the same edited body.
- At preview and export, preserve the selected spoken hook's physical action, audio, and timing. Swap only the on-screen text layer.
- Reject a pairing only if its two lines directly contradict one another, repeat substantially the same claim, or have missing body evidence. Otherwise, tangential connection is allowed and preferred over literal alignment.

## Editing and recommendation explanations

- Spoken hooks, on-screen text, and each spoken take's physical cue have visible editing controls. Saving or cancelling an edit preserves the creator's existing selections and the hook's stable identity.
- Spoken and on-screen recommendations use the heading **Why it works** and state the specific curiosity mechanism directly. Verbal-hook reasons use one brief sentence, or at most two short sentences. Avoid timid wording such as “may work” while keeping claims tied to the wording and psychology, not guaranteed views or virality.
- Spoken and on-screen recommendations expose their original body evidence and source location. Physical hooks show only the action and its editing control, without psychological explanations.
- After spoken or on-screen text is edited, label its existing explanation **Original rationale** until an explanation has been regenerated for that exact revision. Keep original evidence visibly identified as original; do not imply it verifies newly added claims. Recheck body support before treating edited text as validated.
- Physical-cue edits remain within the zero-prop, one-action rules above. Offer editable body-only choices without introducing props, setup, stunts, or a separate physical selection pool.
- Do not show a virality score or an unsupported numerical performance prediction. Research may inform the general curiosity principle; it does not establish that an individual recommendation will succeed.
- Keep interface copy functional: no invented project titles, motivational taglines, redundant combination instructions, or exclamation marks. Show an actual project title only when one exists.

## Stack validation

Accept a stack only when all conditions are true:

1. Every candidate hook cites a body evidence span and contains no invented claim.
2. A generated pairing does not directly contradict or substantially paraphrase itself.
3. The on-screen hook scores highest for mystery or outlandishness while remaining evidence-backed.
4. If physical hooks are enabled, the physical hook comes from the body-only whitelist and is unrelated to both text layers.
5. All enabled layers start within the first second; the body begins directly after the opening stack.

## Example

For a body about a creator's disorganized workspace causing an accidental private-document share:

- **Spoken:** `The app did not lose my notes. I did.`
- **On-screen:** `I nearly sent a client the wrong document.`
- **Physical:** Tuck hair behind one ear before speaking.
