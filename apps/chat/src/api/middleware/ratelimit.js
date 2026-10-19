const rateLimit = require('express-rate-limit');
const { CONFIG } = require('../../config');

// Apply rate limiting to all API routes
const apiLimiter = rateLimit({
  windowMs: CONFIG.RATE_LIMIT.API.WINDOW_MS,
  max: CONFIG.RATE_LIMIT.API.MAX,
  message: 'Too many requests from this IP, please try again later.'
});

// Apply rate limiting for login route
const loginLimiter = rateLimit({
  windowMs: CONFIG.RATE_LIMIT.LOGIN.WINDOW_MS,
  max: CONFIG.RATE_LIMIT.LOGIN.MAX,
  message: 'Too many login attempts, please try again later.'
});

module.exports = { apiLimiter, loginLimiter };