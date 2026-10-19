const { join } = require('path');
require('dotenv').config();

const TEXTS = {
    WELCOME_MESSAGE: 'ברוכים הבאים לבוט הכהנים, ובו כל הפעולות שניתן לבצע דרך בוט הזה  - בהצלחה ',
    HELLO_BACK: 'הי {name}!\n\n',

    MENU_TEXT: 'איך אוכל לעזור לך היום? 🌟\n\n' +
        '1️⃣ בקש מהבוט להגיד שלום\n' +
        '2️⃣ אודות הבוט\n...',

    ADMIN_MENU_TEXT: '\nאפשרויות מנהל:\n \u20661️⃣0️⃣\u2069 קליטת דוח גיול \n \u20661️⃣1️⃣\u2069 קליטת חשבונית / ת. משלוח\n \u20661️⃣2️⃣\u2069 קליטת מסמך מקישור\n \u20661️⃣3️⃣\u2069 רענון הגדרות\n \u20661️⃣4️⃣\u2069 דוח דיפלוימנט מלא (~12 דק׳)\n \u20661️⃣5️⃣\u2069 בדיקת בריאות מהירה (~1–3 דק׳)\n \u20661️⃣6️⃣\u2069 סקירת דיפלוימנט (~5–8 דק׳)\n \u20661️⃣7️⃣\u2069 מצב agent-runner\n \u20661️⃣8️⃣\u2069 ביטול ריצה פעילה\n \u20661️⃣9️⃣\u2069 סקירת אבטחה (~3–5 דק׳)\n \u20662️⃣0️⃣\u2069 דוח אחסון (~3–5 דק׳)\n \u20662️⃣1️⃣\u2069 צ׳אט חי עם הסוכן (קריאה בלבד)\n \u20662️⃣2️⃣\u2069 🚀 Dispatcher — פיתוח אוטונומי (OpenHands)',

    INVALID_OPTION: 'לא הצלחתי להבין את הבחירה שלך \nאנא נסה/י שנית.',

    ABOUT_BOT: 'הבוט הזה נוצר על ידי bina-solutions.co.il, ומיועד לעזור בניהול פניות של חברת הכהנים.\n',

    DAILY_MESSAGE_LIMIT_REACHED: 'סליחה, הגעת למגבלת ההודעות היומית שלך. נשמח לעזור במה שתרצי מחר.',

    // Chat flow prompts and labels
    PROMPT_BALANCE_SHEET_FILE: 'שלח קובץ דוח גיול (Balance Sheet) בפורמט PDF / תמונה / TXT / Excel.',
    PROMPT_GENERIC_DOCUMENT_FILE: 'העבר קובץ PDF / תמונה של מסמך (חשבונית / ת. משלוח).',
    CANCELLED: 'בוטל.',
    PROMPT_GENERIC_DOCUMENT_ONLY: 'נא שלח קובץ מסמך (חשבונית / ת. משלוח).',
    // Quick acks shown immediately when a file is received
    PROCESSING_GENERIC_DOCUMENT: 'המסמך התקבל. מעבד כעת…',
    PROCESSING_BALANCE_SHEET: 'הקובץ התקבל. מעבד את דוח הגיול כעת…',
    GENERIC_DOC_RECEIVED_PREFIX: 'המסמך נקלט ✅',
    BALANCE_SHEET_RECEIVED_PREFIX: 'דוח גיול נקלט ✅',
    PROMPT_BALANCE_SHEET_FILE_OR_CANCEL: 'נא שלח קובץ דוח גיול (PDF / תמונה / TXT / Excel) או כתוב ביטול.',
    UNABLE_TO_GUESS_COMPANY: 'לא זוהתה חברה אוטומטית. כתוב ח.פ או שם חברה.',
    PROMPT_COMPANY_NOT_FOUND: 'לא זוהתה חברה. כתוב שם חלקי / ח.פ מדויק או "ביטול".',
    NO_PENDING_FILE_PREFIX: 'לא נמצא קובץ בהמתנה. התחל שוב עם ',
    LABEL_COMPANY: 'חברה: ',
    LABEL_DOCUMENT: 'מסמך: ',
    LABEL_LINK: 'קישור: ',
    NOT_APPLICABLE: 'N/A',
    ERROR_GENERIC_DOC_PREFIX: 'שגיאה בקליטת המסמך: ',
    ERROR_BALANCE_SHEET_PREFIX: 'שגיאה בקליטת דוח: ',
    ERROR_SAVE_FILE_PREFIX: 'שגיאה בשמירת הקובץ: ',

    // Link/URL document intake
    PROMPT_LINK_DOCUMENT: 'שלח קישור למסמך (URL).',
    PROCESSING_LINK_DOCUMENT: 'הקישור התקבל. מוריד ומעבד את המסמך כעת…',
    LINK_DOC_RECEIVED_PREFIX: 'מסמך מקישור נקלט ✅',
    ERROR_LINK_DOC_PREFIX: 'שגיאה בקליטת מסמך מקישור: ',
    PROMPT_LINK_ONLY: 'נא שלח קישור (URL) למסמך או כתוב ביטול.',
    INVALID_LINK: 'הקישור לא תקין. נא שלח קישור תקין (URL) או כתוב ביטול.',

    // Auto-intake (document/link sent outside menu)
    AUTO_INTAKE_DOC: 'זיהיתי מסמך 📄 — מעבד ומכניס למערכת אוטומטית…',
    AUTO_INTAKE_LINK: 'זיהיתי קישור 🔗 — מוריד ומכניס למערכת אוטומטית…',

    // Group chat
    GROUP_NOT_ADMIN: 'רק מנהלים יכולים לשלוח מסמכים דרך הקבוצה.',

    // Reload settings
    SETTINGS_RELOADED: 'הגדרות רועננו בהצלחה ✅',

    // Sunday deployment report (admin, full ~12m)
    SUNDAY_REPORT_STARTING: '🤖 מתחיל הפקת דוח דיפלוימנט מלא — זה לוקח כמה דקות…',
    SUNDAY_REPORT_DONE_PREFIX: '✅ הדוח מוכן. אורך: ',
    SUNDAY_REPORT_FAILED_PREFIX: '❌ שגיאה בהפקת דוח דיפלוימנט: ',

    // Quick health snapshot (admin, fast ~1-3m)
    QUICK_HEALTH_STARTING: '⚡ בודק בריאות מהירה…',
    QUICK_HEALTH_DONE_PREFIX: '✅ בדיקת בריאות מוכנה. אורך: ',
    QUICK_HEALTH_FAILED_PREFIX: '❌ שגיאה בבדיקת בריאות: ',

    // Mid-depth deployment review (admin, ~5-8m)
    DEPLOYMENT_REVIEW_STARTING: '🔍 מתחיל סקירת דיפלוימנט…',
    DEPLOYMENT_REVIEW_DONE_PREFIX: '✅ הסקירה מוכנה. אורך: ',
    DEPLOYMENT_REVIEW_FAILED_PREFIX: '❌ שגיאה בסקירת דיפלוימנט: ',

    // Security review (admin, ~3-5m)
    SECURITY_REVIEW_STARTING: '🛡️ מתחיל סקירת אבטחה…',
    SECURITY_REVIEW_DONE_PREFIX: '✅ סקירת אבטחה מוכנה. אורך: ',
    SECURITY_REVIEW_FAILED_PREFIX: '❌ שגיאה בסקירת אבטחה: ',

    // Storage report (admin, ~3-5m)
    STORAGE_REPORT_STARTING: '💾 מתחיל דוח אחסון…',
    STORAGE_REPORT_DONE_PREFIX: '✅ דוח האחסון מוכן. אורך: ',
    STORAGE_REPORT_FAILED_PREFIX: '❌ שגיאה בדוח אחסון: ',

    // Agent-runner status/cancel
    AGENT_STATUS_IDLE: '🟢 agent-runner פנוי',
    AGENT_STATUS_RUNNING_PREFIX: '🟡 רץ עכשיו: ',
    AGENT_STATUS_RUNNING_HINT: ' — שלח ⁦1️⃣8️⃣⁩ לביטול',
    AGENT_STATUS_FAILED_PREFIX: '❌ שגיאה בבדיקת מצב agent-runner: ',
    AGENT_CANCEL_NONE: 'אין ריצה פעילה לביטול.',
    AGENT_CANCEL_OK_PREFIX: '🛑 בוטל: ',
    AGENT_CANCEL_FAILED_PREFIX: '❌ שגיאה בביטול: ',

    // Busy / shared
    AGENT_RUNNER_BUSY_PREFIX: '⏳ ה-agent-runner תפוס כרגע ב-',
    AGENT_RUNNER_BUSY_HINT: 'נסה שוב מאוחר יותר או שלח ⁦1️⃣8️⃣⁩ לביטול.',

    // Shared across agent-runner jobs
    AGENT_JOB_ALREADY_RUNNING: '⏳ הפעולה כבר רצה עבורך — תוצאות יגיעו כשתסתיים. (שלח ⁦1️⃣8️⃣⁩ לביטול)',

    // Live agent chat (admin, choice 21)
    AGENT_CHAT_STARTED: '💬 Live agent chat started (read-only).\n\n' +
        'Send a question / task and the agent will answer. ~5 min per turn.\n\n' +
        'Commands:\n' +
        '  /end   — end chat, return to menu\n' +
        '  /stop  — cancel current turn\n' +
        '  /cost  — show cumulative cost\n' +
        '  /model — switch model (deepseek-chat, haiku, sonnet, opus)\n' +
        '  /status — agent-runner status\n\n' +
        'Default: *deepseek-chat* (DeepSeek V4 — fast, near-zero cost).\n' +
        'For deep reasoning: /model deepseek-reasoner.\n\n' +
        'The agent can read code, logs, docker ps/inspect/logs, postgres SELECT — read-only.',
    AGENT_CHAT_ENDED_PREFIX: '👋 Chat ended. ',
    AGENT_CHAT_TURN_FAILED_PREFIX: '❌ Turn error: ',
    AGENT_CHAT_BUSY_PREFIX: '⏳ Agent is busy. ',
    AGENT_CHAT_NO_TURN_RUNNING: 'No active turn.',
    AGENT_CHAT_TURN_CANCELLED: '🛑 Turn cancelled.',
    AGENT_CHAT_COST_PREFIX: '💰 Cumulative cost: ',
    AGENT_CHAT_BUDGET_EXHAUSTED_PREFIX: '🛑 Chat budget exceeded (',
    AGENT_CHAT_BUDGET_EXHAUSTED_SUFFIX: '). Chat closed. Send 21 to restart.',
    AGENT_CHAT_IDLE_TIMEOUT: '⌛ Chat closed (15 min idle). Send 21 to restart.',
    AGENT_CHAT_EMPTY_REPLY: '(no text returned)',

    // Dispatcher — OpenHands autonomous coding (admin, choice 22)
    DISPATCHER_STARTED: '🚀 *Dispatcher Mode — OpenHands Autonomous Coding*\n\n' +
        'שלח משימת פיתוח והסוכן יבצע אותה עם גישה מלאה לשרת.\n\n' +
        'Commands:\n' +
        '  /end   — סיום חזרה לתפריט\n' +
        '  /stop  — ביטול משימה נוכחית\n' +
        '  /status — מצב dispatcher\n' +
        '  /model — החלף מודל\n\n' +
        'הסוכן יכול: לקרוא/לכתוב קבצים, להריץ docker, לערוך קוד, לדבג, לבצע git commit — גישת פיתוח מלאה.',
    DISPATCHER_ENDED_PREFIX: '👋 Dispatcher ended. ',
    DISPATCHER_TURN_FAILED_PREFIX: '❌ Dispatcher error: ',
    DISPATCHER_BUSY_PREFIX: '⏳ Dispatcher busy. ',
    DISPATCHER_NO_ACTIVE: 'No active dispatch.',
    DISPATCHER_CANCELLED: '🛑 Dispatch cancelled.',
    DISPATCHER_EMPTY_REPLY: '(no output returned)',
    DISPATCHER_STARTING: '🤖 מפעיל OpenHands agent…',
    DISPATCHER_TOOL_COUNT_PREFIX: '🔧 Tools used: ',
    DISPATCHER_DURATION_PREFIX: '⏱️ Duration: ',
};

const CONFIG = {
    TEXTS,
    // Default country code used to normalize phone numbers (E.164 without '+')
    DEFAULT_COUNTRY_CODE: process.env.DEFAULT_COUNTRY_CODE || '972',
    ADMINS: [
        // note: admins sorces: hardcoded, env, adds to admins from settings api
        '16828167052', '050-000-0002', '050-000-0008',
        process.env.ADMIN_PHONE_1  || 'env_admin_1',
        process.env.ADMIN_PHONE_2  || 'env_admin_2'
    ],
    CONTENT_MEDIA: join(__dirname, '../media/campaign-media.mp4'),
    SHOPCONTACT_DISPLAY_NAME: process.env.SHOPCONTACT_DISPLAY_NAME || 'תמר יעקב',
    SHOPCONTACT_PHONE: process.env.SHOPCONTACT_PHONE || '050-000-0005',
    SHOPCONTACT_WID: process.env.SHOPCONTACT_WID || '050-000-0005',
    SHOPCONTACT_ORG: process.env.SHOPCONTACT_ORG || 'לנשום',
    PORT: parseInt(process.env.APP_PORT || '3000'),
    SUBSCRIBERS_DB_PATH: join(__dirname, '../data/subscribers.db'),
    DAILY_MESSAGE_LIMIT: parseInt(process.env.DAILY_MESSAGE_LIMIT || '100'),
    UPLOADS_DIR: process.env.UPLOADS_DIR || join(__dirname, '../data/uploads'),
    WA_ARCHIVE_ENABLED: process.env.WA_ARCHIVE_ENABLED !== 'false',
    WA_ARCHIVE_DB_PATH: process.env.WA_ARCHIVE_DB_PATH || join(__dirname, '../data/wa_archive.db'),
    WA_ARCHIVE_SYNC_FULL_HISTORY: process.env.WA_ARCHIVE_SYNC_FULL_HISTORY !== 'false',
    // Authentication settings
    AUTH_ENABLED: process.env.AUTH_ENABLED !== 'false',
    AUTH_USERNAME: process.env.AUTH_USERNAME || 'admin',
    AUTH_PASSWORD: process.env.AUTH_PASSWORD || '1234',
    SESSION_SECRET: process.env.SESSION_SECRET || 'hacohanim-secret-key',
    SESSION_MAX_AGE: parseInt(process.env.SESSION_MAX_AGE || '86400000'), // 24 hours
    IS_PRODUCTION: process.env.NODE_ENV === 'production',
    APP_VERSION: '0.7.4',
    RATE_LIMIT: {
        API: {
            WINDOW_MS: parseInt(process.env.API_RATE_LIMIT_WINDOW_MS || '300000'), // 5 minutes
            MAX: parseInt(process.env.API_RATE_LIMIT_MAX || '500')
        },
        LOGIN: {
            WINDOW_MS: parseInt(process.env.LOGIN_RATE_LIMIT_WINDOW_MS || '300000'), // 5 minutes
            MAX: parseInt(process.env.LOGIN_RATE_LIMIT_MAX || '10')
        }
    }
    // ── in-cluster by default, NOT the hacohen production domain ────────────────────────────────
    // These four defaulted to https://n8n.hacohen.bina-solutions.co.il/webhook/…, which is one
    // specific customer's deployment. The platform ships one deployment per company, so on every
    // OTHER deployment that default is wrong in two ways at once: with no egress it times out
    // (observed here — "N8N Settings Webhook: timeout of 10000ms exceeded", the bot then starts with
    // an empty admin list and refuses every document), and WITH egress it silently reads and writes
    // another company's settings, companies and documents.
    //
    // Service DNS is the correct default: it is the same instance the rest of this deployment uses,
    // it needs no domain, no certificate and no egress, and it cannot reach a different tenant.
    // Same convention as apps/indox (N8N_WEBHOOK_BASE=http://n8n:5678/webhook). An explicit env var
    // still wins, so a deployment that genuinely wants a remote n8n sets one.
    // ── indox, reached through its OWN API ──────────────────────────────────────────────────────
    // Chat and indox share data (companies, document intake) but must not share a settings store:
    // indox's `settings` table is its document-processing configuration and nothing else may reach
    // into it. Anything chat needs from indox comes over `indox-api`, which apps/indox declares and
    // apps/chat's app.json now consumes. The prefix is indox's own default
    // (INCOMING_DOCS_API_PREFIX in its blueprint factory) — without it every request lands on the
    // SPA catch-all and comes back as HTML with a 200, which reads as a working endpoint.
    , INDOX_API_BASE: process.env.INDOX_API_BASE || 'http://incoming-documents:8080'
    , INDOX_API_PREFIX: process.env.INDOX_API_PREFIX || '/incomingDocuments'
    , N8N_WEBHOOK_BASE: process.env.N8N_WEBHOOK_BASE || 'http://n8n:5678/webhook'
    // The INDOX tenant the LEGACY settings/company webhooks serve. Since the 2026-08-28 tenancy
    // cutover those endpoints THROW without ?__instance= — every tenantless call became an n8n
    // error execution (measured 2026-08-31: 24/hour from this app's startup check + admin
    // loader). Empty means "legacy source disabled": the callers SKIP the request entirely —
    // chat-owned botAdmins and CONFIG.ADMINS keep working — instead of hammering an API that
    // refuses by design.
    , INDOX_INSTANCE: process.env.INDOX_INSTANCE || ''
    , N8N_COMPANY_WEBHOOK: process.env.N8N_COMPANY_WEBHOOK || `${process.env.N8N_WEBHOOK_BASE || 'http://n8n:5678/webhook'}/company`
    , N8N_SETTINGS_WEBHOOK: process.env.N8N_SETTINGS_WEBHOOK || `${process.env.N8N_WEBHOOK_BASE || 'http://n8n:5678/webhook'}/setting`
    , N8N_UPLOAD_DOC_WEBHOOK: process.env.N8N_UPLOAD_DOC_WEBHOOK || `${process.env.N8N_WEBHOOK_BASE || 'http://n8n:5678/webhook'}/upload-document`
    , INCOMING_DOCS_WEBHOOK: process.env.INCOMING_DOCS_WEBHOOK || `${process.env.N8N_WEBHOOK_BASE || 'http://n8n:5678/webhook'}/incoming_document`
    , N8N_UPLOAD_DOC_USER: process.env.N8N_UPLOAD_DOC_USER || 'admin'
    , N8N_UPLOAD_DOC_PASS: process.env.N8N_UPLOAD_DOC_PASS || 'password'
    // The other half of n8n's 'Settings Auth' credential, which the platform provisions from
    // SETTINGS_AUTH_USER/PASS (see this app's docker-compose.yml, which bridges the two names).
    // The password default was a hardcoded literal, and a literal here is worse than nothing: it
    // cannot match the value any deployment actually minted, so it produced a confident 403 instead
    // of an obviously-missing credential. Empty means "not configured" and says so.
    , N8N_SETTINGS_USER: process.env.N8N_SETTINGS_USER || 'settings'
    , N8N_SETTINGS_PASS: process.env.N8N_SETTINGS_PASS || ''
    , N8N_INCOMING_DOCS_USER: process.env.N8N_INCOMING_DOCS_USER || 'admin'
    , N8N_INCOMING_DOCS_PASS: process.env.N8N_INCOMING_DOCS_PASS || 'wdnkjd728762873bhjd386213hjg37dksxi72sh'
    // Document OCR / Query endpoints. Same reasoning as the n8n webhooks above: apitools is a service
    // in THIS deployment (apps/apitools declares `http://apitools:8080`), so defaulting to one
    // customer's public hostname sent every other deployment's documents to that customer's OCR.
    , DOCUMENT_OCR_ENDPOINT: process.env.DOCUMENT_OCR_ENDPOINT || 'http://apitools:8080/documentOcr'
    , DOCUMENT_JSON_QUERY_ENDPOINT: process.env.DOCUMENT_JSON_QUERY_ENDPOINT || 'http://apitools:8080/documentJsonQuery'
    // Structured JSON query specs for OCR value extraction
    , DOCUMENT_JSON_QUERIES: {
        INVOICE_ID: {
            "action": "find after",
            "action_value": [
                "חשבונית מס זיכוי מס':",
                "חשבונית מס זיכוי",
                "חשבונית מס מרוכזת מספר:",
                "חשבונית מס מרכזת",
                "חשבונית מס/קבלה מס':",
                "חשבונית מס מספר:",
                "חשבונית מס/קבלה",
                "חשבונית מס / קבלה",
                "חשבונית מס מספר",
                "חשבונית מס מס':",
                "חשבונית מס\"",
                "חשבונית מס -",
                "חשבונית מס :",
                "חשבונית זיכוי",
                "חשבונית מס'",
                "חשבונית מס"
            ],
            "value_validations": [
                { "validation_type": "has_number" },
                { "validation_type": "length_greater_than", "validation_value": 3 },
                { "validation_type": "length_less_than", "validation_value": 20 }
            ],
            "is_rtl": true
        },
        SHIPMENT_ID: {
            "action": "find after",
            "action_value": [
                "תעודת משלוח מספר",
                "משלוח מספר",
                "תעודת משלוח מס':",
                "תעודת משלוח מס'",
                "משלוח מספר    ",
                "משלוח מס' :    ",
                "תעודת משלוח מס'",
                "תעודת משלוח                ",
                "תעודת משלוח מס",
                "תעודת משלוח",
                "מספר משלוח",
                "משלוח מס'"

            ],
            "value_validations": [
                {
                    "validation_type": "has_number"
                },
                {
                    "validation_type": "length_greater_than",
                    "validation_value": 3
                },
                { "validation_type": "length_less_than", "validation_value": 20 }
            ],
            "is_rtl": true
        }
    }
};

module.exports = { CONFIG, TEXTS };