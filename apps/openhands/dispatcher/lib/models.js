// ── Model profiles: dynamically loaded from OpenHands settings.json ──
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const OH_STATE_PATH = process.env.OPENHANDS_STATE_PATH || '/.openhands-state';
const OH_PROFILES_PATH = join(OH_STATE_PATH, 'settings.json');

var MODEL_MAP = {};
var PROFILE_TO_LITELLM = {};
var AVAILABLE_MODELS = [];
var DEFAULT_PROFILE = 'DeepSeek V4 Pro';

function loadOpenHandsProfiles() {
  try {
    var raw = readFileSync(OH_PROFILES_PATH, 'utf-8');
    var settings = JSON.parse(raw);
    var profiles = (settings.llm_profiles || {}).profiles || {};
    MODEL_MAP = {};
    PROFILE_TO_LITELLM = {};
    AVAILABLE_MODELS = [];
    DEFAULT_PROFILE = settings.active_llm_profile || 'DeepSeek V4 Pro';

    for (var name in profiles) {
      var p = profiles[name];
      var model = p.model || '';
      var provider = model.split('/')[0] || 'unknown';
      var shortName = model.replace('/', '-').toLowerCase();

      MODEL_MAP[name.toLowerCase()] = name;
      MODEL_MAP[shortName] = name;
      MODEL_MAP[model.toLowerCase()] = name;

      if (provider === 'deepseek') {
        if (model.includes('chat')) { MODEL_MAP['deepseek'] = name; MODEL_MAP['ds'] = name; }
        if (model.includes('reasoner')) { MODEL_MAP['reasoner'] = name; MODEL_MAP['ds-reasoner'] = name; }
      }
      if (provider === 'gemini') {
        MODEL_MAP['gemini'] = name;
        if (model.includes('flash')) { MODEL_MAP['gemini-flash'] = name; MODEL_MAP['gf'] = name; }
        if (model.includes('pro')) { MODEL_MAP['gemini-pro'] = name; MODEL_MAP['gp'] = name; }
      }

      PROFILE_TO_LITELLM[name] = model;
      AVAILABLE_MODELS.push({ name, model, provider, baseUrl: p.base_url || '' });
    }

    console.log('[profiles] loaded ' + AVAILABLE_MODELS.length + ' models: ' + AVAILABLE_MODELS.map(function(m){return m.name;}).join(', '));
  } catch(e) {
    console.warn('[profiles] failed to load: ' + e.message + ' — using fallbacks');
    MODEL_MAP = {
      'deepseek-v4-pro': 'DeepSeek V4 Pro', 'deepseek': 'DeepSeek V4 Pro', 'ds': 'DeepSeek V4 Pro',
      'deepseek-v4-flash': 'DeepSeek V4 Flash', 'deepseek-chat': 'DeepSeek Chat',
      'deepseek-reasoner': 'DeepSeek Reasoner', 'reasoner': 'DeepSeek Reasoner',
      'haiku': 'DeepSeek V4 Flash', 'sonnet': 'DeepSeek V4 Pro', 'opus': 'DeepSeek V4 Pro'
    };
    PROFILE_TO_LITELLM = {
      'DeepSeek V4 Pro': 'deepseek/deepseek-chat', 'DeepSeek V4 Flash': 'deepseek/deepseek-chat',
      'DeepSeek Chat': 'deepseek/deepseek-chat', 'DeepSeek Reasoner': 'deepseek/deepseek-reasoner'
    };
    AVAILABLE_MODELS = [
      {name:'DeepSeek V4 Pro', model:'deepseek/deepseek-chat', provider:'deepseek'},
      {name:'DeepSeek V4 Flash', model:'deepseek/deepseek-chat', provider:'deepseek'},
      {name:'DeepSeek Reasoner', model:'deepseek/deepseek-reasoner', provider:'deepseek'}
    ];
  }
}

function resolveModel(inputModel) {
  if (!inputModel) return DEFAULT_PROFILE;
  var key = String(inputModel).toLowerCase().trim();
  if (MODEL_MAP[key]) return MODEL_MAP[key];
  for (var name in PROFILE_TO_LITELLM) {
    if (PROFILE_TO_LITELLM[name].toLowerCase() === key) return name;
  }
  if (PROFILE_TO_LITELLM[inputModel]) return inputModel;
  return DEFAULT_PROFILE;
}

function resolveLiteLLMModel(profileName) {
  return PROFILE_TO_LITELLM[profileName] || profileName;
}

// Load on import
loadOpenHandsProfiles();
// Reload every 5 minutes
setInterval(loadOpenHandsProfiles, 300000).unref?.();

export { loadOpenHandsProfiles, resolveModel, resolveLiteLLMModel, MODEL_MAP, PROFILE_TO_LITELLM, AVAILABLE_MODELS, DEFAULT_PROFILE };
