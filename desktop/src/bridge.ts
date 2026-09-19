import { invoke } from '@tauri-apps/api/core';

export const isDesktop = '__TAURI_INTERNALS__' in window;
const operations = {
  connect: ['no_listen'], snapshot: [], command: ['text'], listen: ['enabled', 'once'],
  stop: [], emergency: [], settings: ['values'], devices: [], files: ['query', 'kind'],
  index: [], windows: [], voice_test: [], download_models: [], quit: [],
  owner_status: [], owner_set_pin: ['pin'], owner_delete_pin: [],
  owner_voice_enroll: ['samples', 'seconds', 'device'], owner_delete_voice: [],
  owner_face_camera: ['samples', 'camera'], owner_face_images: ['paths'], owner_delete_face: [],
  personal_voice_status: [], personal_voice_reload: [], personal_voice_delete: [],
  personal_voice_record: ['consent'], personal_voice_import: ['path', 'consent'],
} as const;
export type EngineOperation = keyof typeof operations;

export function request<T = unknown>(op: EngineOperation, payload: Record<string, unknown> = {}): Promise<T> {
  if (!isDesktop) return Promise.reject(new Error('Open the installed Jarvis desktop app to use voice and computer controls.'));
  if (!Object.hasOwn(operations, op) || Object.keys(payload).some(key => !(operations[op] as readonly string[]).includes(key))) {
    return Promise.reject(new Error('Unexpected desktop request fields.'));
  }
  return invoke<T>('engine_request', { request: { ...payload, op } });
}
export { invoke };
