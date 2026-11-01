/**
 * Consolidated controller for all app functions
 */
const fs = require('fs');
const QRCode = require('qrcode');
const { 
  readSubscribers, 
  deleteAllSubscribers, 
  importSubscribers, 
  getFinalSubscribersReport 
} = require('../data/subscribers');
const { 
  sendBroadcastMessage, 
  sendDocumentMessage,
  sendImageMessage
} = require('../whatsapp/send');
const { appProperties } = require('../globals');
const { generateThumbnail } = require('../utils/thumbnail');
  const { normalizePhone } = require('../utils/phone');
const { archiveStats, listChats, searchMessages } = require('../data/wa_archive');

/**
 * The chat client — the app's ONLY surface, and what the console embeds.
 *
 * The admin dashboard that used to live at /admin (ui/index.ejs) is gone, and its four sections were
 * relocated rather than dropped: connect → the connection switcher + the console's credential screen,
 * settings → the per-connection bot panel, actions and users → the client's tools modal. Its API
 * routes below all remain, because n8n calls them.
 */
const renderChat = (req, res) => {
  res.render('chat', { username: req.session.username });
};

/**
 * Login controller
 */
const renderLogin = (req, res) => {
  res.render('login', { error: null });
};

/**
 * Subscriber controllers
 */
const getSubscribers = async (req, res) => {
  try {
    const subscribers = await readSubscribers();
    res.json(subscribers);
  } catch (error) {
    console.error('Error fetching subscribers:', error);
    res.status(500).json({ error: 'Failed to fetch subscribers' });
  }
};

const deleteSubscribers = async (req, res) => {
  try {
    await deleteAllSubscribers();
    res.json({ success: true, message: 'All subscribers deleted' });
  } catch (error) {
    console.error('Error deleting subscribers:', error);
    res.status(500).json({ error: 'Failed to delete subscribers' });
  }
};

const createBackup = async (req, res) => {
  try {
    const subscribers = await readSubscribers();
    res.setHeader('Content-Disposition', `attachment; filename=backup_${Date.now()}.json`);
    res.json(subscribers);
  } catch (error) {
    console.error('Error creating backup:', error);
    res.status(500).send('Error creating backup');
  }
};

const restoreBackup = async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded' });
    }
    
    const backupData = JSON.parse(fs.readFileSync(req.file.path));
    await importSubscribers(backupData);
    
    // Clean up the uploaded file
    fs.unlinkSync(req.file.path);
    
    res.redirect('/');
  } catch (error) {
    console.error('Error restoring backup:', error);
    res.status(500).json({ error: 'Failed to restore backup' });
  }
};


/**
 * Bot controllers
 */
const getConnectionQr = (req, res) => {
  if (!appProperties.qr_text) {
    return res.status(404).send('QR code not available');
  }
  
  QRCode.toDataURL(appProperties.qr_text, (err, url) => {
    if (err) {
      console.error('Error generating QR code:', err);
      return res.status(500).send('Error generating QR code');
    }

    // Send the QR code image as a response
    res.setHeader('Content-Type', 'image/png');
    res.send(Buffer.from(url.split(",")[1], 'base64'));
  });
};

const getBotState = async (req, res) => {
  try {
    const subscribers = await readSubscribers();

    res.json({
      qr_text: appProperties.qr_text,
      is_connected: appProperties.is_connected,
      users_len: subscribers.length,
      botNumber: appProperties.botNumber,
      users: subscribers,
      lastDisconnect: appProperties.lastDisconnect
    });
  } catch (error) {
    console.error('Error fetching bot state:', error);
    res.status(500).json({ error: 'Failed to fetch bot state' });
  }
};

const disconnectBot = async (req, res) => {
  try {
    if (!appProperties.sock || !appProperties.is_connected) {
      return res.status(400).json({ error: 'Bot is not connected' });
    }
    
    console.log('Disconnecting bot...');
    await appProperties.sock.logout();
    
    res.json({ success: true, message: 'Bot disconnected successfully' });
  } catch (error) {
    console.error('Error disconnecting bot:', error);
    res.status(500).json({ error: 'Failed to disconnect bot' });
  }
};



const sendBroadcast = async (req, res) => {
  try {
    const { message } = req.body;
    
    if (!message) {
      return res.status(400).json({ error: 'Message is required' });
    }
    
    await sendBroadcastMessage(message);
    res.json({ success: true, message: 'Broadcast message sent successfully' });
  } catch (error) {
    console.error('Error sending broadcast message:', error);
    res.status(500).json({ error: 'Failed to send broadcast message' });
  }
};

const sendDocument = async (req, res) => {
  try {
    if (!appProperties.sock || !appProperties.is_connected) {
      return res.status(400).json({ success: false, message: 'Bot is not connected' });
    }

    if (!req.file) {
      return res.status(400).json({ success: false, message: 'No document uploaded' });
    }

    const { phoneNumber, caption } = req.body;

    if (!phoneNumber) {
      return res.status(400).json({ success: false, message: 'Phone number is required' });
    }

  // Normalize to E.164 local part without '+' using default country when missing
    const formattedPhoneNumber = normalizePhone(phoneNumber);

    const documentPath = req.file.path;

    // because multer filename is latin1 we need to convert it to utf8
    const utf8Filename = Buffer.from(req.file.originalname, 'latin1').toString('utf-8');

    // Generate real thumbnail (image or first PDF page) if supported
    let jpegThumbnail = null;
    try {
      jpegThumbnail = await generateThumbnail(documentPath, req.file.mimetype, utf8Filename);
    } catch (thumbErr) {
      console.warn('Thumbnail generation failed (non-fatal):', thumbErr.message);
    }

    const result = await sendDocumentMessage(
      appProperties.sock,
      formattedPhoneNumber,
      documentPath,
      utf8Filename,
      req.file.mimetype,
      caption || '',
      jpegThumbnail
    );

    res.json(result);
  } catch (error) {
    console.error('Error sending document:', error);
    res.status(500).json({ success: false, message: error.message });
  }
};

const getWhatsAppArchiveStats = async (req, res) => {
  try {
    res.json(await archiveStats());
  } catch (error) {
    console.error('Error fetching WhatsApp archive stats:', error);
    res.status(500).json({ error: 'Failed to fetch WhatsApp archive stats' });
  }
};

const getWhatsAppArchiveChats = async (req, res) => {
  try {
    const { type, limit, offset } = req.query;
    res.json(await listChats({ type, limit, offset }));
  } catch (error) {
    console.error('Error fetching WhatsApp archive chats:', error);
    res.status(500).json({ error: 'Failed to fetch WhatsApp archive chats' });
  }
};

const searchWhatsAppArchiveMessages = async (req, res) => {
  try {
    const { q, chatJid, from, to, limit, offset } = req.query;
    res.json(await searchMessages({ q, chatJid, from, to, limit, offset }));
  } catch (error) {
    console.error('Error searching WhatsApp archive messages:', error);
    res.status(500).json({ error: 'Failed to search WhatsApp archive messages' });
  }
};

const sendToJid = async (req, res) => {
  try {
    if (!appProperties.sock || !appProperties.is_connected) {
      return res.status(400).json({ error: 'Bot is not connected' });
    }
    const { jid, text } = req.body;
    if (!jid || !text) return res.status(400).json({ error: 'jid and text are required' });
    const result = await appProperties.sock.sendMessage(jid, { text });
    res.json({ success: true, key: result?.key });
  } catch (error) {
    console.error('Error sending to JID:', error);
    res.status(500).json({ error: error.message });
  }
};

const createGroup = async (req, res) => {
  try {
    if (!appProperties.sock || !appProperties.is_connected) {
      return res.status(400).json({ error: 'Bot is not connected' });
    }
    const { name, participants } = req.body;
    if (!name || typeof name !== 'string') {
      return res.status(400).json({ error: 'Group name is required' });
    }
    if (!participants || !Array.isArray(participants) || participants.length === 0) {
      return res.status(400).json({ error: 'At least one participant JID is required' });
    }
    console.log('[createGroup] Creating group:', name, 'with participants:', participants);
    const result = await appProperties.sock.groupCreate(name, participants);
    console.log('[createGroup] Group created! JID:', result.id);
    res.json({ success: true, groupJid: result.id, result });
  } catch (error) {
    console.error('[createGroup] Error:', error.message);
    res.status(500).json({ error: error.message });
  }
};

const groupParticipants = async (req, res) => {
  try {
    if (!appProperties.sock || !appProperties.is_connected) {
      return res.status(400).json({ error: 'Bot is not connected' });
    }
    const { groupJid, participants, action } = req.body;
    if (!groupJid || !participants || !Array.isArray(participants) || !action) {
      return res.status(400).json({ error: 'groupJid, participants (array), and action (add/remove/promote/demote) are required' });
    }
    if (!['add', 'remove', 'promote', 'demote'].includes(action)) {
      return res.status(400).json({ error: 'action must be add, remove, promote, or demote' });
    }
    console.log('[groupParticipants]', action, participants, 'in', groupJid);
    const result = await appProperties.sock.groupParticipantsUpdate(groupJid, participants, action);
    console.log('[groupParticipants] Done:', JSON.stringify(result).slice(0, 200));
    res.json({ success: true, result });
  } catch (error) {
    console.error('[groupParticipants] Error:', error.message);
    res.status(500).json({ error: error.message });
  }
};

const sendImageToJid = async (req, res) => {
  try {
    if (!appProperties.sock || !appProperties.is_connected) {
      return res.status(400).json({ error: 'Bot is not connected' });
    }
    if (!req.file) {
      return res.status(400).json({ error: 'No image uploaded' });
    }
    const { jid, caption } = req.body;
    if (!jid) return res.status(400).json({ error: 'jid is required' });
    const result = await sendImageMessage(appProperties.sock, jid, req.file.path, caption || '');
    // Clean up the uploaded file after sending
    fs.unlink(req.file.path, () => {});
    res.json(result);
  } catch (error) {
    console.error('Error sending image to JID:', error);
    if (req.file) fs.unlink(req.file.path, () => {});
    res.status(500).json({ error: error.message });
  }
};

module.exports = {
  // View controllers
  renderChat,
  renderLogin,
  
  // Subscriber controllers
  getSubscribers,
  deleteSubscribers,
  createBackup,
  restoreBackup,
  
  // Bot controllers
  getConnectionQr,
  getBotState,
  disconnectBot,
  sendBroadcast,
  sendDocument,
  sendToJid,
  sendImageToJid,
  createGroup,
  groupParticipants,

  // WhatsApp archive controllers
  getWhatsAppArchiveStats,
  getWhatsAppArchiveChats,
  searchWhatsAppArchiveMessages
};