import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { open } from '@tauri-apps/plugin-dialog';
import { AudioLines, Mic, RefreshCw, Square } from 'lucide-react';
import { request } from './bridge';
import type { Settings, Snapshot } from './types';

interface VoiceStatus { reference_ready: boolean; runtime_available: boolean; model_state: string; model_configured: boolean }
interface Props {
  connected: boolean; values: Settings;
  change: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  save: (values: Partial<Settings>) => Promise<void>;
  onError: (message: string) => void;
}
export default function PersonalVoiceSettings({ connected, values, change, save, onError }: Props) {
  const [status, setStatus] = useState<VoiceStatus>();
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [progress, setProgress] = useState('');
  const refresh = () => request<VoiceStatus>('personal_voice_status').then(setStatus).catch(e => onError(String(e)));
  useEffect(() => {
    if (!connected) return;
    void refresh();
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void listen<{event: string; data: unknown}>('engine-event', event => {
      if (event.payload.event === 'personal_voice_progress') setProgress(String(event.payload.data));
    }).then(fn => { if (disposed) fn(); else cleanup = fn; }).catch(e => onError(String(e)));
    return () => { disposed = true; cleanup?.(); };
  }, [connected]);
  async function manage(op: 'personal_voice_record'|'personal_voice_import'|'personal_voice_delete'|'personal_voice_reload', payload = {}) {
    setPending(true);
    try {
      setStatus(await request<VoiceStatus>(op, payload));
      const next = await request<Snapshot>('snapshot');
      change('voice_reference', next.settings.voice_reference);
      change('voice_consent', next.settings.voice_consent);
      if (op === 'personal_voice_delete') change('voice_provider', 'windows');
    } catch (e) { onError(String(e)); }
    finally { setPending(false); setProgress(''); }
  }
  async function chooseReference() {
    try {
      const path = await open({ multiple: false, title: 'Choose your own 3–30 second PCM WAV recording', filters: [{ name: 'WAV recording', extensions: ['wav'] }] });
      if (typeof path === 'string') await manage('personal_voice_import', { path, consent });
    } catch (e) { onError(String(e)); }
  }
  async function chooseModel() {
    try {
      const path = await open({ multiple: false, title: 'Choose a local Pocket TTS configuration', filters: [{ name: 'Model configuration', extensions: ['yaml', 'yml'] }] });
      if (typeof path === 'string') change('voice_model_config', path);
    } catch (e) { onError(String(e)); }
  }
  return <section className="panel settings-section">
    <div className="section-heading"><h3><AudioLines size={18}/> Personal speech</h3><button className="text-link" disabled={!connected || pending} onClick={() => void refresh()}><RefreshCw size={13}/> Refresh status</button></div>
    <div className="settings-fields">
      <label>Voice engine<select aria-label="Voice engine" value={values.voice_provider} onChange={e => change('voice_provider', e.target.value)}>
        <option value="windows">System voice</option><option value="pocket">Personal local voice · Pocket TTS</option><option disabled>Online fallback · unavailable, disabled</option>
      </select></label>
      <p>Personal speech uses your recording locally. It does not authenticate you. If it cannot run, the system voice speaks instead.</p>
      <div className="model-row"><span>Your reference</span><b>{status?.reference_ready ? 'Recording configured' : 'Not configured'}</b></div>
      <div className="model-row"><span>Local model</span><b>{status?.model_state === 'loaded' ? 'Loaded' : status?.model_state === 'unavailable' ? 'Unavailable — using system voice' : 'Not loaded / not verified'}</b></div>
      <small>{status?.runtime_available ? 'Local Python runtime found.' : 'Local Python runtime not verified.'} Model weights must be installed separately. No audio is uploaded.</small>
      <label><input type="checkbox" aria-label="Consent to personal voice synthesis" checked={consent} onChange={e => setConsent(e.target.checked)}/> This is my voice, and I allow this recording to be used for local speech synthesis.</label>
      <div className="voice-test"><button className="button compact" disabled={!connected || pending || !consent} onClick={() => void manage('personal_voice_record', { consent })}><Mic size={15}/> Record 8 seconds</button><button className="button compact" disabled={!connected || pending || !consent} onClick={() => void chooseReference()}>Choose my WAV</button><button className="button compact" disabled={!connected} onClick={() => void request('emergency').catch(e => onError(String(e)))}><Square size={13}/> Stop</button></div>
      <small>Record in a quiet room. Read naturally: “Hello, this is my own voice. I use my assistant to help with everyday tasks.” Recording pauses voice input; activate listening again when finished.</small>
      {progress && <div className="setup-progress" role="status">{progress}</div>}
      <div className="voice-test"><button className="text-link" disabled={!connected || pending} onClick={() => void chooseModel()}>Choose local model configuration</button><button className="text-link" disabled={!connected || pending} onClick={() => change('voice_model_config', '')}>Use default model</button></div>
      <small>{values.voice_model_config ? 'Custom local model configuration selected.' : 'Default Pocket TTS model selected.'} Personal playback speed also changes pitch. Use Speaking below for speed and volume.</small>
      <label><input type="checkbox" checked={values.voice_startup} onChange={e => change('voice_startup', e.target.checked)}/> Speak a startup greeting using the selected engine</label>
      <div className="voice-test"><button className="button compact" disabled={!connected || pending} onClick={() => void (async () => { try { await save(values); await request('voice_test'); } catch (e) { onError(String(e)); } })()}>Save &amp; test selected voice</button><button className="text-link" disabled={!connected || pending} onClick={() => void manage('personal_voice_reload')}>Unload / reload on next speech</button><button className="text-link" disabled={!connected || pending} onClick={() => void manage('personal_voice_delete')}>Delete personal recording</button></div>
    </div>
  </section>;
}
