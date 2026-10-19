const fs=require('fs');
const dir=__dirname+'/frag';
fs.mkdirSync(dir,{recursive:true});

const IC={
 dash:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 doc:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
 folder:'<path d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
 mail:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
 inbox:'<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5 5h14l3 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/>',
 chat:'<path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7a8.5 8.5 0 1 1 16.1-3.8z"/>',
 activity:'<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
 bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
 server:'<rect x="2" y="3" width="20" height="6" rx="1"/><rect x="2" y="9" width="20" height="6" rx="1"/><rect x="2" y="15" width="20" height="6" rx="1"/>',
 grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
 key:'<circle cx="8" cy="15" r="4"/><path d="m10.85 12.15 8.15-8.15 2 2-2 2 2 2-3 3-2-2-2 2"/>',
 gear:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-2.82 1.17V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 8 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 8.6a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09A1.65 1.65 0 0 0 15 4.6a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9z"/>',
};
const svg=(p)=>`<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${p}</svg>`;
const NAV=[
 ['sec','ראשי'],
 ['dashboard','לוח בקרה',IC.dash],
 ['sec','עסק'],
 ['mydocs-dash','מסמכים שלי',IC.doc],
 ['drive-root','דרייב',IC.folder],
 ['mail-inbox','מייל',IC.mail],
 ['indox-root','מסמכים נכנסים',IC.inbox],
 ['wadmin-dashboard','בוט ווצאפ',IC.chat],
 ['sec','תשתית'],
 ['kabil','כל‑מקביל',IC.activity],
 ['notifications','התראות',IC.bell],
 ['machine','מכונה',IC.server],
 ['apps','אפליקציות',IC.grid],
 ['feature-validation','אימות מערכת',IC.shield],
 ['sec','הגדרות'],
 ['connections-auth','חיבורים ומפתחות',IC.key],
 ['console-install','מסך התקנה',IC.gear],
];
function sidebar(active){
  let h='<aside class="hm-side"><div class="hm-brand"><div class="logo">מ</div><div class="bt"><b>המרכז</b><span>מערכת ניהול העסק</span></div></div><nav class="hm-nav">';
  for(const it of NAV){
    if(it[0]==='sec'){h+=`<div class="hm-sec">${it[1]}</div>`;continue;}
    const on=it[0]===active?' class="on"':'';
    h+=`<a data-nav="${it[0]}"${on}><span>${it[1]}</span>${svg(it[2])}</a>`;
  }
  h+='</nav><div class="hm-foot"><small>מחובר/ת</small><b>authentik Default Admin</b></div></aside>';
  return h;
}
function top(title,subtitle){
  return `<div class="hm-top"><div class="grp"><div class="hm-title">${title}</div><button class="hm-burger">☰</button></div><div class="grp"><div class="hm-search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4-4"/></svg><span>חיפוש</span><span class="kbd">Ctrl K</span></div></div><div class="grp left">${subtitle?`<span style="color:var(--muted);font-size:13px">${subtitle}</span>`:''}<div class="pill-amber">⚙ 7 שלבי התקנה</div></div></div>`;
}
function screen(id,active,title,subtitle,body,{biz=''}={}){
  const s=`<section class="screen" data-screen="${id}"><div class="viewport">${sidebar(active)}<main class="hm-main">${top(title,subtitle)}<div class="hm-scroll">${biz}<div class="hm-body">${body}</div></div></main></div></section>`;
  fs.writeFileSync(dir+'/'+id+'.html',s);
}

/* ===== business secondary tab bar ===== */
function bizbar(active){
  const tabs=[['mydocs-dash','לוח בקרה'],['mydocs-docs','מסמכים'],['mydocs-customers','לקוחות'],['mydocs-items','פריטים'],['mydocs-settings','הגדרות עסק']];
  let t=tabs.map(([id,n])=>`<a data-nav="${id}"${id===active?' class="on"':''}><span class="dot">▪</span>${n}</a>`).join('');
  return `<div class="biz-bar"><button class="btn btn-primary">+ מסמך חדש</button><div class="biz-tabs">${t}</div></div>`;
}

/* ===================== DASHBOARD ===================== */
screen('dashboard','dashboard','לוח בקרה','',`
<div class="hero"><h2>ברוך/ה הבא/ה, authentik Default Admin</h2><p>כל התשתית של העסק במקום אחד — מסמכים, דואר, אוטומציה, מפתחות גישה והגדרות.</p></div>
<div class="stat-row" style="grid-template-columns:repeat(5,1fr)">
  <div class="stat acc-a"><div class="n a">7</div><div class="l">שלבי התקנה שנותרו</div></div>
  <div class="stat acc-g"><div class="n g">30/51</div><div class="l">חיבורים תקינים</div></div>
  <div class="stat acc-a"><div class="n a">7</div><div class="l">דורשים טיפול</div></div>
  <div class="stat"><div class="n">7</div><div class="l">משימות פעילות</div></div>
  <div class="stat"><div class="n">295</div><div class="l">הודעות דואר</div></div>
</div>
<div class="sec-lab">ראשי</div>
<div class="tiles"><div class="tile" data-nav="dashboard" style="grid-column:5"><div class="ti">${svg(IC.dash)}</div><b>לוח בקרה</b><span>מבט‑על על כל המערכת</span></div></div>
<div class="sec-lab">עסק</div>
<div class="tiles">
  <div class="tile" data-nav="wadmin-dashboard"><div class="ti">${svg(IC.chat)}</div><b>בוט ווצאפ</b><span>ניהול ווצאפ ומסמכים</span></div>
  <div class="tile" data-nav="indox-root"><div class="ti">${svg(IC.inbox)}</div><b>מסמכים נכנסים</b><span>עיבוד מסמכים אוטומטי (INDOX)</span></div>
  <div class="tile" data-nav="mail-inbox"><div class="ti">${svg(IC.mail)}</div><b>מייל</b><span>תיבת דואר עסקית</span></div>
  <div class="tile" data-nav="drive-root"><div class="ti">${svg(IC.folder)}</div><b>דרייב</b><span>קבצים ומסמכים</span></div>
  <div class="tile" data-nav="mydocs-dash"><div class="ti">${svg(IC.doc)}</div><b>מסמכים שלי</b><span>ניהול מסמכים עסקיים</span></div>
</div>
<div class="sec-lab">תשתית</div>
<div class="tiles">
  <div class="tile" data-nav="feature-validation"><div class="ti">${svg(IC.shield)}</div><b>אימות מערכת</b><span>חבילת בדיקות מערכת</span></div>
  <div class="tile" data-nav="apps"><div class="ti">${svg(IC.grid)}</div><b>אפליקציות</b><span>כל האפליקציות והכלים</span></div>
  <div class="tile" data-nav="machine"><div class="ti">${svg(IC.server)}</div><b>מכונה</b><span>מדדי מארח ו‑Docker</span></div>
  <div class="tile" data-nav="notifications"><div class="ti">${svg(IC.bell)}</div><b>התראות</b><span>מרכז התראות</span></div>
  <div class="tile" data-nav="kabil"><div class="ti">${svg(IC.activity)}</div><b>כל‑מקביל</b><span>ציר‑זמן מקביליות</span></div>
</div>
<div class="sec-lab">הגדרות</div>
<div class="tiles">
  <div class="tile" data-nav="console-install"><div class="ti">${svg(IC.gear)}</div><b>מסך התקנה</b><span>הגדרות בסיסיות וחיבור</span></div>
  <div class="tile" data-nav="connections-auth"><div class="ti">${svg(IC.key)}</div><b>חיבורים ומפתחות</b><span>ניהול מפתחות גישה</span></div>
</div>
`);

/* ===================== APPS ===================== */
screen('apps','apps','אפליקציות','כל האפליקציות והכלים של המערכת',`
<div class="hero"><h2>אפליקציות</h2><p>כל האפליקציות של הפלטפורמה וכלי הניהול — במקום אחד.</p></div>
<div class="sec-lab">האפליקציות שלי</div>
<div class="tiles">
  <div class="tile" data-nav="wadmin-dashboard"><div class="ti">${svg(IC.chat)}</div><b>בוט ווצאפ</b><span>ניהול ווצאפ ומסמכים</span></div>
  <div class="tile" data-nav="indox-root"><div class="ti">${svg(IC.inbox)}</div><b>מסמכים נכנסים</b><span>עיבוד מסמכים אוטומטי (INDOX)</span></div>
  <div class="tile" data-nav="mail-inbox"><div class="ti">${svg(IC.mail)}</div><b>מייל</b><span>תיבת דואר עסקית</span></div>
  <div class="tile" data-nav="drive-root"><div class="ti">${svg(IC.folder)}</div><b>דרייב</b><span>קבצים ומסמכים</span></div>
  <div class="tile" data-nav="mydocs-dash"><div class="ti">${svg(IC.doc)}</div><b>מסמכים שלי</b><span>ניהול מסמכים עסקיים</span></div>
  <div class="tile" data-nav="connections-auth"><div class="ti">${svg(IC.key)}</div><b>חיבורים ומפתחות</b><span>ניהול מפתחות גישה וחיבורים</span></div>
  <div class="tile" data-nav="feature-validation"><div class="ti">${svg(IC.shield)}</div><b>אימות מערכת</b><span>חבילת בדיקות מערכת</span></div>
  <div class="tile" data-nav="machine"><div class="ti">${svg(IC.server)}</div><b>מכונה</b><span>מדדי מארח ו‑Docker</span></div>
  <div class="tile" data-nav="notifications"><div class="ti">${svg(IC.bell)}</div><b>התראות</b><span>מרכז התראות</span></div>
  <div class="tile" data-nav="kabil"><div class="ti">${svg(IC.activity)}</div><b>כל‑מקביל</b><span>ציר‑זמן מקביליות</span></div>
  <div class="tile" data-nav="console-install"><div class="ti">${svg(IC.gear)}</div><b>מסך התקנה</b><span>הגדרות בסיסיות וחיבור מערכות חיצוניות</span></div>
</div>
<div class="sec-lab">כלים ומערכת</div>
<div class="tiles">
  <div class="tile ext" data-nav="authentik-admin"><div class="ti"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg></div><b>↗ Authentik</b><span>זהויות, הרשאות ו‑SSO</span></div>
  <div class="tile ext" data-nav="portainer-dashboard"><div class="ti"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2 2 7l10 5 10-5z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/></svg></div><b>↗ Portainer</b><span>ניהול קונטיינרים ותשתית</span></div>
  <div class="tile ext" data-nav="supabase"><div class="ti">${svg(IC.server)}</div><b>↗ Supabase Studio</b><span>מסד הנתונים והטבלאות</span></div>
  <div class="tile ext" data-nav="glitchtip"><div class="ti"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/></svg></div><b>↗ GlitchTip</b><span>מעקב שגיאות ואירועים</span></div>
  <div class="tile ext" data-nav="n8n-workflows"><div class="ti">${svg(IC.activity)}</div><b>↗ n8n</b><span>מנוע האוטומציה והתהליכים</span></div>
  <div class="tile ext" data-nav="redis"><div class="ti">${svg(IC.server)}</div><b>↗ RedisInsight</b><span>מטמון ותורים</span></div>
</div>
`);

/* ===================== NOTIFICATIONS ===================== */
screen('notifications','notifications','התראות','מרכז התראות',`
<div class="page-head"><div><h1>🔔 התראות</h1><div class="sub">מרכז התראות מאוחד — שגיאות, אירועים ומצב המערכת מכל האפליקציות.</div></div>
<div class="row"><span class="live"><span class="dt"></span>חי</span><button class="btn btn-sm">✓ סמן הכל כנקרא</button><button class="btn btn-sm">נקה נקראו</button></div></div>
<div class="stat-row" style="grid-template-columns:repeat(4,1fr)">
  <div class="stat"><div class="n">0</div><div class="l">סה״כ התראות</div></div>
  <div class="stat"><div class="n">0</div><div class="l">לא נקראו</div></div>
  <div class="stat"><div class="n r">0</div><div class="l">שגיאות</div></div>
  <div class="stat"><div class="n a">0</div><div class="l">אזהרות</div></div>
</div>
<div class="segs" style="justify-content:flex-end;margin-bottom:16px"><span class="seg">לא נקראו <span class="c">0</span></span><span class="seg on">הכל <span class="c">0</span></span><span class="seg">שגיאות <span class="c">0</span></span><span class="seg">אזהרות <span class="c">0</span></span><span class="seg">מידע <span class="c">0</span></span></div>
<div class="card" style="text-align:center;padding:48px"><div style="font-size:44px">🔔</div><div style="font-weight:800;font-size:18px;margin-top:6px">אין התראות</div><div class="muted" style="margin-top:6px">כשתתקבל התראה חדשה (שגיאה, אירוע מערכת) היא תופיע כאן.</div></div>
`);

/* ===================== MYDOCS: DASH ===================== */
screen('mydocs-dash','mydocs-dash','מסמכים שלי','ניהול מסמכים עסקיים',`
<div class="page-head"><div><h1>לוח בקרה</h1></div><div class="page-meta">בינה פתרונות בע"מ · עוסק מורשה · ח.פ 514789234</div></div>
<div class="stat-row" style="grid-template-columns:repeat(5,1fr)">
  <div class="stat stat-big"><div class="l">סך התקבולים</div><div class="n">0.00₪</div><div class="foot">השנה 0.00₪ · החודש 0.00₪</div></div>
  <div class="stat"><div class="n">0</div><div class="l">קבלות</div></div>
  <div class="stat"><div class="n">0.00₪</div><div class="l">קבלה ממוצעת</div></div>
  <div class="stat"><div class="n">0</div><div class="l">לקוחות</div></div>
  <div class="stat"><div class="n">9</div><div class="l">סה״כ מסמכים</div></div>
</div>
<div class="card" style="margin-bottom:20px"><div class="spread"><h3 style="margin:0">תקבולים לפי חודש</h3><span class="muted" style="font-size:12px">12 חודשים</span></div>
<div style="display:flex;align-items:flex-end;gap:14px;height:150px;margin-top:20px;padding:0 8px">${['אוג','ספט','אוק','נוב','דצמ','ינו','פבר','מרץ','אפר','מאי','יונ','יול'].map(m=>`<div style="flex:1;text-align:center"><div style="height:2px;background:var(--green);border-radius:2px"></div><div class="muted" style="font-size:11px;margin-top:8px">${m}</div></div>`).join('')}</div></div>
<h3 style="text-align:right;margin:0 0 12px">מסמכים אחרונים</h3>
<div class="tbl-wrap"><table class="tbl"><thead><tr><th>מספר</th><th>סוג</th><th>לקוח</th><th>סכום</th><th>סטטוס</th></tr></thead><tbody>
${[['—','חשבונית מס','ישראל קרטון','25,488.00'],['—','הצעת מחיר','אגן שיווק','9,900.00'],['—','הזמנת רכש','פוליראן תעשיות','8,500.00'],['—','חשבונית מס','סבח סוכנויות בע"מ','14,160.00'],['—','חשבונית מס','מ.ש. הכהנים בע"מ','8,496.00']].map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>₪${r[3]}</td><td><span class="badge badge-gray">טיוטה</span></td></tr>`).join('')}
</tbody></table></div>
`,{biz:bizbar('mydocs-dash')});

/* ===================== MYDOCS: DOCS ===================== */
screen('mydocs-docs','mydocs-dash','מסמכים שלי','ניהול מסמכים עסקיים',`
<div class="page-head"><div><h1>מסמכים</h1></div><div class="page-meta">בינה פתרונות בע"מ · עוסק מורשה · ח.פ 514789234</div></div>
<div class="tbl-wrap" style="padding:16px">
<div class="spread" style="margin-bottom:14px"><div class="segs"><span class="seg">בוטל <span class="c">0</span></span><span class="seg">שולם <span class="c">0</span></span><span class="seg">נשלח <span class="c">0</span></span><span class="seg">הונפק <span class="c">0</span></span><span class="seg">טיוטה <span class="c">9</span></span><span class="seg on">הכל <span class="c">9</span></span></div></div>
<div class="spread" style="margin-bottom:12px"><div class="row"><button class="btn btn-sm">ייצוא</button><button class="btn btn-sm">צפוף</button></div><div class="searchbox"><span>חיפוש לפי מספר, לקוח…</span><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4-4"/></svg></div></div>
<table class="tbl"><thead><tr><th class="idx">#</th><th>מספר</th><th>סוג</th><th>לקוח</th><th>סכום</th><th>תאריך</th><th>סטטוס</th></tr></thead><tbody>
${[[1,'—','חשבונית מס','ישראל קרטון','25,488.00','14/05/2026'],[2,'—','הצעת מחיר','אגן שיווק','9,900.00','21/05/2026'],[3,'—','הזמנת רכש','פוליראן תעשיות','8,500.00','28/05/2026'],[4,'—','חשבונית מס','סבח סוכנויות בע"מ','14,160.00','03/06/2026'],[5,'—','חשבונית מס','מ.ש. הכהנים בע"מ','8,496.00','12/06/2026'],[6,'—','חשבונית מס','ישראל קרטון','25,488.00','14/05/2026'],[7,'—','הצעת מחיר','אגן שיווק','9,900.00','21/05/2026'],[8,'—','חשבונית מס','סבח סוכנויות בע"מ','14,160.00','03/06/2026'],[9,'—','חשבונית מס','מ.ש. הכהנים בע"מ','8,496.00','12/06/2026']].map(r=>`<tr><td class="idx">${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td><td>₪${r[4]}</td><td>${r[5]}</td><td><span class="badge badge-gray">טיוטה</span></td></tr>`).join('')}
</tbody></table></div>
`,{biz:bizbar('mydocs-docs')});

/* ===================== MYDOCS: CUSTOMERS ===================== */
screen('mydocs-customers','mydocs-dash','מסמכים שלי','ניהול מסמכים עסקיים',`
<div class="page-head"><div><h1>לקוחות</h1></div><div class="page-meta">בינה פתרונות בע"מ · עוסק מורשה · ח.פ 514789234</div></div>
<button class="btn btn-primary" style="margin-bottom:14px">+ לקוח</button>
<div class="tbl-wrap" style="padding:16px">
<div class="spread" style="margin-bottom:12px"><div class="row"><button class="btn btn-sm">ייצוא</button><button class="btn btn-sm">צפוף</button></div><div class="searchbox"><span>חיפוש לקוח…</span><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4-4"/></svg></div></div>
<table class="tbl"><thead><tr><th class="idx">#</th><th></th><th>שם</th><th>ח.פ</th><th>עיר</th><th>דוא"ל</th><th>טלפון</th></tr></thead><tbody>
${[[1,'אגן שיווק','511301129','פתח תקווה','person117@example.com','03-9312244'],[2,'ישראל קרטון','512093170','חיפה','person118@example.com','04-8112255'],[3,'מ.ש. הכהנים בע"מ','511020471','מודיעין','person119@example.com','08-9741234'],[4,'סבח סוכנויות בע"מ','570043745','משמר השבעה','person120@example.com','03-9021188'],[5,'פוליראן תעשיות','513498345','אשדוד','person121@example.com','08-8563377']].map(r=>`<tr><td class="idx">${r[0]}</td><td><span class="muted">✕</span></td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td><td>${r[4]}</td><td>${r[5]}</td></tr>`).join('')}
</tbody></table>
<div class="spread" style="margin-top:14px;color:var(--muted);font-size:12px"><span>רשומות 5</span><span>גלילה חופשית — כל הרשומות זמינות</span></div></div>
`,{biz:bizbar('mydocs-customers')});

/* ===================== INDOX ROOT (dashboard) ===================== */
const indoxTabs=(active)=>{const t=[['indox-root','לוח בקרה'],['indox-docs','מסמכים'],['indox-sync','סנכרון'],['indox-settings','הגדרות'],['indox-tests','בדיקות'],['indox-extraction','חילוץ מסמכים']];return `<div class="biz-bar" style="justify-content:flex-start;gap:22px"><div class="biz-tabs" style="border:none">${t.map(([id,n])=>`<a data-nav="${id}"${id===active?' style="color:#12241d;border-bottom:2px solid #12241d;border-radius:0"':''}>${n}</a>`).join('')}</div><span class="muted" style="margin-inline-start:auto;font-size:13px">akadmin</span></div>`;};
screen('indox-root','indox-root','מסמכים נכנסים','עיבוד מסמכים אוטומטי (INDOX)',`
<div class="page-head"><div><h1>לוח בקרה</h1><div class="sub">תמונת מצב חיה של המסמכים הנכנסים — סטטוס, סוגים, חברות וציון חילוץ.</div></div>
<div class="row"><span class="live"><span class="dt"></span>חי</span><span class="muted" style="font-size:12px">עודכן 22:56:10</span></div></div>
<div class="stat-row" style="grid-template-columns:repeat(6,1fr)">
  <div class="stat"><div class="n">5</div><div class="l">סה״כ מסמכים</div></div>
  <div class="stat"><div class="n">0</div><div class="l">הושלמו<br><span class="muted" style="font-size:11px">0% מהמסמכים</span></div></div>
  <div class="stat"><div class="n a">5</div><div class="l">דורשים טיפול</div></div>
  <div class="stat"><div class="n">0</div><div class="l">נכשלו</div></div>
  <div class="stat acc-b"><div class="n b">10</div><div class="l">חברות</div></div>
  <div class="stat"><div class="n a">0%</div><div class="l">ציון חילוץ</div></div>
</div>
<div class="g2" style="margin-bottom:18px">
  <div class="card"><h3>בריאות הצינור — לפי סטטוס</h3>
    <div class="row" style="justify-content:flex-end;gap:14px;font-size:12px;margin-bottom:10px"><span>● הושלמו 0</span><span style="color:var(--red)">● נכשלו 0</span><span style="color:var(--gold)">● דורשים טיפול 5</span><span style="color:var(--blue)">● אחר 0</span></div>
    <div class="bar-line"><div class="bar-track" style="height:14px"><div class="bar-fill" style="width:100%;background:var(--gold)"></div></div></div>
    <div class="bar-line"><span class="bar-num">5</span><div class="bar-track" style="height:14px"><div class="bar-fill" style="width:88%;background:var(--gold)"></div></div><div class="lab">(ריק)</div></div>
  </div>
  <div class="card"><h3>ציון חילוץ — לפי שדה</h3><div class="spread"><div><div style="font-size:40px;font-weight:800;color:var(--green)">0%</div></div><div class="muted" style="font-size:12px">חילוץ ממוצע על פני השדות</div></div>
    ${['חברה','תאריך','מס׳ מסמך','סכום','חילוץ AI'].map(f=>`<div class="bar-line"><span class="bar-num">0</span><div class="bar-track"><div class="bar-fill" style="width:2%;background:var(--red)"></div></div><div class="lab">${f}</div></div>`).join('')}
  </div>
</div>
<div class="g2">
  <div class="card"><h3>לפי סוג מסמך</h3>${[['חשבונית',3,100,'var(--green)'],['הזמנה',1,40,'var(--green)'],['תעודת משלוח',1,40,'var(--green)']].map(r=>`<div class="bar-line"><span class="bar-num">${r[1]}</span><div class="bar-track"><div class="bar-fill" style="width:${r[2]}%;background:${r[3]}"></div></div><div class="lab">${r[0]}</div></div>`).join('')}</div>
  <div class="card"><h3>חברות מובילות</h3>${['סבח סוכנויות בע"מ','ישראל קרטון','מ.ש. הכהנים בע"מ','אגן שיווק','פוליראן תעשיות'].map(c=>`<div class="bar-line"><span class="bar-num">1</span><div class="bar-track"><div class="bar-fill" style="width:100%;background:var(--purple)"></div></div><div class="lab" style="width:150px">${c}</div></div>`).join('')}</div>
</div>
`,{biz:indoxTabs('indox-root')});

/* ===================== MAIL INBOX ===================== */
screen('mail-inbox','mail-inbox','מייל','תיבת דואר עסקית',`
<div class="row" style="justify-content:space-between;padding:12px 4px 16px;flex-wrap:wrap;gap:10px">
  <div class="row" style="gap:10px"><span class="badge badge-red" style="display:inline-flex;align-items:center;gap:6px">● שגיאה</span><button class="btn btn-sm">מקומי ▾</button><button class="btn btn-sm">+ חבר חשבון חדש</button></div>
  <div class="muted" style="font-size:13px">נבדק ב‑22:59 ⟳</div>
</div>
<div style="background:#fff7ed;border:1px solid #f5d9ad;color:#9a5314;border-radius:9px;padding:9px 14px;margin-bottom:14px;text-align:center;font-size:13px">השירות לא השיב לבדיקת החיבור המתוזמנת. ייתכן שהוא מופעל מחדש כרגע.</div>
<div style="display:grid;grid-template-columns:230px 1fr;gap:16px;align-items:start">
  <div class="card" style="padding:12px">
    <div class="btn btn-primary" style="width:100%;justify-content:center;margin-bottom:8px">📥 כל הדואר</div>
    <div style="padding:6px 8px;color:#2b3a34;font-weight:700">🔒 דורש טיפול</div>
    <div class="muted" style="font-size:11px;font-weight:700;margin:12px 6px 4px">תוויות סנכרון · דוחות גיל</div>
    ${['לטיפול','טופל','נכשל'].map(l=>`<div style="padding:6px 8px;font-size:13px"><span style="color:var(--green)">●</span> ${l}</div>`).join('')}
    <div class="muted" style="font-size:11px;font-weight:700;margin:12px 6px 4px">מסמכים כללי</div>
    ${['לטיפול','טופל','באמצע טיפול','חשבונית נשמרה','מסמך לא מזוהה','פעולה בוצעה','פעולה נכשלה','תעודת משלוח נשמרה'].map(l=>`<div style="padding:5px 8px;font-size:13px"><span style="color:var(--gold)">●</span> ${l}</div>`).join('')}
  </div>
  <div class="tbl-wrap">
    <div class="spread" style="padding:12px 16px;border-bottom:1px solid var(--line)"><b>📥 כל הדואר</b><div class="searchbox" style="min-width:240px"><span>חיפוש… (גם from:"…" ו‑label:’וכו’)</span></div></div>
    <table class="tbl"><thead><tr><th>סטטוס</th><th>מאת</th><th>נושא · תוויות</th><th>תאריך</th></tr></thead><tbody>
    ${[['נכשל','Demo Link','קישור למסמך - zlmn-shr-2','22:46'],['נכשל','Demo Link','קישור למסמך - tsh-1','22:46'],['נכשל','Demo Link','קישור למסמך - avnt-symnt-3','22:46'],['נכשל','Demo Link','קישור למסמך - zlmn-shr-1','22:46'],['נכשל','Demo Link','קישור למסמך - avrbvnd-1','22:46'],['נכשל','י.ש קרטון מו','דוח גיל ysh-krtvn-5','22:45'],['נכשל','פזקר','דוח גיל tvrndv-3','22:45'],['נכשל','פלסאון','דוח גיל plsavn-5','22:45'],['נכשל','נוימן','דוח גיל nvymn-5','22:45'],['נכשל','איטונגא','דוח גיל aytvng-5','22:45'],['לטיפול','יחזקאל אהרן','חשבונית yhzkal-ahrvn-5','22:43'],['לטיפול','שריזלי','חשבונית shryzly-3','22:43'],['לטיפול','דלתות תייר','חשבונית dltvt-tyyr-2','22:43'],['לטיפול','בניאס','חשבונית bnyas-3','22:43']].map(r=>`<tr><td><span class="badge ${r[0]==='נכשל'?'badge-red':'badge-blue'}">${r[0]}</span></td><td>${r[1]}</td><td>📎 ${r[2]} <span class="badge badge-gray" style="font-size:10px">1+</span></td><td class="muted">היום ${r[3]}</td></tr>`).join('')}
    </tbody></table>
    <div class="spread" style="padding:10px 16px;color:var(--muted);font-size:12px"><span>מציג 100 מתוך 295</span><span style="color:var(--green);font-weight:700">הסתר דואר בדיקה (100)</span></div>
  </div>
</div>
`);

/* ===================== CONNECTIONS AUTH ===================== */
screen('connections-auth','connections-auth','חיבורים ומפתחות','ניהול מפתחות גישה וחיבורים',`
<div class="spread" style="margin-bottom:14px"><div class="row"><span class="live" style="background:var(--green);color:#fff"><span class="dt" style="background:#fff"></span></span><b style="font-size:18px">חיבורים ומפתחות</b><span class="muted" style="font-size:13px">● 30 תקינים · ● 7 דורשים טיפול · 51 סה״כ</span></div>
<div class="row"><button class="btn btn-sm">↺ יומן</button><button class="btn btn-sm">⟳ רענן</button><button class="btn btn-danger btn-sm">🗑 מחק סודות</button><button class="btn btn-primary btn-sm">+ סוד חדש</button></div></div>
<div class="segs" style="margin-bottom:12px"><span class="seg">🔑 סודות מערכת <span class="c">27</span></span><span class="seg on">🔗 חיבורי אימות <span class="c">18</span></span><span class="seg">📦 סיסמאות אפליקציות <span class="c">6</span></span></div>
<div class="spread" style="margin-bottom:10px"><span class="muted" style="font-size:12px">חיבורים לשירותים חיצוניים — מפתחות API, OAuth, סריקת QR, חשבונות שירות ותעודות. חיבור, בדיקה וניתוק מנוהלים כאן.</span><div class="row"><button class="btn btn-sm">⚠ רק דורשים טיפול</button><div class="searchbox" style="min-width:180px"><span>חיפוש…</span></div></div></div>
<div class="tbl-wrap"><table class="tbl"><thead><tr><th>שם</th><th>ערך</th><th>מקור</th><th></th></tr></thead><tbody>
${[['חיבור חשבון Google (הרשאת Gmail · Sheets · Drive)','google-workspace-grant','OAuth 2.0','—','לא מוגדר'],['חיבור מכשיר ווצאפ (סריקת QR)','whatsapp-baileys','סריקת QR','—','לא מוגדר'],['חשבון שירות Document AI (OCR בענן)','google-document-ai','חשבון שירות','לא מוגדר','לא מוגדר'],['מזהה OAuth של Gmail','gmail-oauth-client','OAuth 2.0','לא מוגדר','ברירת מחדל'],['מזהה OAuth של Google (Sheets / Drive)','google-oauth-client','OAuth 2.0','••••••••','ברירת מחדל'],['מפתח Gemini (Google AI Studio) — חילוץ AI','gemini-key','מפתח API','—','לא מוגדר'],['מפתח Google Vision (OCR בענן)','google-vision-key','מפתח API','••••••••','ברירת מחדל'],['סיסמת אפליקציה של Gmail (IMAP/SMTP)','gmail-app-password','אימות בסיסי','—','לא מוגדר'],['Anthropic (Claude) API key','anthropic-key','מפתח API','לא מוגדר','ברירת מחדל'],['browser42 /mcp bearer token','browser42-mcp-token','טוקן','••••••••','ברירת מחדל']].map(r=>`<tr><td><div style="font-weight:700">${r[0]}</div><div class="muted" style="font-size:11px;direction:ltr;text-align:right">${r[1]} <span class="badge badge-gray" style="font-size:10px">${r[2]}</span></div></td><td class="muted">${r[3]}</td><td><span class="badge badge-gray">${r[4]}</span></td><td class="muted">▾</td></tr>`).join('')}
</tbody></table></div>
`);

console.log('core screens written:', fs.readdirSync(dir).length);
