export interface SecurityStatus { mode: string; owner_authenticated: boolean; strong_authentication_available: boolean; description: string }
export interface TaskStatus { id: string; source: string; state: string; steps: { id: string; tool: string; state: string; verification: string }[] }
export interface ProviderStatus { name: string; online: boolean; reason?: string }
export interface Settings {
  voice_reference: string;
  voice_consent: boolean; voice_model_config: string; voice_python: string; voice_startup: boolean;
  assistant_name: string; owner_email: string;
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
  security: SecurityStatus; owner: OwnerStatus; current_task: TaskStatus | null; provider: ProviderStatus;
  settings: Settings; status: string; listening: boolean; busy: boolean; speaking: boolean;
  speech_ready: boolean; chat_ready: boolean; index_count: number; indexing: boolean;
  history: Message[]; notes: Note[]; reminders: Reminder[]; data_directory: string; memory_percent: number;
}
export interface OwnerStatus { face_enrolled: boolean; face_message: string; camera_available: boolean; voice_enrolled: boolean; voice_samples: number; microphone_available: boolean; microphone_message: string; pin_configured: boolean; overall: boolean; overall_message: string; owner_name: string; assistant_name: string; owner_email: string }
export const defaults: Snapshot = {
  owner: { face_enrolled: false, face_message: 'Face not enrolled', camera_available: false, voice_enrolled: false, voice_samples: 0, microphone_available: false, microphone_message: 'Microphone unavailable', pin_configured: false, overall: false, overall_message: 'Owner authentication not configured', owner_name: 'You', assistant_name: 'Jarvis', owner_email: '' },
  security: { mode: 'legacy_local', owner_authenticated: false, strong_authentication_available: false, description: 'Owner authentication is not configured.' },
  current_task: null, provider: { name: 'local', online: false },
  settings: { voice_consent: false, voice_model_config: '', voice_python: '', voice_startup: true, assistant_name: 'Jarvis', owner_email: '', silence_ms: 850, audit_retention_days: 90, user_name: 'You', language: 'auto', wake_word: 'jarvis', require_wake_word: true,
    microphone_device: null, voice_id: '', voice_rate: 0, voice_volume: 90, speech_enabled: true,
    voice_reference: '', voice_provider: 'windows', vad_aggressiveness: 2, listen_on_startup: true, start_with_windows: false,
    close_to_tray: true, search_roots: [], aliases: {}, whisper_path: '', llm_path: '' },
  status: 'Connecting to your local assistant…', listening: false, busy: false, speaking: false,
  speech_ready: false, chat_ready: false, index_count: 0, indexing: false,
  history: [], notes: [], reminders: [], data_directory: '', memory_percent: 0,
};
