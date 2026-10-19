// Legacy re-export — source of truth is agent_stream.js
const { send, AgentBusyError } = require('./agent_stream');
const TIMEOUT = parseInt(process.env.AGENT_CHAT_HTTP_TIMEOUT_MS || '360000', 10);
module.exports = {
    chatTurn: (opts) => send({ ...opts, endpoint: '/chat-turn', timeoutMs: TIMEOUT }),
    AgentRunnerBusyError: AgentBusyError,
};
