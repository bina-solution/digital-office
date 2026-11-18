// The desktop app's own words, in the office's two languages. The system's language picks: Hebrew, unless the
// computer speaks another (then English). The office's pages keep their own language switch. Read by the screens
// (window.dgoWords) and by the main process for the tray and the menu (require).
'use strict';
(function (root) {
  const WORDS = {
    he: {
      dir: 'rtl', title: 'הלשכה הדיגיטלית', tagline: 'הלשכה נפתחת כמו כל אפליקציה, בלי דפדפן.',
      connectTitle: 'התחברות ללשכה', connectText: 'לשכה שכבר פועלת: בשרת, במשרד או במחשב אחר.',
      address: 'כתובת הלשכה', connect: 'התחברות', checking: 'בודק את הכתובת…',
      found: (o) => `נמצאה לשכה ב-${o}. פותח…`, notOffice: 'בכתובת הזו אין לשכה דיגיטלית.',
      err: { empty: 'כתבו את כתובת הלשכה.', 'https-only': 'ללשכה ברשת מתחברים רק בחיבור מאובטח (https).',
        'not-an-address': 'זו אינה כתובת של אתר.', credentials: 'בלי שם משתמש וסיסמה בתוך הכתובת.',
        unreachable: 'הכתובת לא ענתה. בדקו את החיבור לרשת ואת הכתובת.' },
      localTitle: 'הלשכה במחשב הזה', localChecking: 'בודק אם יש לשכה במחשב הזה…',
      localOn: 'הלשכה פועלת במחשב הזה.', localOff: 'הלשכה מותקנת במחשב הזה, והיא כבויה.',
      localNone: 'אין עדיין לשכה במחשב הזה. ההתקנה מורידה אותה ומכינה את המחשב.',
      open: 'פתיחה', start: 'הפעלה', starting: 'מפעיל את הלשכה…', install: 'התקנה…',
      back: 'חזרה', addOffice: 'לשכה נוספת', thisComputer: 'המחשב הזה', version: (v) => `גרסה ${v}`,
      trayOpen: 'פתיחת הלשכה', trayOn: 'פועלת', trayOff: 'כבויה', quit: 'יציאה', office: 'לשכה', reload: 'רענון',
      keepsRunning: 'הלשכה ממשיכה לפעול כאן, ליד השעון. יציאה: מהתפריט שלה.',
      shareTitle: 'שיתוף מסך', shareText: 'הפגישה מבקשת לשתף את המסך. איזה מסך?', screen: 'מסך', cancel: 'ביטול',
    },
    en: {
      dir: 'ltr', title: 'Digital Office', tagline: 'The office opens like any app, without a browser.',
      connectTitle: 'Connect to an office', connectText: 'An office that already runs: on a server, at work or on another computer.',
      address: "The office's address", connect: 'Connect', checking: 'Checking the address…',
      found: (o) => `Found an office at ${o}. Opening…`, notOffice: 'There is no Digital Office at this address.',
      err: { empty: "Type the office's address.", 'https-only': 'An office on the internet is reached over https only.',
        'not-an-address': 'This is not a web address.', credentials: 'No user name or password inside the address.',
        unreachable: 'The address did not answer. Check the network and the address.' },
      localTitle: 'The office on this computer', localChecking: 'Looking for an office on this computer…',
      localOn: 'The office is running on this computer.', localOff: 'The office is installed on this computer, and it is off.',
      localNone: 'There is no office on this computer yet. Installing downloads it and prepares the computer.',
      open: 'Open', start: 'Start', starting: 'Starting the office…', install: 'Install…',
      back: 'Back', addOffice: 'Another office', thisComputer: 'This computer', version: (v) => `Version ${v}`,
      trayOpen: 'Open the office', trayOn: 'running', trayOff: 'off', quit: 'Quit', office: 'Office', reload: 'Reload',
      keepsRunning: 'The office keeps running here, by the clock. To quit, use its menu.',
      shareTitle: 'Share your screen', shareText: 'The meeting asks to share a screen. Which one?', screen: 'Screen', cancel: 'Cancel',
    },
  };
  const pick = (locale) => WORDS[String(locale || 'he').toLowerCase().startsWith('he') ? 'he' : 'en'];
  if (typeof module === 'object' && module.exports) module.exports = pick;
  else root.dgoWords = pick;
})(this);
