/**
 * File upload middleware configuration
 */
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { CONFIG } = require('../../config');

// Create uploads directory if it doesn't exist
if (!fs.existsSync(CONFIG.UPLOADS_DIR)) {
  fs.mkdirSync(CONFIG.UPLOADS_DIR, { recursive: true });
}

// Configure storage for general uploads
const generalStorage = multer.diskStorage({
  destination: function (req, file, cb) {
    cb(null, CONFIG.UPLOADS_DIR);
  },
  filename: function (req, file, cb) {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
    cb(null, uniqueSuffix + '-' + file.originalname);
  }
});

// Configure storage for document uploads
const documentStorage = multer.diskStorage({
  destination: function (req, file, cb) {
    const uploadDir = path.join(CONFIG.UPLOADS_DIR, 'documents');
    if (!fs.existsSync(uploadDir)) {
      fs.mkdirSync(uploadDir, { recursive: true });
    }
    cb(null, uploadDir);
  },
  filename: function (req, file, cb) {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
    cb(null, uniqueSuffix + '-' + file.originalname);
  }
});

// Document file validation
const documentFileFilter = (req, file, cb) => {
  const allowedMimeTypes = ['application/pdf', 'image/jpeg', 'image/png'];
  
  if (!allowedMimeTypes.includes(file.mimetype)) {
    return cb(new Error('Invalid file type. Only PDF and image files are allowed.'), false);
  }
  
  cb(null, true);
};

// Configure storage for image (screenshot) uploads
const imageStorage = multer.diskStorage({
  destination: function (req, file, cb) {
    const uploadDir = path.join(CONFIG.UPLOADS_DIR, 'images');
    if (!fs.existsSync(uploadDir)) {
      fs.mkdirSync(uploadDir, { recursive: true });
    }
    cb(null, uploadDir);
  },
  filename: function (req, file, cb) {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
    cb(null, uniqueSuffix + '-' + file.originalname);
  }
});

// Image file validation
const imageFileFilter = (req, file, cb) => {
  const allowedMimeTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
  if (!allowedMimeTypes.includes(file.mimetype)) {
    return cb(new Error('Invalid file type. Only JPEG, PNG, WebP and GIF images are allowed.'), false);
  }
  cb(null, true);
};

// Create multer instances
const generalUpload = multer({ storage: generalStorage });
const documentUpload = multer({ 
  storage: documentStorage,
  fileFilter: documentFileFilter,
  limits: {
    fileSize: 10 * 1024 * 1024 // 10MB
  }
});
const imageUpload = multer({
  storage: imageStorage,
  fileFilter: imageFileFilter,
  limits: {
    fileSize: 10 * 1024 * 1024 // 10MB
  }
});

module.exports = {
  generalUpload,
  documentUpload,
  imageUpload
};