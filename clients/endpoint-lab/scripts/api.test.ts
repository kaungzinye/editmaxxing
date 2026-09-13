import assert from 'node:assert/strict';
import { test } from 'node:test';
import { API, RequestError, checksum, fileChecksum } from '@editmaxxing/client/api';
import { rememberSourceChanges } from '@editmaxxing/client/transfers';
import type { ProjectJournal, SourceJournal } from '@editmaxxing/client/journal';

const bytes = new TextEncoder().encode('abcdefghijklmn');
const file = { size: bytes.length, read: async (start: number, end: number) => bytes.slice(start, end) };
const hash = checksum(bytes);

test('resume verifies acknowledged parts, sends missing bytes and completes with ordered hashes', async () => {
  const paths: string[] = [];
  let remembered = '';
  let progress = 0;
  const api = new API('http://api.test/', 'project-secret', () => {}, async (url, request) => {
    const path = String(url); paths.push(path);
    assert.equal(new Headers(request?.headers).get('Authorization'), 'Bearer project-secret');
    if (path.endsWith('/uploads/session')) return Response.json({ upload_id: 'session', sha256: hash, size_bytes: bytes.length, part_size: 5, parts: [{ part: 0, sha256: checksum(bytes.slice(0, 5)), size_bytes: 5 }], state: 'uploading', expires_at: 9999999999 });
    if (path.includes('/parts/')) {
      const part = Number(path.split('/').at(-1));
      const expected = bytes.slice(part * 5, (part + 1) * 5);
      assert.deepEqual(request?.body, expected);
      assert.equal(new Headers(request?.headers).get('X-Content-SHA256'), checksum(expected));
      return Response.json({ part, sha256: checksum(expected), size_bytes: expected.length });
    }
    const complete = JSON.parse(request?.body as string);
    assert.deepEqual(complete.parts.map((p: { part: number }) => p.part), [0, 1, 2]);
    assert.deepEqual(complete.parts.map((p: { sha256: string }) => p.sha256), [checksum(bytes.slice(0, 5)), checksum(bytes.slice(5, 10)), checksum(bytes.slice(10))]);
    return Response.json({ job_id: 'verify_job' }, { status: 202 });
  });
  assert.equal(await fileChecksum(file), hash);
  const result = await api.uploadOriginal({ projectId: 'project', sourceId: 'source', file, sha256: hash, uploadId: 'session', remember: async id => { remembered = id; }, progress: done => { progress = done; }, paused: () => false });
  assert.equal(remembered, 'session');
  assert.equal(progress, bytes.length);
  assert.deepEqual(result, { job_id: 'verify_job' });
  assert.equal(paths.some(path => path.endsWith('/parts/0')), false);
});

test('checksum mismatch fails before writing or completing an upload', async () => {
  let calls = 0;
  const api = new API('http://api.test', 'token', () => {}, async () => {
    calls++;
    return Response.json({ upload_id: 'session', sha256: hash, size_bytes: bytes.length, part_size: 5, parts: [{ part: 0, sha256: 'bad', size_bytes: 5 }] });
  });
  await assert.rejects(api.uploadOriginal({ projectId: 'p', sourceId: 's', file, sha256: hash, uploadId: 'session', remember: async () => {}, progress: () => {}, paused: () => false }), /Acknowledged part 0 differs/);
  assert.equal(calls, 1);
});

test('revision conflicts retain the server response for raw inspection', async () => {
  const detail = { error: { code: 'revision_conflict', message: 'Saved revision is 4.', retryable: false } };
  const api = new API('http://api.test', 'token', () => {}, async () => Response.json(detail, { status: 409 }));
  await assert.rejects(api.request('/projects/p/plan', 'PUT', { base_revision: 3 }), error => {
    assert.ok(error instanceof RequestError);
    assert.equal(error.status, 409);
    assert.deepEqual(error.response, detail);
    return true;
  });
});

test('browser transport receives a standalone call', async () => {
  const transport = function (this: unknown): Promise<Response> {
    assert.equal(this, undefined);
    return Promise.resolve(Response.json({ status: 'ok' }));
  };
  const api = new API('http://api.test', '', () => {}, transport);
  assert.deepEqual(await api.request('/healthz'), { status: 'ok' });
});

test('upload acknowledgement preserves audio prepared during the upload request', () => {
  const timing = { media_origin_ms: 0, encoder_delay_ms: 0, duration_ms: 3000, sample_rate: 16000, extractor: 'fixture' };
  const captured: SourceJournal = { sourceId: 'body', role: 'body', duration: 3000, timing, audioTiming: timing, hookScripts: [] };
  const audio = { uri: 'file:///Documents/audio/body.m4a', name: 'body.m4a', size: 100, sha256: 'audio-checksum', mime: 'audio/mp4' };
  const prepared = { ...captured, audio, audioTiming: { ...timing, media_origin_ms: 200 } };
  const project: ProjectJournal = { baseUrl: 'http://api.test', projectId: 'project', name: 'test', sources: [prepared], jobs: [] };
  const saved = rememberSourceChanges(project, captured, { uploadId: 'upload-session' });
  assert.equal(saved.sources[0].uploadId, 'upload-session');
  assert.deepEqual(saved.sources[0].audio, audio);
  assert.equal(saved.sources[0].audioTiming.media_origin_ms, 200);
  const uploading = rememberSourceChanges({ ...project, sources: [captured] }, captured, { uploadId: 'upload-session' });
  const extracted = rememberSourceChanges(uploading, captured, { audio, audioTiming: prepared.audioTiming });
  assert.deepEqual(extracted, saved);
});

test('draft captions and spoken words follow reordered clip occurrences and clamp to trims', async () => {
  const { remapDraftCaptions } = await import('../src/editor');
  const previous = { clips: [
    { id: 'a', source_start_ms: 0, source_end_ms: 1000 },
    { id: 'b', source_start_ms: 1000, source_end_ms: 2000 },
  ], captions: [{ id: 'caption', clip_id: 'a', start_ms: 100, end_ms: 500, words: [
    { word_id: 'one', text: 'one', start_ms: 100, end_ms: 180 },
    { word_id: 'two', text: 'two', start_ms: 180, end_ms: 300 },
    { word_id: 'three', text: 'three', start_ms: 300, end_ms: 500 },
    { word_id: null, text: 'creator text', start_ms: null, end_ms: null },
  ] }], target_duration_ms: 120000 } as import('../../../contracts/plan').Plan;
  const reordered = remapDraftCaptions(previous, { ...previous, clips: [...previous.clips].reverse() });
  assert.equal(reordered.captions[0].start_ms, 1100);
  assert.deepEqual(reordered.captions[0].words.map(word => [word.start_ms, word.end_ms]), [[1100, 1180], [1180, 1300], [1300, 1500], [null, null]]);
  const trimmed = remapDraftCaptions(reordered, { ...reordered, clips: reordered.clips.map(c => c.id === 'a' ? { ...c, source_start_ms: 200 } : c) });
  assert.equal(trimmed.captions[0].start_ms, 1000);
  assert.equal(trimmed.captions[0].end_ms, 1300);
  assert.deepEqual(trimmed.captions[0].words, [
    { word_id: 'two', text: 'two', start_ms: 1000, end_ms: 1100 },
    { word_id: 'three', text: 'three', start_ms: 1100, end_ms: 1300 },
    { word_id: null, text: 'creator text', start_ms: null, end_ms: null },
  ]);
  const endTrimmed = remapDraftCaptions(trimmed, { ...trimmed, clips: trimmed.clips.map(c => c.id === 'a' ? { ...c, source_end_ms: 350 } : c) });
  assert.equal(endTrimmed.captions[0].end_ms, 1150);
  assert.equal(endTrimmed.captions[0].words[1].end_ms, 1150);
});

test('repeated source ranges retain each caption word occurrence on the timeline', async () => {
  const { remapDraftCaptions } = await import('../src/editor');
  const previous = { clips: [
    { id: 'first', source_id: 'body', source_start_ms: 2000, source_end_ms: 3000 },
    { id: 'repeat', source_id: 'body', source_start_ms: 2000, source_end_ms: 3000 },
  ], captions: [
    { id: 'first-caption', clip_id: 'first', start_ms: 100, end_ms: 500, words: [{ word_id: 'hello', text: 'hello', start_ms: 100, end_ms: 500 }] },
    { id: 'repeat-caption', clip_id: 'repeat', start_ms: 1100, end_ms: 1500, words: [{ word_id: 'hello', text: 'hello', start_ms: 1100, end_ms: 1500 }] },
  ], target_duration_ms: 120000 } as import('../../../contracts/plan').Plan;
  const reordered = remapDraftCaptions(previous, { ...previous, clips: [...previous.clips].reverse() });
  assert.equal(reordered.captions.find(caption => caption.clip_id === 'repeat')?.words[0].start_ms, 100);
  assert.equal(reordered.captions.find(caption => caption.clip_id === 'first')?.words[0].start_ms, 1100);
  const removed = remapDraftCaptions(reordered, { ...reordered, clips: reordered.clips.filter(clip => clip.id === 'first') });
  assert.equal(removed.captions.length, 1);
  assert.equal(removed.captions[0].words[0].start_ms, 100);
});

test('a cue leaves the draft when a trim removes every spoken word', async () => {
  const { remapDraftCaptions } = await import('../src/editor');
  const previous = { clips: [{ id: 'a', source_start_ms: 0, source_end_ms: 1000 }], captions: [
    { id: 'caption', clip_id: 'a', start_ms: 100, end_ms: 500, words: [{ word_id: 'hello', text: 'hello', start_ms: 100, end_ms: 300 }] },
  ], target_duration_ms: 120000 } as import('../../../contracts/plan').Plan;
  const trimmed = remapDraftCaptions(previous, { ...previous, clips: [{ ...previous.clips[0], source_start_ms: 350 }] });
  assert.deepEqual(trimmed.captions, []);
});

test('stored caption words with absent timestamps receive null timing on remap', async () => {
  const { remapDraftCaptions } = await import('../src/editor');
  const previous = { clips: [
    { id: 'a', source_start_ms: 0, source_end_ms: 1000 },
    { id: 'b', source_start_ms: 1000, source_end_ms: 2000 },
  ], captions: [{ id: 'caption', clip_id: 'a', start_ms: 100, end_ms: 500, words: [
    { word_id: 'hello', text: 'hello' },
    { word_id: null, text: 'creator text', start_ms: null, end_ms: null },
  ] }], target_duration_ms: 120000 } as import('../../../contracts/plan').Plan;
  const reordered = remapDraftCaptions(previous, { ...previous, clips: [...previous.clips].reverse() });
  assert.equal(reordered.captions[0].start_ms, 1100);
  assert.deepEqual(reordered.captions[0].words, [
    { word_id: 'hello', text: 'hello', start_ms: null, end_ms: null },
    { word_id: null, text: 'creator text', start_ms: null, end_ms: null },
  ]);
});
