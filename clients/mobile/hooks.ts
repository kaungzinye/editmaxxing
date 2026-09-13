export type Hook = {
  id: string;
  generatedLine: string;
  revision: number;
  line: string;
  mechanism: string;
  reason: string;
  source: string;
  evidence: string;
};

export type VerbalHook = Hook & {
  movement: string;
  movementReason: string;
};

export const CURIOSITY_RESEARCH =
  'https://www.cmu.edu/dietrich/sds/docs/loewenstein/PsychofCuriosity.pdf';

export const MOVEMENTS: string[] = [
  'Tuck your hair behind one ear.',
  'Tap your fingertips together once.',
  'Tilt your head slightly before speaking.',
  'Lean slightly toward the camera, then settle back.',
];


import type { ProjectState, Recommendation } from '../../contracts/plan';
function recommendation(p: ProjectState, value: Recommendation & { id: string }, line: string): Hook {
  const words = value.evidence_word_ids.map(id => p.words.find(w => w.id === id)).filter(w => !!w);
  const first = words[0], last = words.at(-1);
  return { id: value.id, line, generatedLine: value.generated_text, revision: value.text_revision,
    mechanism: value.mechanism, reason: value.rationale,
    source: first ? `${first.source_id} · ${(first.start_ms / 1000).toFixed(1)}–${(last!.end_ms / 1000).toFixed(1)}s` : 'Body evidence unavailable',
    evidence: words.map(w => w.text).join(' ') };
}
export function projectHooks(p?: ProjectState) {
  return {
    verbal: p?.hooks.map(h => ({ ...recommendation(p, h, h.proposed_text), movement: h.movement, movementReason: '' })) ?? [],
    text: p?.titles.map(t => recommendation(p, t, t.text)) ?? [],
  };
}
