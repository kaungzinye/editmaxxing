import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex } from '@noble/hashes/utils.js';
import type { JobCreated, UploadSession } from '../../../contracts/plan';

export interface ByteSource {
  size: number;
  read(start: number, end: number): Promise<Uint8Array<ArrayBuffer>>;
}
export function checksum(bytes: Uint8Array) { return bytesToHex(sha256(bytes)); }
export async function fileChecksum(file: ByteSource, progress?: (value: number) => void) {
  const hash = sha256.create();
  for (let offset = 0; offset < file.size; offset += 4 * 1024 * 1024) {
    hash.update(await file.read(offset, Math.min(file.size, offset + 4 * 1024 * 1024)));
    progress?.(Math.min(1, (offset + 4 * 1024 * 1024) / file.size));
  }
  return bytesToHex(hash.digest());
}
export class RequestError extends Error {
  constructor(public status: number, public response: unknown) {
    super(`HTTP ${status}\n${JSON.stringify(response, null, 2)}`);
  }
}
export class API {
  constructor(
    readonly baseURL: string,
    readonly token: string,
    readonly report: (label: string, result: unknown) => void = () => {},
    readonly transport: typeof fetch = fetch,
  ) {}
  async request<T>(path: string, method = 'GET', body?: unknown, headers: Record<string, string> = {}): Promise<T> {
    const bytes = body instanceof Uint8Array;
    const send = this.transport;
    const response = await send(`${this.baseURL.replace(/\/$/, '')}/api/v1${path}`, {
      method,
      headers: {
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        ...(body !== undefined ? { 'Content-Type': bytes ? 'application/octet-stream' : 'application/json' } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : bytes ? body as Uint8Array<ArrayBuffer> : JSON.stringify(body),
    });
    const text = await response.text();
    let result: unknown;
    try { result = JSON.parse(text); } catch { result = text; }
    const safe = result && typeof result === 'object' && 'project_token' in result
      ? { ...result, project_token: '[stored in token field]' } : result;
    this.report(`${method} ${path} → ${response.status}`, safe);
    if (!response.ok) throw new RequestError(response.status, result);
    return result as T;
  }
  /** The server's acknowledged checksums determine which byte ranges need sending. */
  async uploadOriginal(args: {
    projectId: string; sourceId: string; file: ByteSource; sha256: string;
    uploadId?: string; remember: (id: string) => Promise<void>;
    progress: (acknowledged: number, total: number) => void; paused: () => boolean;
  }): Promise<JobCreated | null> {
    const prefix = `/projects/${args.projectId}/sources/${args.sourceId}/video/uploads`;
    const session = args.uploadId
      ? await this.request<UploadSession>(`${prefix}/${args.uploadId}`)
      : await this.request<UploadSession>(prefix, 'POST', { size_bytes: args.file.size, sha256: args.sha256 });
    if (session.sha256 !== args.sha256 || session.size_bytes !== args.file.size) {
      throw new Error('The selected original differs from this upload session. Select the matching file.');
    }
    await args.remember(session.upload_id);
    const parts: { part: number; sha256: string }[] = [];
    const acknowledged = new Map(session.parts.map(part => [part.part, part]));
    let sent = 0;
    for (let offset = 0, part = 0; offset < args.file.size; offset += session.part_size, part++) {
      if (args.paused()) return null;
      const bytes = await args.file.read(offset, Math.min(args.file.size, offset + session.part_size));
      const digest = checksum(bytes);
      const ack = acknowledged.get(part);
      if (ack && (ack.sha256 !== digest || ack.size_bytes !== bytes.length)) {
        throw new Error(`Acknowledged part ${part} differs from the selected file.`);
      }
      if (!ack) await this.request(`${prefix}/${session.upload_id}/parts/${part}`, 'PUT', bytes, { 'X-Content-SHA256': digest });
      parts.push({ part, sha256: digest });
      sent += bytes.length;
      args.progress(sent, args.file.size);
    }
    if (args.paused()) return null;
    return this.request<JobCreated>(`${prefix}/${session.upload_id}/complete`, 'POST', { parts });
  }
}
