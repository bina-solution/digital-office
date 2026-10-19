// Legacy re-export — source of truth is agent_stream.js
const { send, AgentBusyError } = require('./agent_stream');
const TIMEOUT = parseInt(process.env.AUTO_TURN_TIMEOUT_MS || '300000', 10); // 5 min for n8n workflows
module.exports = {
    automationsTurn: (opts) => send({ ...opts, endpoint: '/automations-turn', timeoutMs: TIMEOUT }),
    AgentBusyError,
};
