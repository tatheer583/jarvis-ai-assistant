export interface SecurityStatus { mode: string; owner_authenticated: boolean; strong_authentication_available: boolean; description: string }
export interface TaskStatus { id: string; source: string; state: string; steps: { id: string; tool: string; state: string; verification: string }[] }
export interface ProviderStatus { name: string; online: boolean; reason?: string }
export interface Settings {
  silence_ms: number;
  audit_retention_days: number;
  user_name: string; language: string; wake_word: string; require_wake_word: boolean;
  microphone_device: number | null; voice_id: string; voice_rate: number; voice_volume: number;
  speech_enabled: boolean; voice_provider: string; vad_aggressiveness: number;
  listen_on_startup: boolean; start_with_windows: boolean; close_to_tray: boolean;
  search_roots: string[]; aliases: Record<string, string>; whisper_path: string; llm_path: string;
}
export interface Message { role: string; content: string }
export interface Note { id: number; content: string; created: number }
export interface Reminder { id: number; text: string; due: number }
export interface FileHit { name: string; path: string; is_dir: boolean; score: number }
export interface WindowInfo { hwnd: number; name: string; process: string; pid: number }
export interface ActionResult { success: boolean; action: string; message: string; error?: string; data?: { choices?: FileHit[]; confirmation?: boolean; path?: string; grid?: unknown } }
export interface Snapshot {
  security: SecurityStatus; current_task: TaskStatus | null; provider: ProviderStatus;
  settings: Settings; status: string; listening: boolean; busy: boolean; speaking: boolean;
  speech_ready: boolean; chat_ready: boolean; index_count: number; indexing: boolean;
  history: Message[]; notes: Note[]; reminders: Reminder[]; data_directory: string; memory_percent: number;
}
export const defaults: Snapshot = {
  security: { mode: 'legacy_local', owner_authenticated: false, strong_authentication_available: false, description: 'Owner authentication is not configured.' },
  current_task: null, provider: { name: 'local', online: false },
  settings: { silence_ms: 850, audit_retention_days: 90, user_name: 'You', language: 'auto', wake_word: 'jarvis', require_wake_word: true,
    microphone_device: null, voice_id: '', voice_rate: 0, voice_volume: 90, speech_enabled: true,
    voice_provider: 'windows', vad_aggressiveness: 2, listen_on_startup: true, start_with_windows: false,
    close_to_tray: true, search_roots: [], aliases: {}, whisper_path: '', llm_path: '' },
  status: 'Connecting to your local assistant…', listening: false, busy: false, speaking: false,
  speech_ready: false, chat_ready: false, index_count: 0, indexing: false,
  history: [], notes: [], reminders: [], data_directory: '', memory_percent: 0,
};
