import { File, Paths } from 'expo-file-system';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import type { HookScript, Plan, SourceRole, TimingManifest } from '../../../contracts/plan';
import type { LocalFile } from './files';

export interface SourceJournal {
  sourceId: string;
  role: SourceRole;
  duration: number;
  timing: TimingManifest;
  audioTiming: TimingManifest;
  original?: LocalFile;
  audio?: LocalFile;
  uploadId?: string;
  registered?: boolean;
  hookScripts: HookScript[];
}
export interface ProjectJournal {
  baseUrl: string;
  projectId: string;
  name: string;
  sources: SourceJournal[];
  planDraft?: Plan;
  jobs: string[];
}
export interface Journal { projects: ProjectJournal[] }
const key = 'editmaxxing-endpoint-lab';
let sequence = 0;
export function readJournal(): Journal {
  if (Platform.OS === 'web') {
    const text = localStorage.getItem(key);
    return text ? JSON.parse(text) : { projects: [] };
  }
  const snapshots = [0, 1].flatMap(slot => {
    try {
      const file = new File(Paths.document, `endpoint-lab-${slot}.json`);
      if (!file.exists) return [];
      const entry = JSON.parse(file.textSync()) as { sequence: number; journal: Journal };
      return typeof entry.sequence === 'number' && Array.isArray(entry.journal.projects) ? [entry] : [];
    } catch { return []; }
  }).sort((a, b) => b.sequence - a.sequence);
  sequence = snapshots[0]?.sequence ?? 0;
  return snapshots[0]?.journal ?? { projects: [] };
}
export function saveJournal(journal: Journal) {
  if (Platform.OS === 'web') localStorage.setItem(key, JSON.stringify(journal));
  else {
    sequence++;
    new File(Paths.document, `endpoint-lab-${sequence % 2}.json`).write(JSON.stringify({ sequence, journal }));
  }
}
const tokenKey = (projectId: string) => `editmaxxing.${projectId}`;
export async function saveToken(projectId: string, token: string) {
  if (Platform.OS === 'web') localStorage.setItem(tokenKey(projectId), token);
  else await SecureStore.setItemAsync(tokenKey(projectId), token);
}
export async function readToken(projectId: string) {
  return Platform.OS === 'web' ? localStorage.getItem(tokenKey(projectId)) ?? '' : await SecureStore.getItemAsync(tokenKey(projectId)) ?? '';
}

export function snapshotStore<T>(name: string, initial: () => T) {
  let sequence = 0;
  return {
    read(): T {
      const snapshots = [0, 1].flatMap(slot => {
        try {
          const text = Platform.OS === 'web' ? localStorage.getItem(`${name}-${slot}`)
            : new File(Paths.document, `${name}-${slot}.json`).textSync();
          if (!text) return [];
          const entry = JSON.parse(text) as { sequence: number; value: T };
          return Number.isInteger(entry.sequence) && entry.value ? [entry] : [];
        } catch { return []; }
      }).sort((a, b) => b.sequence - a.sequence);
      sequence = snapshots[0]?.sequence ?? 0;
      return snapshots[0]?.value ?? initial();
    },
    save(value: T) {
      const text = JSON.stringify({ sequence: ++sequence, value });
      if (Platform.OS === 'web') localStorage.setItem(`${name}-${sequence % 2}`, text);
      else new File(Paths.document, `${name}-${sequence % 2}.json`).write(text);
    },
  };
}
