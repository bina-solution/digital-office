const supertest = require('supertest');
const { CONFIG } = require('../../src/config');

const baseURL = 'http://localhost:3000';
const request = supertest(baseURL);

let sessionCookie;

beforeAll(async () => {
  // Perform login to get session cookie
  const response = await request.post('/login')
    .type('form')
    .send({
      username: CONFIG.AUTH_USERNAME,
      password: CONFIG.AUTH_PASSWORD,
    });

  expect(response.status).toBe(302); // Expect a redirect after successful login
  sessionCookie = response.headers['set-cookie'][0]; // Capture the session cookie
});

// Use the session cookie in all authenticated requests
const authenticatedRequest = (method, url) => {
  return request[method](url).set('Cookie', sessionCookie);
};

// Helper function for Basic Auth API requests
const basicAuthRequest = (method, url) => {
  return request[method](url)
    .auth(CONFIG.AUTH_USERNAME, CONFIG.AUTH_PASSWORD);
};

describe('API Endpoints', () => {
  it('should return 401 for unauthorized access to /api/subscribers', async () => {
    const response = await request.get('/api/subscribers');
    expect(response.status).toBe(401);
    expect(response.body).toHaveProperty('error', 'Unauthorized');
  });

  it('should render the login page', async () => {
    const response = await request.get('/login');
    expect(response.status).toBe(200);
    // expect(response.text).toContain('WhatsApp Hacohanim');
  });
});

describe('Subscribers API', () => {
  it('should fetch subscribers with valid authentication', async () => {
    const response = await authenticatedRequest('get', '/api/subscribers');
    expect(response.status).toBe(200);
    expect(response.body).toBeInstanceOf(Array);
  });

  it('should return 401 for fetching subscribers without authentication', async () => {
    const response = await request.get('/api/subscribers');
    expect(response.status).toBe(401);
    expect(response.body).toHaveProperty('error', 'Unauthorized');
  });

  it('should delete subscribers with valid authentication', async () => {
    const response = await authenticatedRequest('delete', '/api/subscribers');
    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('message', 'All subscribers deleted');
  });
});

describe('Bot API', () => {
  it('should fetch bot state with valid authentication', async () => {
    const response = await authenticatedRequest('get', '/api/bot/state');
    console.log('Fetch Bot State Response:', response.body);
    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('is_connected', false);
    expect(response.body).toHaveProperty('users_len', 0);
  });

  it('should fetch bot state with valid Basic Auth', async () => {
    const response = await basicAuthRequest('get', '/api/bot/state');
    console.log('Fetch Bot State with Basic Auth Response:', response.body);
    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('is_connected', false);
    expect(response.body).toHaveProperty('users_len', 0);
  });

  it('should return QR code for bot connection', async () => {
    const response = await authenticatedRequest('get', '/api/bot/qr');
    console.log('QR Code Response:', response.body);
    expect(response.status).toBe(200);
    expect(Buffer.isBuffer(response.body) || (response.body instanceof Uint8Array)).toBeTruthy();
    // Or simply test that it's a valid PNG by checking the header bytes
    expect(response.body.slice(0, 8)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
    });

  it('should disconnect bot with valid authentication', async () => {
    const response = await authenticatedRequest('post', '/api/bot/disconnect');
    console.log('Disconnect Bot Response:', response.body);
    expect(response.status).toBe(400);
    expect(response.body).toHaveProperty('error', 'Bot is not connected');
  });
});


