// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
const { nativeInvoke } = vi.hoisted(() => ({ nativeInvoke: vi.fn().mockResolvedValue({ accepted: true }) }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: nativeInvoke }));
beforeEach(() => { vi.resetModules(); nativeInvoke.mockClear(); });
afterEach(() => { Reflect.deleteProperty(window, '__TAURI_INTERNALS__'); });

test('browser preview cannot execute desktop operations', async () => {
  const { request } = await import('./bridge');
  await expect(request('command', { text: 'open notepad' })).rejects.toThrow('desktop app');
  expect(nativeInvoke).not.toHaveBeenCalled();
});
test('renderer cannot override operation or supply authentication', async () => {
  Object.defineProperty(window, '__TAURI_INTERNALS__', { value: {}, configurable: true });
  const { request } = await import('./bridge');
  for (const payload of [{ op: 'shell' }, { principal: 'owner' }, { id: 100 }]) {
    await expect(request('command', { text: 'hi', ...payload })).rejects.toThrow('Unexpected');
  }
  expect(nativeInvoke).not.toHaveBeenCalled();
});
test('validated request uses local Tauri IPC', async () => {
  Object.defineProperty(window, '__TAURI_INTERNALS__', { value: {}, configurable: true });
  const { request } = await import('./bridge');
  await request('command', { text: 'open notepad' });
  expect(nativeInvoke).toHaveBeenCalledWith('engine_request', { request: { text: 'open notepad', op: 'command' } });
});
test('emergency request needs no normal command payload', async () => {
  Object.defineProperty(window, '__TAURI_INTERNALS__', { value: {}, configurable: true });
  const { request } = await import('./bridge');
  await request('emergency');
  expect(nativeInvoke).toHaveBeenCalledWith('engine_request', { request: { op: 'emergency' } });
});
