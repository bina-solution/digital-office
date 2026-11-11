/**
 * Authentication middleware functions
 */
const { CONFIG } = require('../../config');

/**
 * Middleware to check if user is authenticated
 */
const basicAuth = require('basic-auth');

// When the app is fronted by an SSO edge (Authentik forward-auth), it must NOT run its own login —
// otherwise it can't be embedded in the console and users hit a second login. TRUST_EDGE_AUTH=true
// makes this app trust the edge: a request is believed when it CAME through the edge (or carries the
// office's service token), not merely because it arrived — see edge_caller.js.
const EDGE_AUTH = process.env.TRUST_EDGE_AUTH === 'true';

const edgeCaller = require('./edge_caller');
const callerCheck = edgeCaller.middleware({
  mode: process.env.CHAT_CALLER_MODE,
  deployment: process.env.DEPLOYMENT_NAME,
  token: process.env.CHAT_API_TOKEN,
  // the office's READ token: GET /api/accounts and /api/readyz only (edge_caller.js READ_ROUTES) — for the office agent
  readToken: process.env.CHAT_READ_TOKEN,
  // the office's chat credential as Basic auth on /api/, as below without edge trust — never the shipped fallback
  basic: edgeCaller.basicChecker({ username: CONFIG.AUTH_USERNAME, password: CONFIG.AUTH_PASSWORD, parse: basicAuth }),
});

const isAuthenticated = (req, res, next) => {
  if (EDGE_AUTH) {
    return callerCheck(req, res, next);
  }
  if (req.session.authenticated) {
    return next();
  }

  // Check for Basic Auth if accessing API
  if (req.path.startsWith('/api/')) {
    const user = basicAuth(req);
    if (
      user &&
      user.name === CONFIG.AUTH_USERNAME &&
      user.pass === CONFIG.AUTH_PASSWORD
    ) {
      return next();
    }
    return res.status(401).json({ error: 'Unauthorized' });
  }

  res.redirect('/login');
};


/**
 * Middleware to redirect already authenticated users away from auth pages
 */
const redirectIfAuthenticated = (req, res, next) => {
  if (EDGE_AUTH || req.session.authenticated) {
    return res.redirect('/');   // no local login page when the edge owns auth
  }
  next();
};

/**
 * Process login attempt
 */
const login = (req, res) => {
  const { username, password } = req.body;
  
  if (username === CONFIG.AUTH_USERNAME && password === CONFIG.AUTH_PASSWORD) {
    req.session.authenticated = true;
    req.session.username = username;
    return res.redirect('/');
  }
  
  res.render('login', { error: 'Invalid username or password' });
};

/**
 * Logout user
 */
const logout = (req, res) => {
  req.session.destroy(() => {
    res.redirect('/login');
  });
};

module.exports = {
  isAuthenticated,
  redirectIfAuthenticated,
  login,
  logout
};