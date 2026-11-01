const Sentry = require('@sentry/node');
const { CONFIG } = require('../config');

const DSN = process.env.SENTRY_DSN || '';

const initSentry = () => {
  if (!DSN) {
    console.warn('[sentry] SENTRY_DSN not set — error tracking disabled');
    return;
  }
  Sentry.init({
    dsn: DSN,
    environment: CONFIG.IS_PRODUCTION ? 'production' : 'development',
    release: `chat@${require('../../package.json').version || 'unknown'}`,
    tracesSampleRate: 0.1,
    beforeSend(event) {
      // Strip auth credentials from breadcrumbs / request data
      if (event.breadcrumbs) {
        event.breadcrumbs = event.breadcrumbs.map(b => {
          if (b.data?.url) b.data.url = b.data.url.replace(/:\/\/[^@]+@/, '://***@');
          return b;
        });
      }
      return event;
    }
  });
  console.log('[sentry] Initialized — reporting to GlitchTip');
};

module.exports = { initSentry, Sentry };
