const {runAPI} = require('./api/api');
const {runBaileyesApp} = require('./whatsapp/baileyes_app');
const { CONFIG } = require('./config');
const { appProperties } = require('./globals');
const { loadSettings } = require('./services/settings_api');
const { fetchCompanies } = require('./services/companies_api');
const { initSentry, Sentry } = require('./services/sentry');
const { runStartupChecks } = require('./services/startup_checks');

const APP_VERSION = CONFIG.APP_VERSION || '0.7';

// Graceful shutdown
const shutdown = async (signal) => {
    console.log(`[shutdown] Received ${signal}, closing gracefully...`);
    try {
        if (appProperties.sock) {
            await appProperties.sock.end();
            console.log('[shutdown] WhatsApp socket closed');
        }
    } catch (e) {
        console.error('[shutdown] Error closing socket:', e.message);
    }
    await Sentry.flush(5000).catch(() => {});
    process.exit(0);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('unhandledRejection', (reason, promise) => {
    console.error('[unhandledRejection]', reason);
    Sentry.captureException(reason);
});
process.on('uncaughtException', (err) => {
    console.error('[uncaughtException]', err);
    Sentry.captureException(err);
    process.exit(1);
});
// Runs the bailyes app (bot) and the admin panel
const runApp = async () => {
    // Initialize error tracking first
    initSentry();

    // Log startup message
    let pwd = process.cwd();
    console.log('Starting the app version:', APP_VERSION, 'in path:', pwd, "Is Production:", CONFIG.IS_PRODUCTION);

    // Run external integration health checks
    await runStartupChecks();

    // Load settings and companies from external sources at startup
    await loadSettings();
    await fetchCompanies(true).catch(e => console.error('[startup] Failed to load companies:', e.message));

    // Run the api and the baileyes app
    runAPI();
    runBaileyesApp();
};


runApp();