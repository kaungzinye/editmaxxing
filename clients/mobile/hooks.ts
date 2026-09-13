export type Hook = {
  id: string;
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

// Sample data for the prototype, not quotations from an uploaded recording.
// Evidence snippets are fictional excerpts from the supplied productivity story.
// Rationales are editorial hypotheses, not measured performance predictions.
export const VERBAL_HOOKS: VerbalHook[] = [
  {
    id: 'verbal-1',
    line: 'The app did not lose my notes. I did.',
    mechanism: 'Unexpected confession',
    reason:
      'The unexpected confession creates a clear question: what actually happened to the notes?',
    source: 'Sample body · The note dump',
    evidence:
      'I had dumped notes in there for three months. Nothing was missing, but I nearly sent a client the wrong document.',
    movement: MOVEMENTS[0],
    movementReason:
      'This familiar gesture may draw the eye toward your expression before the first word.',
  },
  {
    id: 'verbal-2',
    line: 'Turning everything off made it worse, at first.',
    mechanism: 'Backfired fix',
    reason:
      'The failed fix opens two questions: why it backfired and what changed later.',
    source: 'Sample body · Notifications',
    evidence:
      'I turned off every notification. For the next two weeks, my screen time actually went up before I addressed the habit underneath.',
    movement: MOVEMENTS[1],
    movementReason:
      'A single fingertip tap may create a visible opening beat without distracting from your face.',
  },
  {
    id: 'verbal-3',
    line: 'I was not disorganized. I was avoiding this.',
    mechanism: 'Hidden reason',
    reason:
      'The confession leaves the real problem unnamed, creating curiosity about what you avoided.',
    source: 'Sample body · The three remaining notes',
    evidence:
      'I deleted 400 notes. The three left were tasks I kept putting off. Collecting more notes had become a way to avoid them.',
    movement: MOVEMENTS[2],
    movementReason:
      'A small change in head angle may invite attention while keeping your expression easy to read.',
  },
  {
    id: 'verbal-4',
    line: 'The habit I trusted most was slowing me down.',
    mechanism: 'Surprising cost',
    reason:
      'Turning a trusted habit into the problem creates doubt about a familiar routine.',
    source: 'Sample body · Collecting instead of doing',
    evidence:
      'For three years I trusted the system, but it only worked privately. Saving and sorting more notes kept delaying the work I needed to do.',
    movement: MOVEMENTS[3],
    movementReason:
      'Changing your distance from the lens may catch attention before you settle into the first line.',
  },
];

export const TEXT_HOOKS: Hook[] = [
  {
    id: 'text-1',
    line: 'I nearly sent a client the wrong document. The mistake started three months before that moment.',
    mechanism: 'Hidden cause',
    reason:
      'The client mistake establishes stakes. The three-month gap creates a mystery about where it began.',
    source: 'Sample body · The near miss',
    evidence:
      'After three months of dumping notes together, I nearly sent a client the wrong document. I caught it before sending.',
  },
  {
    id: 'text-2',
    line: 'For three years, my system worked perfectly. The catch was that it only worked in private.',
    mechanism: 'Hidden catch',
    reason:
      'Three years establishes trust, then the private-only condition undermines it, leaving the hidden weakness unexplained.',
    source: 'Sample body · A private system',
    evidence:
      'I thought my system worked for three years. It worked when only I used it; trying to share the right document exposed the problem.',
  },
  {
    id: 'text-3',
    line: 'I switched off every notification. Two weeks later, my screen time had gone in the wrong direction.',
    mechanism: 'Reversed result',
    reason:
      'The two-week result contradicts a familiar fix, opening the question of why fewer alerts meant more screen time.',
    source: 'Sample body · Two weeks without alerts',
    evidence:
      'I disabled every notification. Two weeks later, my screen time was higher. The notifications had not been the whole problem.',
  },
  {
    id: 'text-4',
    line: 'I deleted 400 notes. The three I kept were the ones I had been trying not to face.',
    mechanism: 'Unfinished confession',
    reason:
      'The contrast between 400 deleted notes and three uncomfortable survivors turns a cleanup into an unfinished confession.',
    source: 'Sample body · What survived the cleanup',
    evidence:
      'After deleting 400 notes, I had three left. They were the tasks I was procrastinating on, hidden underneath all that collecting.',
  },
];
