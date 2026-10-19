const fs = require('fs');
const path = require('path');
const axios = require('axios');
jest.mock('axios');

const { uploadFileAndGetLink } = require('../document_storage');
const { CONFIG } = require('../../config');

describe('uploadFileAndGetLink', () => {
  const tmpFile = path.join(__dirname, 'tmp-test.txt');
  beforeAll(() => {
    fs.writeFileSync(tmpFile, 'hello');
    // Ensure webhook auth configured
    CONFIG.N8N_UPLOAD_DOC_WEBHOOK = 'https://example.com/w';
    CONFIG.N8N_UPLOAD_DOC_USER = 'u';
    CONFIG.N8N_UPLOAD_DOC_PASS = 'p';
  });
  afterAll(() => {
    try { fs.unlinkSync(tmpFile); } catch {}
  });

  it('uses overrideName when provided', async () => {
    axios.post.mockResolvedValue({ data: { webViewLink: 'https://gdrive/link' } });
    const link = await uploadFileAndGetLink(tmpFile, 'Company-12345');
    expect(link).toBe('https://gdrive/link');
    expect(axios.post).toHaveBeenCalledTimes(1);
    const payload = axios.post.mock.calls[0][1];
    expect(payload.fileName).toBe('Company-12345');
  });
});
