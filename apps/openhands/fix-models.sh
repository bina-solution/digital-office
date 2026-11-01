#!/bin/bash
# Fix agent-server models: remove litellm_proxy/ prefix, add api_key, fix base_url
# Runs continuously, checking for new agent servers and fixing their conversation state.

INTERVAL=${1:-3}
echo "[fix-models] Starting, interval=${INTERVAL}s"

fix_agent() {
    local cid="$1"
    # Fix environment - add DEEPSEEK_API_KEY if missing
    if docker exec "$cid" env 2>/dev/null | grep -q "DEEPSEEK_API_KEY"; then
        : # already has it
    else
        # Can't set env on running container, skip
        :
    fi

    # Fix all base_state.json files
    docker exec "$cid" python3 -c "
import json, os, glob

conv_dir = '/workspace/conversations'
if not os.path.isdir(conv_dir):
    exit(0)

fixed = 0
for d in os.listdir(conv_dir):
    bsp = os.path.join(conv_dir, d, 'base_state.json')
    if not os.path.exists(bsp):
        continue
    try:
        with open(bsp) as f:
            s = json.load(f)
    except:
        continue
    
    changed = False
    # Fix agent.llm — ensure it has api_key and correct base_url
    llm = s.get('agent', {}).get('llm', {})
    # Remove litellm_proxy/ prefix if present
    if llm.get('model', '').startswith('litellm_proxy/'):
        llm['model'] = llm['model'].replace('litellm_proxy/', '')
        changed = True
    # Add api_key if missing
    if not llm.get('api_key'):
        llm['api_key'] = os.environ.get('LLM_API_KEY', '')
        changed = True
    # Fix base_url if pointing to llm-proxy
    if 'llm-proxy' in (llm.get('base_url') or ''):
        llm['base_url'] = os.environ.get('LLM_BASE_URL', 'https://api.deepseek.com')
        changed = True
    
    # Fix stats — remove litellm_proxy prefix
    agent_stats = s.get('stats', {}).get('usage_to_metrics', {}).get('agent', {})
    if (agent_stats.get('model_name') || '').startsWith('litellm_proxy/'):
        agent_stats['model_name'] = agent_stats['model_name'].replace('litellm_proxy/', '')
        changed = True
    
    if changed:
        with open(bsp, 'w') as f:
            json.dump(s, f)
        fixed += 1

if fixed > 0:
    print(f'[fix-models] Fixed {fixed} conversation(s) in {cid}')
" 2>/dev/null
}

while true; do
    # Find all oh-agent-server containers
    containers=$(docker ps --filter "name=oh-agent-server" --format "{{.Names}}" 2>/dev/null)
    for cid in $containers; do
        fix_agent "$cid"
    done
    
    # Also fix conversation_metadata in the DB
    docker exec "openhands-${DEPLOYMENT_NAME:-bina-deployment}" python3 -c "
import sqlite3
db = sqlite3.connect('/.openhands-state/openhands.db')
    cur = db.execute(\"UPDATE conversation_metadata SET llm_model = REPLACE(llm_model, 'litellm_proxy/', '') WHERE llm_model LIKE '%litellm_proxy%'\")
if cur.rowcount > 0:
    db.commit()
    print(f'[fix-models] DB: fixed {cur.rowcount} conversation(s)')
" 2>/dev/null

    sleep "$INTERVAL"
done
