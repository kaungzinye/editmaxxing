/** Run against an isolated fixture-enabled API with prepared fixture media. */
import { readFile, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { API, checksum } from '../src/api';
import type { Job, JobCreated, Plan, ProjectCreated, ProjectState } from '../../../contracts/plan';

async function main() {
  const [baseURL, originalPath, audioPath, durationText] = process.argv.slice(2);
  if (!baseURL || !originalPath || !audioPath || !durationText) throw new Error('Usage: npm run smoke -- BASE_URL ORIGINAL AUDIO DURATION_MS');
  const original = new Uint8Array(await readFile(originalPath));
  const audio = new Uint8Array(await readFile(audioPath));
  const duration = Number(durationText);
  const project = await new API(baseURL, '').request<ProjectCreated>('/projects', 'POST', { name: 'Endpoint lab smoke', target_duration_ms: 120000 });
  const api = new API(baseURL, project.project_token);
  const prefix = `/projects/${project.project_id}`;
  const timing = { media_origin_ms: 0, encoder_delay_ms: 0, duration_ms: duration, sample_rate: 16000, extractor: 'fixture-prepared' };
  const wait = async (job: JobCreated) => {
    for (let attempts = 0; attempts < 120; attempts++) {
      const state = await api.request<Job>(`/jobs/${job.job_id}`);
      if (state.state === 'succeeded') return state;
      if (state.state === 'failed' || state.state === 'cancelled') throw new Error(JSON.stringify(state.error));
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    throw new Error('Job exceeds two minute smoke deadline');
  };
  await api.request(`${prefix}/templates`, 'PUT', { templates: [1, 2, 3, 4].map(i => ({ id: `fixture_title_${i}`, pattern: `Fixture ${i}: {topic}`, slots: ['topic'] })) });
  const register = async (sourceId: string, role: 'body' | 'hooks', hookScripts: { hook_id: string; text: string }[] = []) => {
    await api.request(`${prefix}/sources`, 'POST', { source_id: sourceId, role, duration_ms: duration, fingerprint: checksum(original), timing, hook_scripts: hookScripts });
    await api.request(`${prefix}/sources/${sourceId}/fixture`, 'POST');
    const analysisJob = await api.request<JobCreated>(`${prefix}/sources/${sourceId}/audio`, 'PUT', audio, { 'X-Content-SHA256': checksum(audio), 'X-Timing-Manifest': JSON.stringify(timing) });
    const videoJob = await api.uploadOriginal({ projectId: project.project_id, sourceId, file: { size: original.length, read: async (start, end) => original.slice(start, end) }, sha256: checksum(original), remember: async () => {}, progress: () => {}, paused: () => false });
    assert.ok(videoJob);
    await Promise.all([wait(analysisJob), wait(videoJob)]);
  };
  await register('body', 'body');
  let state = await api.request<ProjectState>(prefix);
  assert.ok(state.plan.clips.length);
  assert.equal(state.hooks.length, 4);
  const edited = structuredClone(state.plan);
  edited.clips[0].source_start_ms += 10;
  const saved = await api.request<Plan>(`${prefix}/plan`, 'PUT', { base_revision: state.plan.revision, plan: edited });
  assert.equal(saved.revision, state.plan.revision + 1);
  const bodyClips = structuredClone(saved.clips);
  await register('hooks', 'hooks', state.hooks.map(h => ({ hook_id: h.id, text: h.proposed_text })));
  state = await api.request<ProjectState>(prefix);
  assert.deepEqual(state.plan.clips, bodyClips);
  const hook = state.hooks.find(h => h.take_id);
  assert.ok(hook);
  const rendered = await wait(await api.request<JobCreated>(`${prefix}/renders`, 'POST', { plan_revision: saved.revision, kind: 'draft', combinations: [{ id: 'smoke', hook_id: hook.id, visual_title_id: null, use_title: false }] }));
  const result = rendered.result as { outputs: { url: string; plan_revision: number }[] };
  assert.equal(result.outputs[0].plan_revision, saved.revision);
  const video = await fetch(result.outputs[0].url);
  assert.equal(video.status, 200);
  assert.match(video.headers.get('content-type') ?? '', /video\/mp4/);
  const outputPath = '/tmp/editmaxxing-endpoint-smoke.mp4';
  await writeFile(outputPath, new Uint8Array(await video.arrayBuffer()));
  console.log(JSON.stringify({ project_id: project.project_id, revision: saved.revision, hooks: state.hooks.length, rendered: true, downloaded_video: outputPath }, null, 2));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
