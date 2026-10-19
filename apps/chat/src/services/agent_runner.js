// Legacy re-export — source of truth is agent_stream.js
const { send, AgentBusyError } = require('./agent_stream');
const TIMEOUT = parseInt(process.env.AGENT_RUNNER_TIMEOUT_MS || '1800000', 10);
module.exports = {
    runAgent: (opts) => send({ ...opts, endpoint: '/run-agent', timeoutMs: TIMEOUT }),
    AgentRunnerBusyError: AgentBusyError,
};
