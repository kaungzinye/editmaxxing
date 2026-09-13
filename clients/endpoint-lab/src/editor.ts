import type { Plan } from '../../../contracts/plan';

/** Keep displayed caption timing attached to its clip while raw trim controls edit it. */
export function remapDraftCaptions(previous: Plan, next: Plan): Plan {
  const previousClips = new Map<string, { start: number; offset: number }>();
  let offset = 0;
  for (const clip of previous.clips) {
    previousClips.set(clip.id, { start: clip.source_start_ms, offset });
    offset += clip.source_end_ms - clip.source_start_ms;
  }
  const nextClips = new Map<string, { start: number; end: number; offset: number }>();
  offset = 0;
  for (const clip of next.clips) {
    nextClips.set(clip.id, { start: clip.source_start_ms, end: clip.source_end_ms, offset });
    offset += clip.source_end_ms - clip.source_start_ms;
  }
  const captions = next.captions.flatMap(caption => {
    const before = previousClips.get(caption.clip_id), after = nextClips.get(caption.clip_id);
    if (!before || !after) return [];
    const start = Math.max(after.start, before.start + caption.start_ms - before.offset);
    const end = Math.min(after.end, before.start + caption.end_ms - before.offset);
    if (end <= start) return [];
    return [{ ...caption, start_ms: after.offset + start - after.start, end_ms: after.offset + end - after.start }];
  });
  return { ...next, captions, duration_ms: offset, target_met: offset <= next.target_duration_ms };
}
