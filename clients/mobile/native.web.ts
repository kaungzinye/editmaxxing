import { randomUUID } from 'expo-crypto';
import { snapshotStore, readToken, saveToken } from '@editmaxxing/client/journal';
import type { LocalFile } from '@editmaxxing/client/files';
import { initialSession, ProjectController, type Recording, type Session } from './controller';
import { API_BASE_URL } from './config';

const journal = snapshotStore<Session>(`editmaxxing-mobile-${encodeURIComponent(API_BASE_URL)}`, initialSession);
export function createController() {
  return new ProjectController(journal.read(), {
    save: value => journal.save(value), saveToken, readToken, uuid: randomUUID,
    read: (file: LocalFile) => ({ size: file.size, async read(start, end) {
      const response = await fetch(file.uri, { headers: { Range: `bytes=${start}-${end - 1}` } });
      if (!response.ok) throw new Error('The saved recording is unavailable.');
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length !== end - start) throw new Error('The saved recording returned an incomplete byte range.');
      return bytes;
    } }),
    async prepare(clip, hookScripts) {
      const source = await fetch(clip.uri!);
      if (!source.ok) throw new Error('Select the video again to read its contents.');
      const response = await fetch(`${API_BASE_URL}/local/prepare`, {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: await source.blob(),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? 'Video preparation failed.');
      const prepared = await response.json() as Pick<Recording, 'duration' | 'timing' | 'audioTiming' | 'original' | 'audio'>;
      return { ...prepared, sourceId: `src_${randomUUID().replaceAll('-', '')}`,
        role: hookScripts.length ? 'hooks' : 'body', hookScripts,
        clip: { ...clip, uri: prepared.original!.uri, duration: prepared.duration / 1000 } };
    },
  });
}

export async function saveExport(controller: ProjectController, pairId: string) {
  const response = await fetch(await controller.media(pairId, 'export'));
  if (!response.ok) throw new Error('The export could not be downloaded.');
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url; link.download = `editmaxxing-${pairId}.mp4`;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
