/* Mock backend for the המרכז console shell. Real console UI untouched; serves its API from
   the real module registry (modules.yaml) + plausible business KPIs. No real backend. */
(function(){
  var MODULES = [
    // No "לוח בקרה" module: the console has no home screen of its own — the rail IS the launcher,
    // and the shell opens on the first tile in it. Order here mirrors the live registry.
    {id:"my-docs",    name:"מסמכים שלי",      icon:"file-text", group:"עסק",    embed:"/a/my-docs/",            desc:"ניהול מסמכים עסקיים"},
    {id:"drive",      name:"דרייב",           icon:"folder",    group:"עסק",    embed:"/a/localdrive/",         desc:"קבצים ומסמכים"},
    {id:"mail",       name:"מייל",            icon:"mail",      group:"עסק",    embed:"/a/mailview/",           desc:"תיבת דואר עסקית"},
    {id:"chat",       name:"צ׳אט",            icon:"message",   group:"עסק",    embed:"/a/wadmin/",             desc:"שיחות מרובות ספקים (וואטסאפ / טלגרם / מקומי)"},
    {id:"incoming",   name:"מסמכים נכנסים",   icon:"inbox",     group:"עסק",    embed:"/a/incoming/",           desc:"עיבוד מסמכים אוטומטי (INDOX)"},
    {id:"concurrency",name:"כל מקביל",        icon:"activity",  group:"תשתית",  embed:"/a/any-concurrency/",    desc:"ציר-זמן מקביליות"},
    {id:"alerts",     name:"התראות",          icon:"bell",      group:"תשתית",  embed:"/a/alerts/",             desc:"מרכז התראות"},
    {id:"machine",    name:"מכונה",           icon:"server",    group:"תשתית",  embed:"/a/machine/",            desc:"מדדי מארח ו-Docker"},
    // The apps screen is an APP (app-management) since the shell's own grid was removed; `view:"apps"`
    // named a screen the shell no longer draws, so this tile loaded a frame at "undefined" and showed
    // nothing — unnoticed while the layout suite measured the browser's error page instead (see
    // flow-qa.py `screen`). Its real frontend is bundled now (build.mjs APPS, mocks/app-management.js).
    {id:"apps",       name:"אפליקציות",       icon:"grid",      group:"תשתית",  embed:"/a/app-management/",     desc:"כל האפליקציות והכלים"},
    {id:"validation", name:"אימות מערכת",     icon:"check",     group:"תשתית",  embed:"/a/feature-validation/", desc:"חבילת בדיקות מערכת"},
    {id:"connections",name:"חיבורים ומפתחות", icon:"key",       group:"הגדרות", embed:"/a/connections/",        desc:"ניהול מפתחות גישה וחיבורים"},
  ];
  var TOOLS = [
    {id:"n8n",name:"n8n",sub:"n8n",icon:"workflow",desc:"מנוע האוטומציה והתהליכים",href:"#"},
    {id:"glitchtip",name:"GlitchTip",sub:"glitchtip",icon:"alert",desc:"מעקב שגיאות ואירועים",href:"#"},
    {id:"supabase",name:"Supabase Studio",sub:"supabase-studio",icon:"database",desc:"מסד הנתונים והטבלאות",href:"#"},
    {id:"portainer",name:"Portainer",sub:"portainer",icon:"box",desc:"ניהול קונטיינרים ותשתית",href:"#"},
    {id:"authentik",name:"Authentik",sub:"auth",icon:"shield",desc:"זהויות, הרשאות ו-SSO",href:"#"},
    {id:"redisinsight",name:"RedisInsight",sub:"redisinsight",icon:"activity",desc:"מטמון ותורים (Redis)",href:"#"}
  ];
  var ROUTES = [
    [/\/api\/me/,            function(){ return {user:"akadmin", email:"admin@bina.local", name:"בינה · מנהל", groups:["admins"]}; }],
    [/\/api\/modules/,       function(){ return {modules:MODULES}; }],
    [/\/api\/apps/,          function(){ return {apps:MODULES, tools:TOOLS}; }],
    [/\/api\/office/,        function(){ return {installed:true, office:{name:"בינה פתרונות", animal:"elephant", hue:"muted"}}; }],
    [/\/api\/connections/,   function(){ return {summary:{healthy:27,total:51,attention:2}, connections:[]}; }],
    // per-service account bar (service:drive|mail) — shell renders it above the embed
    [/\/api\/svc\/[^/]+\/readyz/,  function(){ return {ready:true, ok:true}; }],
    [/\/api\/svc\/[^/]+\/manifest/,function(u){ var s=(u.match(/svc\/([^/]+)/)||[])[1]||""; return {name:s, service:s}; }],
    [/\/api\/svc\/(drive|localdrive)\/connections/, function(){ return {active:"local", connections:[{id:"local",protocol:"local",label:"אחסון מקומי",account_hint:"מקומי · מובנה",status:"ok"}]}; }],
    [/\/api\/svc\/(mail|mailview)\/connections/,    function(){ return {active:"gmail", connections:[{id:"gmail",protocol:"gmail",label:"Gmail",account_hint:"person127@example.com",status:"ok"}]}; }],
    [/\/api\/svc\/[^/]+\/connections/, function(){ return {active:null, connections:[]}; }]
  ];
  // Shared harness (build.mjs MOCK_PRELUDE): route handlers return plain objects → auto-JSON; the
  // harness passes (url,opts,match) so the svc/manifest handler still gets the url it parses.
  // fallback: any other console API → empty ok, keeps the UI from erroring; else defer to realFetch.
  window.__mock(ROUTES, function(u){ if (/\/api\//.test(u)) return {}; });
})();
