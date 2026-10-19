/**
 * Consolidated API routes
 */
const express = require('express');
const path = require('path');
const session = require('express-session');
const rateLimit = require('express-rate-limit');
const { CONFIG } = require('../config');
const { 
  isAuthenticated, 
  redirectIfAuthenticated,
  login,
  logout
} = require('./middleware/auth');
const { 
  generalUpload, 
  documentUpload,
  imageUpload
} = require('./middleware/upload');
const { apiLimiter, loginLimiter } = require('./middleware/ratelimit');
const controller = require('./controller');

// Create express app
const app = express();

// Configure session middleware
// Trust proxy for secure cookies in production
app.set('trust proxy', CONFIG.IS_PRODUCTION ? 1 : 0);
app.use(session({
  secret: CONFIG.SESSION_SECRET,
  resave: false,
  saveUninitialized: false,
  cookie: {
    maxAge: CONFIG.SESSION_MAX_AGE,
    httpOnly: true,
    secure: false // Set to true in production
  }
}));

// Middleware for parsing request bodies
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// There is no static directory, and there should not be one. Both views (chat, login) inline all of
// their CSS and JS, so the app ships exactly two documents and no asset requests — which is why
// `express.static(src/public)` was dead: the directory has never existed and nothing sets
// STATIC_FILES_PATH to another one. It was not harmless. It ran BEFORE `isAuthenticated`, so the day
// anything created that directory its contents would have served to anonymous callers; and until
// then it cost a filesystem stat on every request to the service for nothing.
//
// If assets ever need serving, mount them under an explicit path AFTER the auth middleware
// (`app.use('/assets', isAuthenticated, express.static(dir))`) rather than restoring a catch-all.

// Set up view engine
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'ui'));

// Apply rate limiting to all API routes
app.use('/api/', apiLimiter);

// ===== Authentication Routes =====
app.get('/login', redirectIfAuthenticated, controller.renderLogin);
app.post('/login', loginLimiter, redirectIfAuthenticated, login);
app.get('/logout', logout);

// ===== View Routes =====
// The chat client is the app's face; the console embeds this app at '/', and the client fetches
// 'api/…' RELATIVE, which only resolves to /api/… when it is served from the root.
//
// There is ONE view, and that is the point. `/admin` used to serve a second UI (ui/index.ejs) over
// the same service — a separate surface for accounts, subscribers and ops, which the simulation
// deliberately does not have: there, accounts, bots, conversations AND subscribers are one app.
// Every one of its four sections now has a home in the client above:
//   #connect   the connection switcher + the console's חיבורים ומפתחות screen (which proxies the QR
//              with the chat-auth basic auth — that is where a human pairs a credential)
//   #settings  the per-connection bot settings panel
//   #actions   broadcast → POST /api/broadcast, through the adapter, so it works on every backend;
//              send-a-document-to-a-phone-number stays on the WhatsApp route below (it addresses a
//              NUMBER, and the op contract addresses conversations), surfaced in the tools modal
//   #users     the subscriber list, its export, restore and delete — same routes, in the tools modal
// The API routes it called are all still here: n8n calls most of them (blueprint/n8n), and deleting
// a working capability to make a rename look tidy is worse than leaving it.
app.get('/', isAuthenticated, controller.renderChat);

// ===== Subscribers API Routes =====
app.get('/api/subscribers', isAuthenticated, controller.getSubscribers);
app.delete('/api/subscribers', isAuthenticated, controller.deleteSubscribers);
app.get('/api/subscribers/backup', isAuthenticated, controller.createBackup);
app.post('/api/subscribers/restore', isAuthenticated, generalUpload.single('backupFile'), controller.restoreBackup);

// ===== Bot API Routes =====
app.get('/api/bot/state', isAuthenticated, controller.getBotState);
app.get('/api/bot/qr', isAuthenticated, controller.getConnectionQr);
app.post('/api/bot/disconnect', isAuthenticated, controller.disconnectBot);
app.post('/api/bot/broadcast', isAuthenticated, controller.sendBroadcast);
app.post('/api/bot/send-document', isAuthenticated, documentUpload.single('document'), controller.sendDocument);
app.post('/api/bot/send', isAuthenticated, controller.sendToJid);
app.post('/api/bot/send-image', isAuthenticated, imageUpload.single('image'), controller.sendImageToJid);
app.post('/api/bot/create-group', isAuthenticated, controller.createGroup);
app.post('/api/bot/group-participants', isAuthenticated, controller.groupParticipants);

// ===== WhatsApp Archive API Routes =====
app.get('/api/wa-archive/stats', isAuthenticated, controller.getWhatsAppArchiveStats);
app.get('/api/wa-archive/chats', isAuthenticated, controller.getWhatsAppArchiveChats);
app.get('/api/wa-archive/messages/search', isAuthenticated, controller.searchWhatsAppArchiveMessages);

// ===== Chat client =====
// The ABSTRACT chat API: one surface over local chat, WhatsApp and Telegram, resolved per request
// from the selected connection. See chatapi/adapters/index.js for why it is shaped like mail's.
//
// Registered BEFORE the legacy WhatsApp-only adapter, so where both define a route the abstract one
// wins. The legacy adapter stays registered behind it rather than being deleted: it projects the
// WhatsApp archive directly and still answers for anything the new layer does not yet cover, so a
// gap degrades to the old behaviour instead of a 404. It goes when the Baileys backend is complete.
//
// A failure to load must NOT take the app down — the WhatsApp bot is live and does real work, and it
// does not need the chat API to keep running. So this is guarded, and says so loudly if it fails.
try {
  require('../../chatapi/server').register(app, isAuthenticated);
  // THE BOOTSTRAP RECONCILER. Declared profiles in app.json become real, credentialed identities
  // with a vault instance each — created here, IN-PROCESS with direct database access, which is the
  // one path exempt from profile authentication and the only thing that can resolve the
  // chicken-and-egg of needing an admin key to create the first admin. Idempotent and ledger-backed,
  // so a redeploy never re-mints a key and never deletes a profile an operator made by hand.
  // Fire-and-forget: a database or vault that is briefly unreachable is a retry, not a boot failure.
  // The local engine's receive path. Baileys and Telegram hand inbound messages to the bot runtime
  // from their own sockets; the local engine's socket is opened here, and without it a bot attached
  // to a local identity reports itself attached in the UI and never answers anything.
  //
  // AFTER the reconciler, not beside it. These two used to be fired independently, and the race was
  // silent: the inbox enumerates the profiles that have a bot, so on a boot where the reconciler had
  // not finished creating them yet it found none, logged "no profile has a bot attached", and
  // exited — leaving a deployment whose bots simply never answered until someone restarted it.
  // Measured on this deployment the first time a third profile was declared.
  //
  // Still fire-and-forget as a pair: a database or vault that is briefly unreachable is a retry,
  // not a boot failure, and each half logs its own.
  require('../../chatapi/engine/bootstrap').start()
    .catch((e) => console.error('engine profile reconcile failed (chat still starts):', e))
    .then(() => require('../../chatapi/local_inbox').start())
    .catch((e) => console.error('local-inbox failed to start (bots will not answer on local chat):', e));
} catch (e) {
  console.error('chatapi failed to register — falling back to the legacy adapter only:', e);
}

// The WhatsApp-only projection over the archive. Owns no data of its own.
const { appProperties } = require('../globals');
require('./chat_adapter').register(app, isAuthenticated, appProperties, controller);


// ===== Error handling =====
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).send('Something broke!');
});

// ===== 404 handler =====
app.use((req, res) => {
  res.status(404).render('404', { username: req.session.username });
});

const runAPI = () => {
  app.listen(CONFIG.PORT, () => {
    console.log(`Admin panel running at http://localhost:${CONFIG.PORT}`);
  });
};

module.exports = { app, runAPI };