#!/usr/bin/env python3
"""Declarative LiteLLM config generator — one provider block per API key found in env.
Just add DEEPSEEK_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY to .env → all models appear.
Wildcard routing: deepseek/* → DeepSeek, gemini/* → Gemini, openai/* → OpenAI, etc.
"""

import os, json, yaml

# ── Collect all provider keys from environment ──
providers = {}

if os.environ.get("DEEPSEEK_API_KEY"):
    providers["deepseek"] = {
        "api_key": os.environ["DEEPSEEK_API_KEY"],
        "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model_prefix": "deepseek"
    }

if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
    providers["gemini"] = {
        "api_key": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
        "model_prefix": "gemini"
    }

if os.environ.get("OPENAI_API_KEY"):
    key = os.environ["OPENAI_API_KEY"]
    # Don't reuse DeepSeek key for OpenAI
    if key != os.environ.get("DEEPSEEK_API_KEY", ""):
        providers["openai"] = {
            "api_key": key,
            "model_prefix": "openai"
        }

if os.environ.get("ANTHROPIC_API_KEY"):
    providers["anthropic"] = {
        "api_key": os.environ["ANTHROPIC_API_KEY"],
        "model_prefix": "anthropic"
    }

# Generic: any *_API_KEY env var that matches a known provider pattern
for env_key, env_val in os.environ.items():
    if not env_key.endswith("_API_KEY") or not env_val:
        continue
    prefix = env_key.replace("_API_KEY", "").lower()
    if prefix in ("deepseek", "gemini", "google", "openai", "anthropic"):
        continue  # already handled above
    # Known LiteLLM providers: groq, mistral, openrouter, together, fireworks, etc.
    known = {"groq", "mistral", "openrouter", "together", "fireworks", "cohere", "replicate"}
    if prefix in known:
        providers[prefix] = {"api_key": env_val, "model_prefix": prefix}

if not providers:
    print("[llm-gateway] WARNING: No API keys found — gateway will start but have no models")
    providers["deepseek"] = {"api_key": "placeholder", "model_prefix": "deepseek"}

# ── Build LiteLLM config ──
master_key = os.environ.get("LITELLM_MASTER_KEY", "sk-REDACTED-key-4")

config = {
    "general_settings": {
        "master_key": master_key,
        "disable_expensive_db_pools": True,
        "database_connection_pool_limit": 3,
        "allow_requests_from": ["0.0.0.0/0"]
    },
    "model_list": [],
    "router_settings": {
        "num_retries": 3,
        "retry_after": 5,
        "timeout": 300,
        "allowed_fails": 3,
        "fallbacks": []
    },
    "litellm_settings": {
        "drop_params": True,
        "set_verbose": False,
        "cache": True,
        "cache_params": {"type": "local"}
    }
}

# ── One wildcard block per provider ──
for provider_name, pdata in providers.items():
    model_name = f"{pdata['model_prefix']}/*"
    entry = {
        "model_name": model_name,
        "litellm_params": {
            "model": model_name,
            "api_key": pdata["api_key"],
            "rpm": 100,
            "timeout": 300
        }
    }
    if "base_url" in pdata:
        entry["litellm_params"]["api_base"] = pdata["base_url"]
    config["model_list"].append(entry)

# ── Default text + vision models ──
# DeepSeek V4 Pro → deepseek/deepseek-chat
# Gemini 2.5 Flash → gemini/gemini-2.5-flash
config["router_settings"]["fallbacks"] = []
if "deepseek" in providers:
    config["router_settings"]["fallbacks"].append({"deepseek/deepseek-chat": ["gemini/gemini-2.5-flash"] if "gemini" in providers else []})
if "gemini" in providers:
    config["router_settings"]["fallbacks"].append({"gemini/gemini-2.5-flash": ["deepseek/deepseek-chat"] if "deepseek" in providers else []})

# ── Write config ──
config_path = "/app/litellm-config.yaml"
with open(config_path, "w") as f:
    yaml.dump(config, f, default_flow_style=False, allow_unicode=True, width=200)

# ── Write a /v1/models stub for OpenHands init to consume ──
# LiteLLM provides this natively — no need for a stub
# But we output a summary for the init container
model_count = len(providers)
print(f"[llm-gateway] Config written: {model_count} providers → {config_path}")
for name, pdata in providers.items():
    print(f"  - {name}: {pdata['model_prefix']}/*")
print(f"[llm-gateway] Master key: {master_key[:8]}...")
