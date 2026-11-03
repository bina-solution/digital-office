/* types.js — what a file IS, said once: its kind, its glyph, its words, whether it has a picture
   (a thumbnail), and which viewer opens it in place. Everything else — the list, the grid, the
   viewer, the details — asks here. A type no viewer can open natively says so (`viewer: null`)
   and is offered to the apps that registered for it ("open with"), then downloaded. */
(function () {
  "use strict";
  const { L } = F;

  // kind → presentation. `thumb`: the server can draw a picture of it. `media`: it plays.
  const KINDS = {
    folder:  { icon: "folder",    he: "תיקייה",      en: "Folder" },
    image:   { icon: "image",     he: "תמונה",       en: "Image",        thumb: true, viewer: "image" },
    raster:  { icon: "image",     he: "תמונה",       en: "Image",        thumb: true, viewer: "preview" },
    video:   { icon: "film",      he: "סרטון",       en: "Video",        thumb: true, viewer: "video", media: "video" },
    audio:   { icon: "music",     he: "אודיו",       en: "Audio",        thumb: true, viewer: "audio", media: "audio" },
    pdf:     { icon: "pdf",       he: "PDF",          en: "PDF",          thumb: true, viewer: "pdf", doc: true },
    word:    { icon: "file-text", he: "מסמך",        en: "Document",     viewer: "docx", doc: true },
    text:    { icon: "file-text", he: "טקסט",        en: "Text",         viewer: "text" },
    md:      { icon: "file-text", he: "Markdown",     en: "Markdown",     viewer: "md" },
    sheet:   { icon: "sheet",     he: "גיליון",      en: "Spreadsheet",  viewer: "sheet" },
    slides:  { icon: "slides",    he: "מצגת",        en: "Presentation", viewer: null, doc: true },
    office:  { icon: "file-text", he: "מסמך",        en: "Document",     viewer: null, doc: true },
    ebook:   { icon: "book",      he: "ספר",         en: "E-book",       viewer: "epub" },
    code:    { icon: "code",      he: "קוד",         en: "Code",         viewer: "code" },
    data:    { icon: "code",      he: "נתונים",      en: "Data",         viewer: "code" },
    html:    { icon: "code",      he: "דף אינטרנט",  en: "Web page",     viewer: "html" },
    archive: { icon: "archive",   he: "ארכיון",      en: "Archive",      viewer: "zip" },
    disk:    { icon: "archive",   he: "קובץ דחוס",   en: "Archive",      viewer: null },
    model:   { icon: "cube",      he: "מודל תלת־ממד", en: "3D model",    viewer: "model" },
    cad:     { icon: "cube",      he: "שרטוט",       en: "Drawing",      viewer: null },
    font:    { icon: "type",      he: "גופן",        en: "Font",         viewer: "font" },
    contact: { icon: "user",      he: "איש קשר",     en: "Contact",      viewer: "vcf" },
    event:   { icon: "calendar",  he: "אירוע",       en: "Event",        viewer: "ics" },
    email:   { icon: "mail",      he: "אימייל",      en: "Email",        viewer: "eml" },
    db:      { icon: "db",        he: "מסד נתונים",  en: "Database",     viewer: null },
    program: { icon: "app",       he: "תוכנה",       en: "Program",      viewer: null },
    torrent: { icon: "magnet",    he: "טורנט",       en: "Torrent",      viewer: "torrent" },
    other:   { icon: "file",      he: "קובץ",        en: "File",         viewer: null },
  };

  // extension → kind. The browser draws `image` itself; `raster` needs the server's picture.
  const EXT = {};
  const add = (kind, list) => list.split(" ").forEach((e) => (EXT[e] = kind));
  add("image", "jpg jpeg png gif webp avif bmp ico svg");
  add("raster", "heic heif tif tiff raw cr2 nef dng arw psd ai eps");
  add("video", "mp4 m4v mov webm mkv avi wmv flv 3gp mpeg mpg");
  add("audio", "mp3 wav flac aac m4a ogg oga opus weba wma mid midi amr");
  add("pdf", "pdf");
  add("word", "docx");
  add("office", "doc rtf odt pages");
  add("text", "txt log srt vtt");
  add("md", "md markdown");
  add("sheet", "xlsx xls xlsm ods csv tsv numbers");
  add("slides", "pptx ppt odp key");
  add("ebook", "epub");
  add("code", "css js mjs ts tsx jsx php py java c h cpp hpp cs go rs swift kt rb sql sh bat ps1 tex ipynb");
  add("data", "json xml yaml yml toml ini env conf cfg");
  add("html", "html htm");
  add("archive", "zip");
  add("disk", "rar 7z tar gz tgz bz2 xz iso dmg");
  add("model", "stl obj glb gltf 3mf ply fbx 3ds dae");
  add("cad", "dwg dxf");
  add("font", "ttf otf woff woff2");
  add("contact", "vcf");
  add("event", "ics");
  add("email", "eml");
  add("db", "db sqlite sqlite3");
  add("program", "exe msi dll apk deb app");
  add("torrent", "torrent");

  const extOf = (name) => {
    const s = String(name || "").toLowerCase(), i = s.lastIndexOf(".");
    return i > 0 ? s.slice(i + 1) : "";
  };
  function kindOf(it) {
    if (!it) return "other";
    if (it.kind === "folder" || it.isFolder) return "folder";
    const m = String(it.mime || "");
    // a container can hold sound only — a recorded .webm, an audio .mp4: the type says so, the name does not
    if (m.startsWith("audio/")) return "audio";
    const k = EXT[extOf(it.name)];
    if (k) return k;
    if (m.startsWith("image/")) return "image";
    if (m.startsWith("video/")) return "video";
    if (m.startsWith("audio/")) return "audio";
    if (m === "application/pdf") return "pdf";
    if (m.startsWith("text/")) return "text";
    return "other";
  }
  const info = (it) => KINDS[kindOf(it)] || KINDS.other;
  const label = (it) => { const k = info(it); return L(k.he, k.en); };
  const icon = (it) => info(it).icon;
  // a short tag over a glyph: the extension itself, as people say it
  const badge = (it) => { const e = extOf(it.name); return e && e.length <= 5 ? e.toUpperCase() : ""; };
  const hasThumb = (it) => !!info(it).thumb;
  const isMedia = (it) => info(it).media || "";
  const viewerOf = (it) => info(it).viewer;

  F.types = { KINDS, EXT, extOf, kindOf, info, label, icon, badge, hasThumb, isMedia, viewerOf };
})();
