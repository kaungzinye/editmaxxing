import { randomUUID } from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { finalizeRecording, extractedFile, readFile } from '@editmaxxing/client/files';
import { snapshotStore, readToken, saveToken } from '@editmaxxing/client/journal';
import { extractAudio, extractionAvailable, inspectSource } from '@editmaxxing/client/source-audio';
import { initialSession, ProjectController, type Session } from './controller';
import { API_BASE_URL } from './config';

const journal = snapshotStore<Session>(`editmaxxing-mobile-${encodeURIComponent(API_BASE_URL)}`, initialSession);
export function createController() {
  return new ProjectController(journal.read(), {
    save: value => journal.save(value), saveToken, readToken, uuid: randomUUID, read: readFile,
    async prepare(clip, hookScripts) {
      if (!extractionAvailable) throw new Error('Open the iOS development build to process recordings.');
      const original = await finalizeRecording(clip.uri!, clip.name);
      const { duration_ms } = await inspectSource(original.uri);
      const extraction = await extractAudio(original.uri);
      if (Math.abs(extraction.source_duration_ms - duration_ms) > 1) throw new Error('The recording duration differs from its extracted audio.');
      return { sourceId: `src_${randomUUID().replaceAll('-', '')}`, role: hookScripts.length ? 'hooks' : 'body',
        duration: duration_ms, timing: { media_origin_ms: 0, encoder_delay_ms: 0, duration_ms, sample_rate: 48000, extractor: 'original' },
        audioTiming: extraction.timing, original, audio: await extractedFile(extraction.uri), hookScripts,
        clip: { ...clip, uri: original.uri, duration: duration_ms / 1000 } };
    },
  });
}
export async function saveExport(controller: ProjectController, pairId: string) {
  const directory = new Directory(Paths.cache, 'exports');
  directory.create({ intermediates: true, idempotent: true });
  const destination = new File(directory, `${randomUUID()}.mp4`);
  try {
    let url = await controller.media(pairId, 'export');
    try { await File.downloadFileAsync(url, destination); }
    catch { url = await controller.media(pairId, 'export'); await File.downloadFileAsync(url, destination, { idempotent: true }); }
    await Sharing.shareAsync(destination.uri, { mimeType: 'video/mp4', UTI: 'public.mpeg-4', dialogTitle: 'Save video' });
  } finally { if (destination.exists) destination.delete(); }
}
