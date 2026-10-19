#!/bin/sh
# Declarative model profile generator — Python-backed for safe JSON
exec python3 << 'EOF'
import json, os, hashlib

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

profiles = {}
active = "DeepSeek V4 Pro"

if DEEPSEEK_KEY:
    print("[openhands-init] DeepSeek API key detected → enabling DeepSeek profiles")
    profiles.update({
        "DeepSeek V4 Pro": {
            "model": "deepseek/deepseek-chat", "base_url": "https://api.deepseek.com",
            "api_key": DEEPSEEK_KEY, "num_retries": 5, "retry_multiplier": 8.0,
            "retry_min_wait": 8, "retry_max_wait": 64, "timeout": 300,
            "max_message_chars": 30000, "stream": False, "drop_params": True,
            "modify_params": True, "caching_prompt": True,
            "native_tool_calling": True, "reasoning_effort": "high",
            "enable_encrypted_reasoning": True, "prompt_cache_retention": "24h",
            "schema_version": 1
        },
        "DeepSeek V4 Flash": {
            "model": "deepseek/deepseek-chat", "base_url": "https://api.deepseek.com",
            "api_key": DEEPSEEK_KEY, "num_retries": 3, "retry_multiplier": 4.0,
            "retry_min_wait": 4, "retry_max_wait": 32, "timeout": 120,
            "max_message_chars": 15000, "stream": False, "drop_params": True,
            "modify_params": True, "caching_prompt": True,
            "native_tool_calling": True, "schema_version": 1
        },
        "DeepSeek Reasoner": {
            "model": "deepseek/deepseek-reasoner", "base_url": "https://api.deepseek.com",
            "api_key": DEEPSEEK_KEY, "num_retries": 5, "retry_multiplier": 8.0,
            "retry_min_wait": 8, "retry_max_wait": 64, "timeout": 600,
            "max_message_chars": 30000, "stream": False, "drop_params": True,
            "modify_params": True, "caching_prompt": True,
            "native_tool_calling": True, "schema_version": 1
        }
    })
    active = "DeepSeek V4 Pro"

if GEMINI_KEY:
    print("[openhands-init] Gemini API key detected → enabling Gemini profiles")
    profiles.update({
        "Gemini 2.5 Flash": {
            "model": "gemini/gemini-2.5-flash",
            "api_key": GEMINI_KEY, "num_retries": 5, "retry_multiplier": 8.0,
            "retry_min_wait": 8, "retry_max_wait": 64, "timeout": 120,
            "max_message_chars": 80000, "stream": False, "drop_params": True,
            "modify_params": True, "caching_prompt": False,
            "native_tool_calling": True, "schema_version": 1
        },
        "Gemini 2.5 Pro": {
            "model": "gemini/gemini-2.5-pro",
            "api_key": GEMINI_KEY, "num_retries": 5, "retry_multiplier": 8.0,
            "retry_min_wait": 8, "retry_max_wait": 64, "timeout": 300,
            "max_message_chars": 80000, "stream": False, "drop_params": True,
            "modify_params": True, "caching_prompt": False,
            "native_tool_calling": True, "schema_version": 1
        }
    })
    if not DEEPSEEK_KEY:
        active = "Gemini 2.5 Flash"

if OPENAI_KEY and OPENAI_KEY != DEEPSEEK_KEY:
    print("[openhands-init] OpenAI API key detected → enabling OpenAI profiles")
    profiles.update({
        "GPT-4o": {
            "model": "openai/gpt-4o",
            "api_key": OPENAI_KEY, "num_retries": 5, "retry_multiplier": 8.0,
            "retry_min_wait": 8, "retry_max_wait": 64, "timeout": 300,
            "max_message_chars": 50000, "stream": False, "drop_params": True,
            "modify_params": True, "caching_prompt": False,
            "native_tool_calling": True, "schema_version": 1
        },
        "GPT-4o Mini": {
            "model": "openai/gpt-4o-mini",
            "api_key": OPENAI_KEY, "num_retries": 4, "retry_multiplier": 6.0,
            "retry_min_wait": 6, "retry_max_wait": 48, "timeout": 120,
            "max_message_chars": 30000, "stream": False, "drop_params": True,
            "modify_params": True, "caching_prompt": True,
            "native_tool_calling": True, "schema_version": 1
        }
    })
    if not DEEPSEEK_KEY and not GEMINI_KEY:
        active = "GPT-4o"

if ANTHROPIC_KEY:
    print("[openhands-init] Anthropic API key detected → enabling Claude profiles")
    profiles.update({
        "Claude Sonnet 4": {
            "model": "anthropic/claude-sonnet-4-20250514",
            "api_key": ANTHROPIC_KEY, "num_retries": 5, "retry_multiplier": 8.0,
            "retry_min_wait": 8, "retry_max_wait": 64, "timeout": 300,
            "max_message_chars": 80000, "stream": False, "drop_params": True,
            "modify_params": True, "caching_prompt": True,
            "native_tool_calling": True, "schema_version": 1
        },
        "Claude Haiku 4": {
            "model": "anthropic/claude-haiku-4-20250514",
            "api_key": ANTHROPIC_KEY, "num_retries": 3, "retry_multiplier": 4.0,
            "retry_min_wait": 4, "retry_max_wait": 32, "timeout": 120,
            "max_message_chars": 30000, "stream": False, "drop_params": True,
            "modify_params": True, "caching_prompt": True,
            "native_tool_calling": True, "schema_version": 1
        }
    })

settings = {
    "language": "en",
    "active_llm_profile": active,
    "enable_sound_notifications": False,
    "enable_proactive_conversation_starters": False,
    "user_consents_to_analytics": False,
    "llm_profiles": {"profiles": profiles}
}

for path in ["/.openhands/settings.json", "/.openhands-state/settings.json"]:
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)

# Hash for change detection
h = hashlib.md5((DEEPSEEK_KEY + GEMINI_KEY + OPENAI_KEY + ANTHROPIC_KEY).encode()).hexdigest()
with open("/.openhands/.seed-hash", "w") as f:
    f.write(h)

print(f"[openhands-init] Settings seeded: {len(profiles)} model profiles, active={active}")
EOF
