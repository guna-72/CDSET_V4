// Utility for managing API keys in user settings with priority over backend .env
import { saveBackendSettingsKeys } from '../api';

export const API_KEY_STORAGE_KEY = 'chaosTutorApiKeys';
export const SETTINGS_STORAGE_KEY = 'chaosTutorSettings';

export const SUPPORTED_PROVIDERS = [
  { id: 'gemini', name: 'Google Gemini', placeholder: 'AIzaSy... or AQ.Ab8...', desc: 'Primary LLM for Chaos Tutor explanations & live chat', docs: 'https://aistudio.google.com/app/apikey' },
  { id: 'groq', name: 'Groq', placeholder: 'gsk_...', desc: 'Ultra-fast inference (Llama 3.3, Mixtral)', docs: 'https://console.groq.com/keys' },
  { id: 'openai', name: 'OpenAI', placeholder: 'sk-...', desc: 'GPT-4o, GPT-4o-mini models', docs: 'https://platform.openai.com/api-keys' },
  { id: 'anthropic', name: 'Anthropic', placeholder: 'sk-ant-...', desc: 'Claude 3.5 Sonnet, Claude 3 Opus', docs: 'https://console.anthropic.com/settings/keys' },
  { id: 'openrouter', name: 'OpenRouter', placeholder: 'sk-or-...', desc: 'Multi-model gateway & free routers', docs: 'https://openrouter.ai/keys' },
];

/**
 * Returns all API keys configured by the user in Settings.
 */
export function getStoredApiKeys() {
  try {
    const raw = localStorage.getItem(API_KEY_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
    const settingsRaw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (settingsRaw) {
      const parsed = JSON.parse(settingsRaw);
      if (parsed.apiKeys && typeof parsed.apiKeys === 'object') {
        return parsed.apiKeys;
      }
    }
  } catch (err) {
    console.warn('Error reading stored API keys:', err);
  }
  return {};
}

/**
 * Priority check:
 * First check in settings whether there is a key.
 * If there is a key in settings, returns it.
 * Else returns null, indicating the caller should fallback to the .env file.
 */
export function getEffectiveApiKey(provider = 'gemini') {
  const keys = getStoredApiKeys();
  const normalized = String(provider).toLowerCase().trim();
  const key = keys[normalized] || keys[provider];
  if (key && typeof key === 'string' && key.trim().length > 0) {
    return key.trim();
  }
  return null;
}

/**
 * Save user API keys to localStorage and sync with backend settings.
 */
export async function saveStoredApiKeys(keys) {
  const cleaned = {};
  for (const [k, v] of Object.entries(keys || {})) {
    if (typeof v === 'string' && v.trim().length > 0) {
      cleaned[k.toLowerCase().trim()] = v.trim();
    }
  }

  try {
    localStorage.setItem(API_KEY_STORAGE_KEY, JSON.stringify(cleaned));
    const settingsRaw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    const settings = settingsRaw ? JSON.parse(settingsRaw) : {};
    settings.apiKeys = cleaned;
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  } catch (err) {
    console.warn('LocalStorage error while saving API keys:', err);
  }

  // Sync to backend so main Python backend also prioritizes settings over .env
  try {
    await saveBackendSettingsKeys(cleaned);
  } catch (err) {
    console.warn('Backend sync for settings keys note:', err?.message);
  }

  return cleaned;
}
