import assert from 'node:assert/strict';
import { test } from 'node:test';
import { API, checksum } from '@editmaxxing/client/api';
import { ProjectController, initialSession, jobProgress, matchingOutput, renderKey, type Dependencies, type Recording } from '../controller';
import type { Job, ProjectState, RenderOutput } from '../../../contracts/plan';

const project = (): ProjectState => ({ project_id: 'p', hooks: [{ id: 'h', take_id: 'take1', capture_revision: 1, proposed_text: 'A spoken hook', candidates: [], text_revision: 1 }],
  titles: [{ id: 't', text: 'An on-screen hook', text_revision: 1 }], plan: { revision: 1, clips: [{ id: 'clip', role: 'body' }] },
  sources: {}, recommendations: { status: 'ready', short_set_reason: '' }, outputs: [] } as unknown as ProjectState);
const job = (id: string, state: Job['state'] = 'running', stage = 'analyze', progress = .5): Job => ({ id, project_id: 'p', state, stage, progress, error: null, result: null });
const bytes = new TextEncoder().encode('abcdefghijklmn');
const file = { uri: 'file:///saved.mp4', name: 'Recording', size: bytes.length, sha256: checksum(bytes), mime: 'video/mp4' };
const recording = (): Recording => ({ sourceId: 's', role: 'body', duration: 12000, timing: { duration_ms: 12000, media_origin_ms: 0, encoder_delay_ms: 0, extractor: 'original', sample_rate: 48000 },
  audioTiming: { duration_ms: 12000, media_origin_ms: 0, encoder_delay_ms: 0, extractor: 'test', sample_rate: 16000 }, original: file, audio: file, hookScripts: [], registered: true,
  clip: { id: 'clip', uri: file.uri, name: 'Body', duration: 12, demo: false } });
function dependencies(transport: typeof fetch): Dependencies {
  return { save() {}, saveToken: async () => {}, readToken: async () => 'token', uuid: () => 'request1',
    prepare: async () => recording(), read: () => ({ size: bytes.length, read: async (a, b) => bytes.slice(a, b) }), transport };
}

test('job presentation distinguishes waiting, success, failure, cancellation and clamps units', () => {
  assert.equal(jobProgress(job('j', 'queued', 'waiting_video', .55)).label, 'Waiting for video upload');
  assert.equal(jobProgress(job('j', 'running', 'analyze', 2)).percent, 99);
  assert.equal(jobProgress(job('j', 'running', 'analyze', -2)).percent, 0);
  assert.equal(jobProgress(job('j', 'succeeded')).status, 'complete');
  assert.equal(jobProgress(job('j', 'failed')).status, 'error');
  assert.equal(jobProgress(job('j', 'cancelled')).status, 'error');
});

test('outputs require a successful job and exact take, title, plan, kind and input hash', () => {
  const p = project(), pairId = 'h--t';
  const input = { combination_id: pairId, hook_take_id: 'take1', hook_revision: 1, title_revision: 1, input_hash: 'hash' };
  p.outputs = [{ ...input, render_job_id: 'render1', plan_revision: 1, kind: 'draft', metadata: {}, url: 'https://media/draft', expires_at: 123 }] as RenderOutput[];
  const state = { ...initialSession(), project: p, jobs: { render1: job('render1', 'succeeded') },
    renders: [{ requestId: 'r', key: renderKey(p, [pairId]), kind: 'draft' as const, pairIds: [pairId], jobId: 'render1', inputs: [input] }] };
  assert.equal(matchingOutput(state, pairId, 'draft')?.url, 'https://media/draft');
  assert.equal(matchingOutput(state, pairId, 'export'), undefined);
  state.jobs.render1.state = 'running'; assert.equal(matchingOutput(state, pairId, 'draft'), undefined);
  state.jobs.render1.state = 'succeeded';
  for (const mutate of [(p: ProjectState) => p.hooks[0].take_id = 'retake', (p: ProjectState) => p.titles[0].text_revision++, (p: ProjectState) => p.plan.revision++, (p: ProjectState) => p.outputs[0].input_hash = 'wrong']) {
    const changed = structuredClone(state); mutate(changed.project); assert.equal(matchingOutput(changed, pairId, 'draft'), undefined);
  }
});

test('restart resumes acknowledged video parts and independently keeps the audio job', async () => {
  const sent: number[] = [], saved: string[] = [];
  const transport: typeof fetch = async (url, options) => {
    const path = String(url);
    if (path.endsWith('/projects/p')) return Response.json(project());
    if (path.includes('/jobs/')) return Response.json(job(path.split('/').at(-1)!));
    if (path.endsWith('/audio')) return Response.json({ job_id: 'audio1' });
    if (path.endsWith('/uploads/up1')) return Response.json({ upload_id: 'up1', sha256: file.sha256, size_bytes: bytes.length, part_size: 5,
      parts: [{ part: 0, size_bytes: 5, sha256: checksum(bytes.slice(0, 5)) }] });
    if (path.includes('/parts/')) { sent.push(Number(path.split('/').at(-1))); return Response.json({}); }
    if (path.endsWith('/complete')) return Response.json({ job_id: 'video1' });
    throw new Error(`Unexpected ${options?.method} ${path}`);
  };
  const deps = dependencies(transport); deps.save = state => saved.push(JSON.stringify(state));
  const controller = new ProjectController({ ...initialSession(), projectId: 'p', baseUrl: 'https://api', sources: [{ ...recording(), uploadId: 'up1' }] }, deps);
  await controller.resume();
  assert.deepEqual(sent, [1, 2]);
  const persisted = JSON.parse(saved.at(-1)!);
  assert.equal(persisted.sources[0].audioJob, 'audio1'); assert.equal(persisted.sources[0].videoJob, 'video1');
  // Recover jobs whose IDs persisted before their first status fetch.
  persisted.jobs = {};
  const restored = new ProjectController(persisted, deps); await restored.refresh();
  assert.deepEqual(Object.keys(restored.state.jobs).sort(), ['audio1', 'video1']);
});

test('matching selects the newest source explicitly and ignores earlier takes', async () => {
  const p = project(), selected: string[] = [];
  p.hooks[0].candidates = ['s1', 's2'].map((id, i) => ({ source_id: id, take_id: `take${i + 1}`, confidence: 1, capture_revision: 1, clips: [], reason: '' }));
  const transport: typeof fetch = async (url, options) => {
    if (options?.method === 'PUT') { const id = JSON.parse(options.body as string).take_id; selected.push(id); p.hooks[0].take_id = id; return Response.json(p.hooks[0]); }
    return Response.json(p);
  };
  const sources = ['s1', 's2'].map(sourceId => ({ ...recording(), sourceId, role: 'hooks' as const,
    hookScripts: [{ hook_id: 'h', text: 'A spoken hook', capture_revision: 1, action_start_ms: null }] }));
  const controller = new ProjectController({ ...initialSession(), projectId: 'p', baseUrl: 'https://api', sources }, dependencies(transport));
  await controller.refresh(); assert.deepEqual(selected, ['take2']); assert.equal(controller.state.sources[1].selected, true);
});

test('a lost render response retries the persisted request identity', async () => {
  const requests: string[] = []; let fail = true;
  const transport: typeof fetch = async (url, options) => {
    const path = String(url);
    if (path.endsWith('/renders')) {
      const request = JSON.parse(options!.body as string); requests.push(request.request_id);
      if (fail) { fail = false; throw new Error('Connection lost after submission'); }
      return Response.json({ job_id: 'render1', inputs: [] });
    }
    if (path.includes('/jobs/')) return Response.json(job('render1'));
    return Response.json(project());
  };
  const deps = dependencies(transport);
  const controller = new ProjectController({ ...initialSession(), projectId: 'p', baseUrl: 'https://api' }, deps);
  await assert.rejects(controller.render('draft', ['h--t']));
  const restored = new ProjectController(structuredClone(controller.state), deps);
  await restored.render('draft', ['h--t']);
  assert.deepEqual(requests, ['request1', 'request1']);
  assert.equal(restored.state.renders[0].jobId, 'render1');
});

test('revision conflict preserves the body draft and fetches the saved revision', async () => {
  const p = project();
  const transport: typeof fetch = async (_url, options) => options?.method === 'PUT'
    ? Response.json({ error: { message: 'Revision conflict' } }, { status: 409 }) : Response.json({ ...p, plan: { ...p.plan, revision: 2 } });
  const controller = new ProjectController({ ...initialSession(), projectId: 'p', baseUrl: 'https://api', project: p }, dependencies(transport));
  await assert.rejects(controller.savePlan(p.plan));
  assert.equal(controller.state.planDraft?.revision, 1); assert.equal(controller.state.project?.plan.revision, 2);
});

test('media refresh returns a renewed signed URL only for matching completed exports', async () => {
  const p = project(), input = { combination_id: 'h--t', hook_take_id: 'take1', hook_revision: 1, title_revision: 1, input_hash: 'hash' };
  p.outputs = [{ ...input, render_job_id: 'r', plan_revision: 1, kind: 'export', metadata: {}, url: 'https://media/fresh', expires_at: 9999999 }];
  const controller = new ProjectController({ ...initialSession(), projectId: 'p', baseUrl: 'https://api', project: p,
    renders: [{ requestId: 'r1', key: renderKey(p, ['h--t']), kind: 'export', pairIds: ['h--t'], jobId: 'r', inputs: [input] }] }, dependencies(async url => Response.json(String(url).includes('/jobs/') ? job('r', 'succeeded') : p)));
  assert.equal(await controller.media('h--t', 'export'), 'https://media/fresh');
});
