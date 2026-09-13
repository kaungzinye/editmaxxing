import * as DocumentPicker from 'expo-document-picker';
import { Directory, File, Paths } from 'expo-file-system';
import { Platform } from 'react-native';
import { randomUUID } from 'expo-crypto';
import { fileChecksum, type ByteSource } from './api';

export interface LocalFile { uri: string; name: string; size: number; sha256: string; mime: string }
const browserFiles = new Map<string, Blob>();
export function readFile(file: LocalFile): ByteSource {
  if (Platform.OS === 'web') {
    const blob = browserFiles.get(file.uri);
    if (!blob) throw new Error('Select the same file to resume this browser upload after a page reload.');
    return { size: blob.size, read: async (start, end) => new Uint8Array(await blob.slice(start, end).arrayBuffer()) };
  }
  const native = new File(file.uri);
  if (!native.exists) throw new Error(`Saved file is missing: ${file.name}`);
  return { size: native.size, read: async (start, end) => new Uint8Array(await native.slice(start, end).arrayBuffer()) };
}
export async function pickFile(kind: 'audio' | 'original', progress: (v: number) => void): Promise<LocalFile | null> {
  const selected = await DocumentPicker.getDocumentAsync({ type: kind === 'audio' ? 'audio/*' : 'video/*', copyToCacheDirectory: true });
  if (selected.canceled) return null;
  const asset = selected.assets[0];
  let uri = asset.uri;
  let size = asset.size ?? 0;
  if (Platform.OS === 'web') {
    const blob = asset.file;
    if (!blob) throw new Error('The browser file picker did not return file bytes.');
    browserFiles.set(uri, blob);
    size = blob.size;
  } else {
    const directory = new Directory(Paths.document, kind === 'original' ? 'originals' : 'audio');
    directory.create({ intermediates: true, idempotent: true });
    const destination = new File(directory, `${randomUUID()}-${asset.name.replace(/[^A-Za-z0-9._-]/g, '_')}`);
    new File(uri).copy(destination);
    uri = destination.uri;
    size = destination.size;
  }
  const file = { uri, name: asset.name, size, mime: asset.mimeType ?? 'application/octet-stream', sha256: '' };
  file.sha256 = await fileChecksum(readFile(file), progress);
  return file;
}
export async function extractedFile(uri: string): Promise<LocalFile> {
  const file = new File(uri);
  const result = { uri, name: file.name, size: file.size, mime: 'audio/mp4', sha256: '' };
  result.sha256 = await fileChecksum(readFile(result));
  return result;
}

export function unlinkedOriginals(knownUris: string[]): LocalFile[] {
  if (Platform.OS === 'web') return [];
  const directory = new Directory(Paths.document, 'originals');
  if (!directory.exists) return [];
  return directory.list().filter((item): item is File => item instanceof File && !knownUris.includes(item.uri)).map(file => ({
    uri: file.uri, name: file.name, size: file.size, mime: 'video/mp4', sha256: '',
  }));
}
export async function recoverOriginal(file: LocalFile) {
  return { ...file, sha256: await fileChecksum(readFile(file)) };
}

/** Copy camera and picker output into durable storage before registration. */
export async function finalizeRecording(uri: string, name: string): Promise<LocalFile> {
  if (Platform.OS !== 'ios') throw new Error('Open the iOS development build to process recordings.');
  const directory = new Directory(Paths.document, 'originals');
  directory.create({ intermediates: true, idempotent: true });
  const destination = new File(directory, `${randomUUID()}.mp4`);
  new File(uri).copy(destination);
  const result = { uri: destination.uri, name, size: destination.size, mime: 'video/mp4', sha256: '' };
  result.sha256 = await fileChecksum(readFile(result));
  return result;
}
