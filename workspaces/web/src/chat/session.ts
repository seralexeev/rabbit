const BASE_URL = import.meta.env['VITE_CHAT_URL'] ?? 'https://jetson.rabbit';

export const CHAT_URL = `${BASE_URL}/api/chat`;
export const HEALTH_URL = `${BASE_URL}/api/health`;
export const VOICE_CALL_URL = `${BASE_URL}/api/voice/call`;
export const VOICE_TOOL_URL = `${BASE_URL}/api/voice/tool`;
