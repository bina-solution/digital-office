// Utility for generating JPEG thumbnails for supported document types (images & PDFs)
// Returns Buffer (jpeg) or null if generation not possible.
const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');
const { execFile } = require('child_process');
const sharp = require('sharp');

const MAX_DIMENSION = 300; // px
const JPEG_QUALITY = 70;   // percent
const MAX_SIZE_BYTES = 200 * 1024; // 200KB safeguard

async function generateImageThumbnail(filePath) {
  if (!sharp) return null;
  const buffer = fs.readFileSync(filePath);
  return await sharp(buffer)
    .resize({ width: MAX_DIMENSION, fit: 'inside' })
    .jpeg({ quality: JPEG_QUALITY })
    .toBuffer();
}

function runPdftoppm(pdfPath, outputDir) {
  return new Promise((resolve, reject) => {
    const prefix = path.join(outputDir, `thumb_${randomUUID()}`);
    // -singlefile ensures name without -1 suffix across versions
    execFile('pdftoppm', ['-jpeg', '-f', '1', '-l', '1', '-singlefile', pdfPath, prefix], (err) => {
      if (err) return reject(err);
      resolve(`${prefix}.jpg`);
    });
  });
}

async function generatePdfThumbnail(filePath) {
  // Requires poppler-utils (pdftoppm). If not installed, we return null.
  const tmpDir = path.dirname(filePath);
  let jpgPath;
  try {
    jpgPath = await runPdftoppm(filePath, tmpDir);
  } catch (e) {
    if (e.code === 'ENOENT') {
      console.warn('[thumbnail] pdftoppm not found. Install poppler-utils for PDF previews.');
    } else {
      console.warn('[thumbnail] pdftoppm failed:', e.message);
    }
    return null;
  }
  try {
    let buffer = fs.readFileSync(jpgPath);
    buffer = await sharp(buffer)
    .resize(MAX_DIMENSION, MAX_DIMENSION, { fit: 'inside' })
    .jpeg({ quality: JPEG_QUALITY })
    .toBuffer();
    
    // cleanup temp jpg
    fs.unlink(jpgPath, () => {});

    return buffer.length <= MAX_SIZE_BYTES ? buffer : null;
  } catch (e) {
    console.warn('[thumbnail] Failed processing PDF jpg:', e.message);
    return null;
  }
}

async function generateThumbnail(filePath, mimetype) {
  if (!mimetype) return null;
  if (mimetype.startsWith('image/')) {
    try { return await generateImageThumbnail(filePath); } catch (e) { console.warn('[thumbnail] image generation failed:', e.message); return null; }
  }
  if (mimetype === 'application/pdf') {
    return await generatePdfThumbnail(filePath);
  }
  return null; // unsupported type
}

module.exports = { generateThumbnail };
