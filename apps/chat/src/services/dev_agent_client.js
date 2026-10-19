// Legacy re-export — source of truth is agent_stream.js
const { send, AgentBusyError } = require('./agent_stream');
const TIMEOUT = parseInt(process.env.DEV_TURN_TIMEOUT_MS || '1800000', 10);
module.exports = {
    devTurn: (opts) => send({ ...opts, endpoint: '/dev-turn', timeoutMs: TIMEOUT }),
    DevAgentBusyError: AgentBusyError,
};
