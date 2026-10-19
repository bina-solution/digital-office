const fs = require('fs');
const crypto = require('crypto');

/**
 * Compute md5 hash of a file. Returns null if file can't be read.
 * @param {string} filePath
 * @returns {string|null}
 */
function hashFile(filePath) {
  try {
    const data = fs.readFileSync(filePath);
    return crypto.createHash('md5').update(data).digest('hex');
  } catch {
    return null;
  }
}

module.exports = { hashFile };
