// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import { defaults } from './types';
import PersonalVoiceSettings from './PersonalVoiceSettings';
import { request } from './bridge';
vi.mock('./bridge', () => ({ request: vi.fn(async () => ({ reference_ready: false, model_state: 'not_loaded' })) }));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => {}) }));
test('personal recording requires consent and Stop stays available while recording', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement('div');
  const root = createRoot(host);
  let finish: (value: unknown) => void = () => {};
  vi.mocked(request).mockImplementation(async op => op === 'personal_voice_record' ? new Promise(resolve => { finish = resolve; }) : op === 'snapshot' ? defaults : { reference_ready: false, model_state: 'not_loaded' });
  try {
    await act(async () => root.render(<PersonalVoiceSettings connected values={defaults.settings} change={vi.fn()} save={vi.fn()} onError={vi.fn()}/>));
    const button = (text: string) => Array.from(host.querySelectorAll('button')).find(b => b.textContent?.includes(text))!;
    expect(button('Record 8 seconds').disabled).toBe(true);
    await act(async () => (host.querySelector('[aria-label="Consent to personal voice synthesis"]') as HTMLInputElement).click());
    await act(async () => button('Record 8 seconds').click());
    expect(button('Record 8 seconds').disabled).toBe(true);
    expect(button('Stop').disabled).toBe(false);
    await act(async () => button('Stop').click());
    expect(request).toHaveBeenCalledWith('emergency');
    await act(async () => finish({ reference_ready: true, model_state: 'not_loaded' }));
  } finally { await act(async () => root.unmount()); }
});
