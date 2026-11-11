/* dev/mock.js — «קבצים» without a server: an in-page stand-in for the drive API, with content that
   looks like an office's (folders of recordings and meetings, photos of several shapes, audio with
   a real waveform, a PDF, a Word document, a spreadsheet, code, an archive, a 3D model). It is the
   ground the layout QA runs on and the demo a person can drive; it never ships (the image copies
   static/ only). Every answer has the shape apps/drive/app.py gives. */
(function () {
  "use strict";
  const realFetch = window.fetch.bind(window);
  const BASE = new URL(".", document.baseURI).pathname;
  const now = Date.now();
  const iso = (msAgo) => new Date(now - msAgo).toISOString().slice(0, 16).replace("T", " ");
  let n = 100;
  const id = (p) => p + (++n).toString(36) + "x";
  const H = 3600e3, D = 24 * H;

  /* ── the tree ────────────────────────────────────────────────────────── */
  const folders = [];
  const F = (name, parent, extra) => { const f = { id: id("ld"), name, parent: parent || null, last: iso(Math.random() * 30 * D), owner: "אני", mine: true, ...extra }; folders.push(f); return f; };
  const rec = F("הקלטות", "", { system: "הקלטות" }), meet = F("פגישות", "", { system: "פגישות" });
  const m1 = F("2026-10-27 · ישיבת צוות", meet.id), m2 = F("2026-10-21 · לקוח — הצעת מחיר", meet.id);
  /* the names meet-start writes (a Latin room after the date; a Hebrew word before a Latin stem) — the live office has them (EXF-385) */
  const m3 = F("2026-10-28 · exf106", meet.id);
  const docs = F("מסמכים", ""), inv = F("חשבוניות 2026", docs.id), contracts = F("חוזים", docs.id);
  const photos = F("תמונות מהשטח", ""), proj = F("פרויקטים", ""), p1 = F("ארובה — רחוב הדקל 12", proj.id), p2 = F("Lancaster TX — chimney caps", proj.id);
  F("ארכיון ישן מאוד עם שם ארוך שבודק שהשורה לא נשברת ולא דוחפת דברים החוצה", "");

  const files = [];
  const blobs = {};
  const add = (name, folder, size, mime, ago, meta, make) => {
    const f = { id: id("lf"), name, folder: folder || "", size, mime, created: iso(ago), starred: false, opened: "", md5: Math.random().toString(16).slice(2, 10),
      owner: "אני", owner_id: "admin", mine: true, shared: [], link: location.origin + BASE + "file/d/demo/view", meta };
    files.push(f); if (make) blobs[f.id] = make; return f;
  };

  /* pictures drawn on the spot, in the palette read off the page */
  const tok = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#888";
  function picture(w, h, seed, label) {
    return () => new Promise((res) => {
      const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d");
      const hues = ["--olive", "--sky", "--lime", "--plum", "--sky-d", "--olive-d"].map(tok);
      const gr = g.createLinearGradient(0, 0, w, h); gr.addColorStop(0, hues[seed % 6]); gr.addColorStop(1, hues[(seed + 2) % 6]);
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
      for (let i = 0; i < 9; i++) { g.globalAlpha = 0.18; g.fillStyle = hues[(seed + i) % 6]; g.beginPath();
        g.arc(((seed * 97 + i * 131) % w), ((seed * 53 + i * 71) % h), (w + h) / (6 + (i % 4)), 0, 7); g.fill(); }
      g.globalAlpha = 1; g.fillStyle = tok("--surface"); g.font = `bold ${Math.round(Math.min(w, h) / 9)}px system-ui`; g.textAlign = "center";
      g.fillText(label || "", w / 2, h / 2);
      c.toBlob((b) => res(b), "image/jpeg", 0.82);
    });
  }
  /* sound: chords with an envelope, so the waveform has a shape */
  function sound(seconds, seed) {
    return () => {
      const rate = 8000, len = Math.round(rate * seconds), buf = new ArrayBuffer(44 + len * 2), v = new DataView(buf);
      const w = (o, s) => [...s].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)));
      w(0, "RIFF"); v.setUint32(4, 36 + len * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
      v.setUint16(22, 1, true); v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
      w(36, "data"); v.setUint32(40, len * 2, true);
      const notes = [220, 277, 330, 440, 247, 294].map((f) => f * (1 + (seed % 3) * 0.12));
      for (let i = 0; i < len; i++) {
        const t = i / rate, beat = Math.floor(t * 2) % notes.length, env = Math.abs(Math.sin(t * Math.PI * (0.5 + (seed % 4) * 0.25))) * (0.45 + 0.4 * Math.sin(t / 7));
        const s = (Math.sin(2 * Math.PI * notes[beat] * t) + 0.5 * Math.sin(2 * Math.PI * notes[(beat + 2) % notes.length] * t)) * env * 9000;
        v.setInt16(44 + i * 2, Math.max(-32767, Math.min(32767, s)), true);
      }
      return new Blob([buf], { type: "audio/wav" });
    };
  }
  const text = (s, type) => () => new Blob([s], { type: type || "text/plain" });
  function pdf() {
    const objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >>",
      "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
      null, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
      "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 7 0 R /Resources << /Font << /F1 5 0 R >> >> >>", null];
    const page = (lines) => { const s = "BT /F1 22 Tf 60 770 Td (" + lines[0] + ") Tj /F1 12 Tf " + lines.slice(1).map((l) => "0 -24 Td (" + l + ") Tj").join(" ") + " ET"; return "<< /Length " + s.length + " >>\nstream\n" + s + "\nendstream"; };
    objs[3] = page(["Quote #1042 - The Examplef Guys", "Customer: 501 Colgate Dr, Lancaster TX", "Chimney cap, stainless, 13x13 flue", "Installation and inspection", "Total: $1,240.00"]);
    objs[6] = page(["Page 2 - Terms", "Valid for 30 days.", "Thank you for your business."]);
    let out = "%PDF-1.4\n", off = [];
    objs.forEach((o, i) => { off.push(out.length); out += (i + 1) + " 0 obj\n" + o + "\nendobj\n"; });
    const x = out.length;
    out += "xref\n0 " + (objs.length + 1) + "\n0000000000 65535 f \n" + off.map((o) => String(o).padStart(10, "0") + " 00000 n \n").join("") +
      "trailer\n<< /Size " + (objs.length + 1) + " /Root 1 0 R >>\nstartxref\n" + x + "\n%%EOF";
    return () => new Blob([out], { type: "application/pdf" });
  }
  const lib = (src) => new Promise((res, rej) => { if (document.querySelector(`script[data-dev="${src}"]`)) return res(); const s = document.createElement("script");
    s.src = BASE + "vendor/" + src; s.dataset.dev = src; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
  const docx = () => async () => {
    await lib("jszip-3.10.2/jszip.min.js");
    const z = new JSZip();
    z.file("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>');
    z.file("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>');
    const p = (t, b) => `<w:p><w:pPr><w:bidi/><w:jc w:val="right"/></w:pPr><w:r><w:rPr>${b ? "<w:b/><w:sz w:val=\"36\"/>" : ""}<w:rtl/></w:rPr><w:t xml:space="preserve">${t}</w:t></w:r></w:p>`;
    z.file("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
      p("הסכם שירות — התקנת כובע ארובה", true) + p("בין: The Examplef Guys (להלן: «הספק»)") + p("לבין: הלקוח, רחוב הדקל 12") +
      p("1. הספק יתקין כובע ארובה מנירוסטה במידה 13×13 אינץ׳ כולל בדיקת תקינות.") + p("2. התשלום: 1,240 דולר, עם סיום העבודה.") + p("3. אחריות: 5 שנים על החומר ושנה על ההתקנה.") +
      "</w:body></w:document>");
    return z.generateAsync({ type: "blob" });
  };
  const xlsx = () => async () => {
    await lib("xlsx-0.20.3/xlsx.full.min.js");
    const wb = XLSX.utils.book_new();
    const rows = [["חודש", "הכנסות", "הוצאות", "רווח"], ...["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר"]
      .map((m, i) => { const a = 18000 + i * 1450, b = 11000 + (i % 3) * 900; return [m, a, b, a - b]; })];
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(rows), "סיכום 2026");
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([["לקוח", "עיר", "סכום"], ["Smith", "Dallas", 1240], ["Cohen", "Plano", 860], ["Garcia", "Lancaster", 2100]]), "לקוחות");
    return new Blob([XLSX.write(wb, { type: "array", bookType: "xlsx" })]);
  };
  const zip = () => async () => {
    await lib("fflate-0.8.3/fflate.umd.js");
    const enc = new TextEncoder();
    return new Blob([fflate.zipSync({ "readme.txt": enc.encode("Site photos and notes"), "notes/measure.txt": enc.encode("13x13 flue, 2 storeys"), "notes/קבלה.txt": enc.encode("שולם") })]);
  };
  const stl = () => text("solid pyramid\n" + [[[0, 0, 0], [10, 0, 0], [5, 8, 0]], [[0, 0, 0], [5, 4, 9], [10, 0, 0]], [[10, 0, 0], [5, 4, 9], [5, 8, 0]], [[5, 8, 0], [5, 4, 9], [0, 0, 0]]]
    .map((t) => "facet normal 0 0 0\n outer loop\n" + t.map((p) => "  vertex " + p.join(" ")).join("\n") + "\n endloop\nendfacet").join("\n") + "\nendsolid pyramid\n", "model/stl");

  /* recordings and meetings */
  add("הקלטה חדשה 3.m4a", rec.id, 43423451, "audio/mp4", 2 * H, { duration: 5169, title: "פגישת צוות — חלק ב׳" }, sound(96, 1));
  add("הקלטה חדשה.m4a", rec.id, 8388568, "audio/mp4", 2.4 * H, { duration: 1005, title: "פגישת צוות — חלק א׳" }, sound(64, 2));
  add("רעיונות לאתר.m4a", rec.id, 1620000, "audio/mp4", 3 * D, { duration: 192 }, sound(40, 3));
  add("exf105_2026-10-28-09-02.mp4", meet.id, 612400000, "video/mp4", 5 * H, { duration: 6845, w: 1280, h: 720 }, null);
  add("תמלול — ישיבת צוות.md", m1.id, 8200, "text/markdown", 20 * H, null, text("# ישיבת צוות — 27.10\n\n**משתתפים:** שלמה, אלן, ויליאם\n\n## החלטות\n- מחירון חדש לכובעים עד יום ראשון\n- **אלן** מוסר תמונות מהשטח\n\n> \"כל הקבצים במקום אחד\" — שלמה\n\n| נושא | אחראי |\n|---|---|\n| אתר | ויליאם |\n| מחירון | אלן |\n", "text/markdown"));
  add("הצעת מחיר 1042.pdf", m2.id, 18400, "application/pdf", 7 * D, null, pdf());
  add("תמלול — exf106.txt", m3.id, 491, "text/plain", 16 * H, null, text("[00:00] שלמה: מתחילים.\n[00:12] אלן: הכובע הגיע.\n"));
  add("כתוביות — exf106.vtt", m3.id, 749, "text/vtt", 16 * H, null, text("WEBVTT\n\n00:00.000 --> 00:04.000\nשלמה: מתחילים.\n", "text/vtt"));
  /* documents */
  add("הסכם שירות — הדקל 12.docx", contracts.id, 7400, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 4 * D, null, docx());
  add("דוח הכנסות 2026.xlsx", docs.id, 16900, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 26 * H, null, xlsx());
  add("לקוחות.csv", docs.id, 420, "text/csv", 6 * D, null, text("שם,טלפון,עיר\nג׳ון סמית׳,469-555-0101,Dallas\nדנה כהן,469-555-0177,Plano\nמיגל גרסיה,469-555-0142,Lancaster\n", "text/csv"));
  add("חשבונית 2026-0042.pdf", inv.id, 18400, "application/pdf", 9 * D, null, pdf());
  add("חשבונית 2026-0043.pdf", inv.id, 18400, "application/pdf", 8 * D, null, pdf());
  add("מצגת למשקיעים.pptx", docs.id, 3_400_000, "application/vnd.openxmlformats-officedocument.presentationml.presentation", 12 * D, null, text("x"));
  add("הצעה ישנה.doc", contracts.id, 88000, "application/msword", 40 * D, null, text("x"));
  /* photos of several shapes */
  [[1600, 1200, "גג צפוני"], [1200, 1600, "ארובה"], [1600, 900, "רחוב הדקל"], [1080, 1080, "כובע 13×13"], [2000, 1000, "פנורמה"], [900, 1600, "סולם"], [1600, 1066, "לפני"], [1600, 1066, "אחרי"]]
    .forEach(([w, h, l], i) => add(`IMG_${4410 + i}.jpg`, photos.id, 900000 + i * 123000, "image/jpeg", (i + 1) * 9 * H, { w, h }, picture(w / 4, h / 4, i, l)));
  add("שרטוט חזית.png", p1.id, 240000, "image/png", 30 * H, { w: 1400, h: 1000 }, picture(350, 250, 7, "חזית"));
  add("IMG_5001.heic", p2.id, 2_100_000, "image/heic", 4 * H, { w: 4032, h: 3024 }, null);
  /* code, data and the rest */
  add("pricing.py", proj.id, 1200, "text/x-python", 3 * D, null, text('"""Chimney cap pricing."""\n\ndef price(width, height, metal="stainless"):\n    base = 180 + 4.5 * (width * height) ** 0.5\n    if metal == "copper":\n        base *= 1.85  # copper costs more\n    return round(base, 2)\n\n\nif __name__ == "__main__":\n    print(price(13, 13))\n'));
  add("config.json", proj.id, 230, "application/json", 9 * D, null, text('{"office":"examplef","storage":{"limit_gb":2},"apps":["files","meet","recorder"]}'));
  add("deploy.env", proj.id, 120, "text/plain", 9 * D, null, text("DOMAIN=exf.digital-office.co.il\nSTRIPE_KEY=sk_live_not_a_real_key\nMAIL=office@example.com\n"));
  add("index.html", proj.id, 300, "text/html", 11 * D, null, text("<!doctype html><h1 style='font-family:sans-serif'>The Examplef Guys</h1><p>Landing page draft.</p><script>alert('never runs')</script>"));
  add("logo.svg", proj.id, 380, "image/svg+xml", 14 * D, { w: 120, h: 120 }, text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" rx="24" fill="#56693f"/><path d="M30 80h60L60 30z" fill="#f3f5f7"/></svg>', "image/svg+xml"));
  add("תמונות לאתר.zip", proj.id, 3_200_000, "application/zip", 15 * D, null, zip());
  add("chimney-cap.stl", p2.id, 1800, "model/stl", 2 * D, null, stl());
  add("אלן — טכנאי.vcf", "", 260, "text/vcard", 16 * D, null, text("BEGIN:VCARD\nVERSION:3.0\nFN:אלן לוי\nORG:The Examplef Guys\nTEL:+1-469-555-0119\nEMAIL:alan@example.com\nEND:VCARD\n"));
  add("התקנה אצל סמית׳.ics", "", 300, "text/calendar", 2 * D, null, text("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:התקנת כובע ארובה — סמית׳\nDTSTART:20261030T150000Z\nDTEND:20261030T170000Z\nLOCATION:501 Colgate Dr, Lancaster TX\nDESCRIPTION:להביא סולם 24 רגל\nEND:VEVENT\nEND:VCALENDAR\n"));
  add("installer.exe", "", 48_000_000, "application/vnd.microsoft.portable-executable", 33 * D, null, text("MZ"));
  files[0].starred = true; files[6].starred = true;
  folders[0].starred = true;

  /* ── answers ─────────────────────────────────────────────────────────── */
  const trashed = new Set(), trashedFolders = new Set();
  const live = () => files.filter((f) => !trashed.has(f.id) && !inTrashedFolder(f.folder));
  const inTrashedFolder = (fid) => { let c = fid; const m = Object.fromEntries(folders.map((f) => [f.id, f])); while (c) { if (trashedFolders.has(c)) return true; c = (m[c] || {}).parent; } return false; };
  const liveFolders = () => folders.filter((f) => !inTrashedFolder(f.id));
  const json = (body, status) => new Response(JSON.stringify(body), { status: status || 200, headers: { "Content-Type": "application/json" } });
  const counts = () => liveFolders().map((f) => ({ ...f, count: live().filter((x) => x.folder === f.id).length }));
  const pathOf = (fid) => { const m = Object.fromEntries(folders.map((f) => [f.id, f])), out = []; while (fid && m[fid]) { out.unshift(m[fid].name); fid = m[fid].parent; } return "/" + out.join("/"); };
  const peaks = (fid) => { let s = fid.length * 7; return Array.from({ length: 600 }, (_, i) => { s = (s * 9301 + 49297) % 233280; return 0.15 + 0.85 * Math.abs(Math.sin(i / 23)) * (0.55 + 0.45 * (s / 233280)); }); };
  const uploads = {};
  let rev = 1;
  const bump = () => (rev += 1);

  /* ── the account plane: every drive of the office (accounts.js) ──────────
     Three drives — the office storage's two profiles and a Google account — answered as app.py answers
     /connections, /providers, /engine/profiles and the probe. `?oauth=dead` on the page's address makes
     the sign-in answer what every office's Google client answered on 2026-11-05 (invalid_client). */
  const ADMIN = "drive_local-demo", USER2 = "drive_local-user2", GMAIL = "drive_google_oauth-demo";
  const LOCAL_CONN = { views: ["recent", "starred", "added"], optional_ops: ["star", "storage", "touch", "views"], media: true, creates: true };
  const GOOGLE_CONN = { views: ["recent", "starred", "shared", "added"], optional_ops: ["star", "storage", "views"], media: true, creates: true };
  const SA_CONN = { ...GOOGLE_CONN, creates: false };
  const conns = [
    { id: ADMIN, protocol: "drive_local", label: "מנהל", account_hint: "admin", profile_id: "admin", is_private: true, is_admin: true, profile_status: "active", status: "ok", engine: "drive_local", app: "drive" },
    { id: USER2, protocol: "drive_local", label: "משתמש 2", account_hint: "user2", profile_id: "user2", is_private: true, is_admin: false, profile_status: "active", status: "ok", engine: "drive_local", app: "drive" },
    { id: GMAIL, protocol: "drive_google_oauth", label: "person30@example.com (drive)", account_hint: "person30@example.com", is_private: false, status: "ok", engine: "drive_google_oauth", app: "drive" },
  ];
  let activeConn = ADMIN;
  const profilesList = () => conns.filter((c) => c.protocol === "drive_local").map((c) => ({ id: c.profile_id, display_name: c.label, is_admin: !!c.is_admin,
    status: c.profile_status || "active", connection_id: c.id, created_at: iso(30 * D) }));
  const PROVIDERS = [
    { id: "local", name: "אחסון הלשכה", icon: "hard-drive", builtin: true, engine: "drive_local", private: true,
      description: "האחסון שמובנה בלשכה. עובד מיד, בלי חשבון חיצוני, והקבצים נשארים אצלכם.",
      auth_methods: [{ id: "profile", label: "פרופיל באחסון הלשכה", protocol: "drive_local", needs: [], recommended: true,
        can: "ניהול תיקיות וקבצים, העלאה, אשפה, חיפוש וקישורים ציבוריים — בנפרד לכל פרופיל." }] },
    { id: "google_drive", name: "Google Drive", icon: "cloud", engine: "drive_google_oauth", private: false,
      description: "החשבון שלך ב־Google. הקבצים נשארים ב־Drive; המערכת עובדת עליהם ישירות.",
      auth_methods: [
        { id: "oauth", label: "התחברות עם Google", protocol: "drive_google_oauth", needs: [], recommended: true,
          can: "צפייה, העלאה, העברה, שינוי שם ומחיקה בקבצים של החשבון שתאשר.",
          explain: "נפתח חלון של Google. אחרי האישור החשבון נבדק ונפתח כאן — גם ה־Drive וגם ה־Gmail שלו. אפשר לסגור את החלון בכל שלב: לא ייווצר חיבור.",
          start_url: "oauth/google/start", grant: "google-workspace-grant" },
        // the rows apps/drive-google/engine.py gives (/ops `providers`), word for word
        { id: "service_account", label: "שיתוף תיקייה עם הלשכה (חשבון שירות)", protocol: "drive_google_service_account",
          needs: ["service_account_json"], share: true,
          fields: [{ name: "service_account_json", label: "תוכן קובץ ה־JSON של חשבון השירות", type: "textarea" }],
          can: "רואה ועובד על התיקיות ששיתפו עם הכתובת שלו: צפייה, הורדה, העברה, שינוי שם ומחיקה. העלאת קבצים אינה אפשרית בחשבון שירות.",
          explain: "חשבון שירות הוא כתובת של הלשכה ב־Google. משתפים איתה ב־Google Drive את התיקיות שהלשכה צריכה (שיתוף › עורך), והן מופיעות כאן. את קובץ ה־JSON שלו מורידים פעם אחת ב־Google Cloud Console, במסך Service Accounts › Keys.",
          help_url: "https://cloud.google.com/iam/docs/service-account-overview" }] },
  ];
  /* `?sa=1`: the office already has its address at Google (a service account), and nothing was shared with it
     yet — the first «בדיקה» finds nothing; by the second the person «shared» a folder (the demo's stand-in for
     Google Drive's own share dialog), and it arrives. */
  const SA_ID = "drive_google_service_account-office";
  if (new URLSearchParams(location.search).get("sa") === "1") {
    conns.push({ id: SA_ID, protocol: "drive_google_service_account", label: "Google Drive", account_hint: "person34@example.com",
      is_private: false, status: "ok", engine: "drive_google_service_account", app: "drive" });
  }
  let saChecks = 0;
  const deadClient = new URLSearchParams(location.search).get("oauth") === "dead";
  /* the Google window comes back here (dev_server.py's return page) and says which account it made */
  window.__mockGoogleConnected = (email) => {
    const id = "drive_google_oauth-" + (++n).toString(36);
    conns.push({ id, protocol: "drive_google_oauth", label: email + " (drive)", account_hint: email, is_private: false, status: "ok", engine: "drive_google_oauth", app: "drive" });
    worlds[id] = googleWorld(email);
    return [{ id, protocol: "drive_google_oauth", account_hint: email, again: false }, { id: "mail_gmail_oauth-" + n, protocol: "mail_gmail_oauth", account_hint: email, again: false }];
  };

  /* a drive of its own for every other connection: what the screen asks of any drive, kept small */
  function googleWorld(email, sa) {
    const W = { folders: [], files: [], trashed: new Set(), rev: 1 };
    const fo = (name, parent, extra) => { const f = { id: id("g"), name, parent: parent || null, last: iso(Math.random() * 20 * D), owner: email, owner_id: email, mine: true, ...extra }; W.folders.push(f); return f; };
    const fi = (name, folder, size, mime, ago, extra) => { const f = { id: id("gf"), name, folder: folder || "", size, mime, created: iso(ago), starred: false,
      opened: ago < 3 * D ? iso(ago / 2) : "", md5: "", owner: email, owner_id: email, mine: true, link: "https://drive.google.com/file/d/demo/view", probed: true, ...extra }; W.files.push(f); return f; };
    if (sa) {
      const a = fo("חשבוניות לקוחות — משותף", null, { mine: false, owner: "office@example.com" });
      fi("חשבונית 1188.pdf", a.id, 22000, "application/pdf", 3 * D, { mine: false });
      return W;
    }
    const work = fo("עבודה"), clients = fo("לקוחות", work.id), photos = fo("Google Photos — ייצוא"), team = fo("כונן הצוות", null, { drive: true, mine: false, owner: "" });
    fo("פרויקט משותף מאלן", null, { shared: true, mine: false, owner: "alan@example.com" });
    fi("תוכנית עבודה 2026", work.id, 0, "application/vnd.google-apps.document", 2 * D, { thumb: true });
    fi("תקציב רבעוני", work.id, 0, "application/vnd.google-apps.spreadsheet", 5 * H, { thumb: true, starred: true });
    fi("מצגת ללקוח", clients.id, 0, "application/vnd.google-apps.presentation", 9 * D, { thumb: true });
    fi("הסכם — סמית׳.pdf", clients.id, 184000, "application/pdf", 12 * D);
    fi("IMG_20261101_0930.jpg", photos.id, 2400000, "image/jpeg", 4 * D, { meta: { w: 4032, h: 3024 }, taken: iso(4 * D) });
    fi("IMG_20261102_1415.jpg", photos.id, 2100000, "image/jpeg", 3 * D, { meta: { w: 3024, h: 4032 }, taken: iso(3 * D) });
    fi("נוהל צוות.docx", team.id, 32000, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 20 * D);
    fi("רשימת קניות.txt", "", 400, "text/plain", 6 * H);
    return W;
  }
  const worlds = { [USER2]: { folders: [], files: [], trashed: new Set(), rev: 1 }, [GMAIL]: googleWorld("person30@example.com"),
    [SA_ID]: { folders: [], files: [], trashed: new Set(), rev: 1 } };
  async function other(W, c, p, q, method, body) {
    if (c.id === SA_ID && p === "api/folders" && method === "GET" && ++saChecks >= 2 && !W.folders.length) {
      // the person shared a folder in Google Drive between the two checks (see `?sa=1` above)
      const f = { id: id("g"), name: "חוזים ושכירויות", parent: null, last: iso(0), owner: "office@example.com", owner_id: "office@example.com", mine: false };
      W.folders.push(f);
      W.files.push({ id: id("gf"), name: "חוזה שכירות — חנות 11.pdf", folder: f.id, size: 184000, mime: "application/pdf", created: iso(2 * D),
        starred: false, opened: "", md5: "", owner: "office@example.com", owner_id: "office@example.com", mine: false, link: "", probed: true });
      W.rev++;
    }
    const liveW = () => W.files.filter((f) => !W.trashed.has(f.id));
    const conn = { id: c.id, protocol: c.protocol, label: c.label, account_hint: c.account_hint, profile_id: c.profile_id || null, is_private: !!c.is_private,
      ...(c.protocol === "drive_local" ? LOCAL_CONN : c.protocol === "drive_google_service_account" ? SA_CONN : GOOGLE_CONN) };
    const pathW = (fid) => { const mm = Object.fromEntries(W.folders.map((f) => [f.id, f])), out = []; while (fid && mm[fid]) { out.unshift(mm[fid].name); fid = mm[fid].parent; } return "/" + out.join("/"); };
    let m;
    if (p === "api/folders" && method === "GET") return json({ folders: W.folders.map((f) => ({ ...f, count: liveW().filter((x) => x.folder === f.id).length })), connection: conn });
    if (p === "api/folders") { const f = { id: id("g"), name: body.name, parent: body.parent || null, last: iso(0), owner: c.account_hint, mine: true }; W.folders.push(f); W.rev++; return json({ folder: f }, 201); }
    if (p === "api/files") {
      if (q.get("trash")) return json({ files: W.files.filter((f) => W.trashed.has(f.id)), folders: [] });
      const v = q.get("view");
      if (v === "recent") return json({ files: liveW().filter((f) => f.opened).sort((a, b) => b.opened.localeCompare(a.opened)), folders: [] });
      if (v === "starred") return json({ files: liveW().filter((f) => f.starred), folders: [] });
      if (v === "shared") return json({ files: [], folders: W.folders.filter((f) => f.shared), view: "shared" });
      if (v === "added") return json({ files: [...liveW()].sort((a, b) => b.created.localeCompare(a.created)).slice(0, 30), folders: [] });
      return json({ files: liveW().filter((f) => (f.folder || "") === (q.get("folder") || "")), folders: [] });
    }
    if (p === "api/media") { const k = q.get("kind"), want = k === "audio" ? /^audio\// : k === "video" ? /^video\// : /^(image|video)\//; return json({ files: liveW().filter((f) => want.test(f.mime)) }); }
    if (p === "api/search") { const t = (q.get("q") || "").toLowerCase(); return json({ files: liveW().filter((f) => f.name.toLowerCase().includes(t)), folders: W.folders.filter((f) => f.name.toLowerCase().includes(t)) }); }
    if (p === "api/storage") return c.protocol === "drive_local" ? json({ files: liveW().length, used: liveW().reduce((s, f) => s + f.size, 0), trash_used: 0 })
      : json({ used: 6.4 * 2 ** 30, limit: 15 * 2 ** 30, percent: 42.67, trash_used: 120 * 2 ** 20 });
    if (p === "api/changes") return json({ rev: W.rev });
    if (p === "api/star") { const ids = body.ids || [body.id]; W.files.concat(W.folders).forEach((f) => ids.includes(f.id) && (f.starred = body.starred !== false)); W.rev++; return json({ ok: true }); }
    if (p === "api/rename") { const f = W.files.concat(W.folders).find((x) => x.id === body.id); if (f) f.name = body.name; W.rev++; return json({ ok: true }); }
    if (p === "api/move") { (body.ids || []).forEach((i) => { const f = W.files.find((x) => x.id === i); if (f) f.folder = body.to || ""; const d = W.folders.find((x) => x.id === i); if (d) d.parent = body.to || null; }); W.rev++; return json({ ok: true }); }
    if (p === "api/trash") { (body.ids || []).forEach((i) => (body.restore ? W.trashed.delete(i) : W.trashed.add(i))); W.rev++; return json({ ok: true, count: (body.ids || []).length }); }
    if (p === "api/delete") { (body.ids || []).forEach((i) => { const a = W.files.findIndex((x) => x.id === i); if (a >= 0) W.files.splice(a, 1); W.trashed.delete(i); }); W.rev++; return json({ ok: true }); }
    if ((m = /^api\/folder\/([^/]+)\/path$/.exec(p))) return json({ id: m[1], path: pathW(decodeURIComponent(m[1])) });
    if ((m = /^api\/file\/([^/]+)$/.exec(p))) { const f = W.files.find((x) => x.id === decodeURIComponent(m[1])); return f ? json({ file: { ...f, path: pathW(f.folder).replace(/\/$/, "") + "/" + f.name } }) : json({ error: "הקובץ אינו קיים" }, 404); }
    if ((m = /^api\/file\/([^/]+)\/(content|thumb|peaks)$/.exec(p))) {
      const f = W.files.find((x) => x.id === decodeURIComponent(m[1]));
      if (!f) return json({ error: "הקובץ אינו קיים" }, 404);
      if (m[2] === "peaks") return json({ error: "אין גל קול לקובץ הזה" }, 404);
      const b = await (/^image\//.test(f.mime) || f.thumb ? picture(320, f.mime.includes("presentation") ? 180 : 240, f.name.length, f.mime.includes("google-apps") ? "Google" : "")() : pdf()());
      return new Response(b, { status: 200, headers: { "Content-Type": b.type } });
    }
    if (p === "api/uploads" && method === "POST") { const u = { id: id("up"), size: body.size, name: body.name, mime: body.mime || "", folder: body.folder || "", got: 0, chunks: [], world: W }; uploads[u.id] = u; return json({ id: u.id, offset: 0, size: u.size }, 201); }
    if ((m = /^api\/uploads\/([^/]+)$/.exec(p))) {
      const u = uploads[m[1]]; if (!u) return json({ error: "ההעלאה אינה קיימת" }, 404);
      if (method === "PATCH") { u.got += init_body_size(); if (u.got >= u.size) { u.state = "done"; const f = { id: id("gf"), name: u.name, folder: u.folder, size: u.size, mime: u.mime, created: iso(0), owner: c.account_hint, mine: true, probed: true };
        W.files.push(f); u.file = f; W.rev++; return json({ state: "done", file: f, offset: u.got }, 202); } return new Response(null, { status: 204, headers: { "Upload-Offset": String(u.got) } }); }
      return json({ id: u.id, offset: u.got, size: u.size, state: u.state || "receiving", file: u.file });
    }
    if (p === "extensions") return json({ extensions: [] });
    return json({ error: "mock: " + p }, 404);
  }
  let init_body_size = () => 0;

  window.fetch = async function (input, init) {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!url.pathname.startsWith(BASE) || url.pathname.startsWith(BASE + "vendor/") || /\.(js|css|mjs|html)$/.test(url.pathname)) return realFetch(input, init);
    const p = url.pathname.slice(BASE.length), q = url.searchParams, method = (init && init.method) || "GET";
    const body = init && init.body && typeof init.body === "string" ? JSON.parse(init.body) : {};
    await new Promise((r) => setTimeout(r, 120 + Math.random() * 180));
    let m;
    /* the account plane */
    if (p === "connections" && method === "GET") return json({ connections: conns, active: activeConn, bound: activeConn,
      acting_profile: { id: "admin", display_name: "מנהל", is_admin: true, status: "active", instance_id: ADMIN } });
    if (p === "connections" && method === "POST") {
      if (body.protocol === "drive_google_service_account") {
        let sa = {}; try { sa = JSON.parse((body.secret || {}).service_account_json || ""); } catch (e) { return json({ error: "ה־JSON של חשבון השירות אינו תקין" }, 400); }
        if (sa.type !== "service_account" || !sa.client_email || !sa.private_key) return json({ error: "קובץ JSON אינו חשבון שירות תקין — חסרים שדות type / client_email / private_key" }, 400);
        const cid = "drive_google_service_account-" + (++n).toString(36);
        conns.push({ id: cid, protocol: body.protocol, label: body.label, account_hint: sa.client_email, is_private: false, status: "ok", engine: body.protocol, app: "drive" });
        worlds[cid] = googleWorld(sa.client_email, true);
        return json({ id: cid, protocol: body.protocol });
      }
      return json({ error: "mock: protocol " + body.protocol }, 400);
    }
    if (p === "connections/select") { activeConn = body.id; return json({ ok: true, active: body.id }); }
    if ((m = /^connections\/([^/]+)\/probe$/.exec(p))) { const c = conns.find((x) => x.id === decodeURIComponent(m[1])); return c ? json({ ok: true, reason: null, id: c.id, account_hint: c.account_hint }) : json({ error: "unknown" }, 404); }
    if ((m = /^connections\/([^/]+)$/.exec(p)) && method === "DELETE") {
      const i = conns.findIndex((x) => x.id === decodeURIComponent(m[1]));
      if (i < 0) return json({ error: "unknown" }, 404);
      if (conns[i].protocol === "drive_local") return json({ error: "זהו פרופיל של המנוע המקומי — הסרה נעשית במסך ניהול הפרופילים" }, 400);
      conns.splice(i, 1); return json({ ok: true });
    }
    if (p === "providers") return json({ providers: PROVIDERS });
    if (p === "engine/profiles" && method === "GET") return json({ profiles: profilesList(), acting_as: "admin" });
    if (p === "engine/profiles" && method === "POST") {
      if (conns.some((c) => c.profile_id === body.id)) return json({ error: "פרופיל בשם הזה כבר קיים" }, 409);
      const cid = "drive_local-" + body.id;
      conns.push({ id: cid, protocol: "drive_local", label: body.display_name || body.id, account_hint: body.id, profile_id: body.id, is_private: true, is_admin: !!body.admin, profile_status: "active", status: "ok", engine: "drive_local", app: "drive" });
      worlds[cid] = { folders: [], files: [], trashed: new Set(), rev: 1 };
      return json({ ok: true, id: body.id, key: "dpk_" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2), connection_id: cid }, 201);
    }
    if ((m = /^engine\/profiles\/([^/]+)(\/key)?$/.exec(p))) {
      const c = conns.find((x) => x.profile_id === decodeURIComponent(m[1]));
      if (!c) return json({ error: "unknown profile" }, 404);
      if (m[2]) return json({ ok: true, key: "dpk_" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2) });
      if (method === "PATCH") { if (body.display_name) c.label = body.display_name; if (body.status) c.profile_status = body.status; return json({ ok: true }); }
      if (method === "DELETE") { if (c.is_admin && conns.filter((x) => x.is_admin).length < 2) return json({ error: "אי אפשר להסיר את המנהל האחרון" }, 409); conns.splice(conns.indexOf(c), 1); return json({ ok: true }); }
    }
    if (p === "oauth/google/start") {
      // connections' answer word for word (its _REFUSAL_HE / _REFUSAL_HELP, DGO-1634)
      if (deadClient) return json({ error: "ההתחברות עם Google עוד לא פתוחה בלשכה הזו: מזהה ההתחברות שלה (OAuth client) נמחק אצל Google. מי שמנהל את Google Cloud של העסק יוצר מזהה חדש, עם כתובת החזרה https://connections.staging.digital-office.co.il/oauth/relay", provider_error: "invalid_client", help_url: "https://console.cloud.google.com/apis/credentials" }, 409);
      return json({ ok: true, authorize_url: BASE + "__mock-google?ret=" + encodeURIComponent(q.get("ret") || ""), bind: "mock-bind" });
    }
    /* another drive than the office storage's admin: its own small world */
    const cid = q.get("connection_id");
    if (cid && cid !== ADMIN) {
      const c = conns.find((x) => x.id === cid);
      if (!c) return json({ error: `unknown connection '${cid}'` }, 404);
      init_body_size = () => (init && init.body && init.body.size) || 0;
      return other(worlds[cid] || (worlds[cid] = { folders: [], files: [], trashed: new Set(), rev: 1 }), c, p, q, method, body);
    }
    if (p === "api/folders" && method === "GET") return json({ folders: counts(), connection: { id: ADMIN, protocol: "drive_local", label: "מנהל", account_hint: "admin", profile_id: "admin", is_private: true, ...LOCAL_CONN } });
    if (p === "api/folders") { const f = { id: id("ld"), name: body.name, parent: body.parent || null, last: iso(0), owner: "אני", mine: true }; folders.push(f); bump(); return json({ folder: f }, 201); }
    if (p === "api/files") {
      if (q.get("trash")) return json({ files: files.filter((f) => trashed.has(f.id)), folders: folders.filter((f) => trashedFolders.has(f.id)) });
      const v = q.get("view");
      if (v === "recent") return json({ files: live().filter((f) => f.opened).sort((a, b) => b.opened.localeCompare(a.opened)) });
      if (v === "starred") return json({ files: live().filter((f) => f.starred) });
      if (v === "added") return json({ files: [...live()].sort((a, b) => b.created.localeCompare(a.created)).slice(0, Number(q.get("limit") || 30)) });
      return json({ files: live().filter((f) => (f.folder || "") === (q.get("folder") || "")) });
    }
    if (p === "api/media") {
      const k = q.get("kind"), want = k === "audio" ? /^audio\// : k === "video" ? /^video\// : /^(image|video)\//;
      return json({ files: live().filter((f) => want.test(f.mime)) });
    }
    if (p === "api/search") { const t = (q.get("q") || "").toLowerCase(); return json({ files: live().filter((f) => f.name.toLowerCase().includes(t)), folders: counts().filter((f) => f.name.toLowerCase().includes(t)) }); }
    if (p === "api/storage") { const l = live(), t = files.filter((f) => trashed.has(f.id)); return json({ files: l.length, used: l.reduce((s, f) => s + f.size, 0), trash_files: t.length, trash_used: t.reduce((s, f) => s + f.size, 0), limit: 20 * 2 ** 30, percent: 4.2 }); }
    if (p === "api/changes") return json({ rev });
    if (p === "extensions") return json({ extensions: [{ app: "office", slot: "open-with", spec: { label: "מסמכים", exts: ["docx", "doc", "xlsx", "pptx", "odt"], url: "#office-demo", mode: "edit" } }] });
    if (p === "api/star") { const ids = body.ids || [body.id]; files.concat(folders).forEach((f) => ids.includes(f.id) && (f.starred = body.starred !== false)); bump(); return json({ ok: true }); }
    if (p === "api/rename") { const f = files.concat(folders).find((x) => x.id === body.id); if (f) f.name = body.name; bump(); return json({ ok: true }); }
    if (p === "api/move") { (body.ids || []).forEach((i) => { const f = files.find((x) => x.id === i); if (f) f.folder = body.to || ""; const d = folders.find((x) => x.id === i); if (d) d.parent = body.to || null; }); bump(); return json({ ok: true, moved: body.ids.length }); }
    if (p === "api/trash") { (body.ids || []).forEach((i) => { const isF = folders.some((x) => x.id === i); if (body.restore) { trashed.delete(i); trashedFolders.delete(i); } else (isF ? trashedFolders : trashed).add(i); }); bump(); return json({ ok: true, count: body.ids.length }); }
    if (p === "api/delete") { (body.ids || []).forEach((i) => { const a = files.findIndex((x) => x.id === i); if (a >= 0) files.splice(a, 1); const b = folders.findIndex((x) => x.id === i); if (b >= 0) folders.splice(b, 1); trashed.delete(i); trashedFolders.delete(i); }); bump(); return json({ ok: true, deleted: body.ids.length }); }
    if ((m = /^api\/folder\/([^/]+)\/path$/.exec(p))) return json({ id: m[1], path: pathOf(decodeURIComponent(m[1])) });
    if ((m = /^api\/file\/([^/]+)$/.exec(p))) { const f = files.find((x) => x.id === decodeURIComponent(m[1])); return f ? json({ file: { ...f, path: pathOf(f.folder).replace(/\/$/, "") + "/" + f.name } }) : json({ error: "הקובץ אינו קיים" }, 404); }
    if ((m = /^api\/file\/([^/]+)\/(content|thumb|peaks)$/.exec(p))) {
      const f = files.find((x) => x.id === decodeURIComponent(m[1]));
      if (!f) return json({ error: "הקובץ אינו קיים" }, 404);
      if (m[2] === "peaks") return f.mime.startsWith("audio") ? json({ peaks: peaks(f.id) }) : json({ error: "no" }, 404);
      if (m[2] === "content") f.opened = iso(0);
      if (m[2] === "thumb" && !f.mime.startsWith("image")) return json({ error: "no thumb" }, 404);
      const make = blobs[f.id]; if (!make) return json({ error: "אין תוכן בהדגמה" }, 404);
      const b = await make();
      return new Response(b, { status: 200, headers: { "Content-Type": b.type || f.mime } });
    }
    if (p === "api/fs" && method === "GET") {         // the path API: a folder by its path, and what is in it
      const segs = (q.get("path") || "/").split("/").filter(Boolean);
      let fid = "";
      for (const s of segs) { const f = folders.find((x) => (x.parent || "") === fid && x.name === s); if (!f) return json({ error: "אין כלום בנתיב " + q.get("path") }, 404); fid = f.id; }
      const fo = folders.find((x) => x.id === fid);
      return json({ kind: "folder", folder: fo ? { ...fo, path: pathOf(fid) } : null, path: pathOf(fid),
        folders: folders.filter((x) => (x.parent || "") === fid && !trashedFolders.has(x.id)),
        files: files.filter((x) => (x.folder || "") === fid && !trashed.has(x.id)) });
    }
    if (p === "api/uploads" && method === "POST") {
      let folder = body.folder || "";
      if (body.path) {                                  // a path is made on demand; an app may mark its own folder
        const segs = String(body.path).split("/").filter(Boolean);
        folder = "";
        segs.forEach((s, i) => { let f = folders.find((x) => (x.parent || "") === folder && x.name === s);
          if (!f) { f = { id: id("ld"), name: s, parent: folder || null, last: iso(0), owner: "אני", mine: true }; folders.push(f); }
          if (i === segs.length - 1 && body.system === s && !f.system) f.system = s;
          folder = f.id; });
      }
      const u = { id: id("up"), size: body.size, name: body.name, mime: body.mime || "", folder, got: 0, chunks: [] };
      uploads[u.id] = u; return json({ id: u.id, offset: 0, size: u.size }, 201);
    }
    if ((m = /^api\/uploads\/([^/]+)$/.exec(p))) {
      const u = uploads[m[1]]; if (!u) return json({ error: "ההעלאה אינה קיימת" }, 404);
      if (method === "PATCH") { const b = init.body; u.chunks.push(b); u.got += b.size; await new Promise((r) => setTimeout(r, 200)); if (u.got >= u.size) { u.state = "done"; const f = add(u.name, u.folder, u.size, u.mime || b.type || "", 0, null, () => new Blob(u.chunks, { type: u.mime || b.type || "" })); u.file = f; bump(); return json({ state: "done", file: f, offset: u.got }, 202); }
        return new Response(null, { status: 204, headers: { "Upload-Offset": String(u.got) } }); }
      if (method === "DELETE") { delete uploads[m[1]]; return new Response(null, { status: 204 }); }
      return json({ id: u.id, offset: u.got, size: u.size, state: u.state || (u.got >= u.size ? "complete" : "receiving"), file: u.file });
    }
    return json({ error: "mock: " + p }, 404);
  };

  /* an <img>, <audio> or <video> loads its src by itself, not through fetch — so the stand-in
     answers those too: the bytes come from the mock, the element gets an object URL */
  function hook(proto) {
    const d = Object.getOwnPropertyDescriptor(proto, "src");
    Object.defineProperty(proto, "src", { configurable: true, enumerable: true,
      get() { return d.get.call(this); },
      set(v) {
        const u = new URL(String(v), location.href);
        if (!u.pathname.startsWith(BASE + "api/file/")) return d.set.call(this, v);
        const el = this;
        window.fetch(u.pathname + u.search).then((r) => (r.ok ? r.blob() : Promise.reject(r.status)))
          .then((b) => d.set.call(el, URL.createObjectURL(b))).catch(() => d.set.call(el, "data:,"));
      } });
  }
  hook(HTMLImageElement.prototype);
  hook(HTMLMediaElement.prototype);
})();
