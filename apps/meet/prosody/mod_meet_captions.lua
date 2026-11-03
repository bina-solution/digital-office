-- mod_meet_captions — apps/meet: writes the live captions down as they are said (fireplace, 2026-10-27:
-- the owner, after fpg103/fpg104 came out of a starved recorder with a third of their words gone:
-- «live transcription showing up in meet so i will never be betrayed like that», and on a 2-core box,
-- «להגדיל זה לא אופציה»).
--
-- Each person's own browser captions that person's own voice (web/plugin.head.html, LIVE CAPTIONS
-- FROM EACH PERSON'S OWN BROWSER) and sends the text to the room as a JSON message
-- ({"type":"dgo-caption", sid, seq, text, final, lang}); prosody relays it like any message, and no
-- history keeps it (it carries no body). This module writes it down on the way, one file per meeting
-- under MEET_CAPTIONS_DIR, so a meeting has its words on disk the moment they are said — when it had
-- no recording (one recorder: a second meeting at the same time is not recorded) and when the
-- recording broke:
--   <dir>/<slug>_<start>.jsonl   while the room lives: {"k","t","name","text","final"} per update; a
--                                caption still being said is written at most every INTERIM seconds, a
--                                settled one at once; the last line of a key is its text
--   <dir>/<slug>_<start>.json    when the room ends: {id, room, started, ended, people, sessions (the
--                                recordings jicofo reported), segments [{t, name, text, final}]}
-- A .jsonl without its .json (prosody stopped mid-meeting) is turned into one at the next start.
-- The name is the one the room sees for the sender (its presence nick), never one the message claims.
-- A caption that never settled (the person left mid-sentence) keeps its last text with final=false.
--
-- meet-start reads the meetings through a door on prosody's HTTP port (5280, meet-net only, never
-- routed by the edge), with the bearer secret the recorder's door takes (MEET_RECORDER_WATCH_SECRET:
-- the same two containers hold it):
--   GET /meet-captions/meetings        [{id, room, started, ended, live, people, sessions, segments, words}]
--   GET /meet-captions/meetings/<id>   the meeting, segments included, and who was in the room
--                                      without captions (attendees, uncaptioned) and the signed-in
--                                      users (their token's id: meet-start leaves QA's out)
--   GET /meet-captions/rooms           the rooms now: people, hosts, the recording's status (jicofo's
--                                      word), each person's captions state — meet-start's watch
--   POST /meet-captions/tell {node, text}   a message to that one room (never another), from «הקלטה»
-- Kept MEET_CAPTIONS_KEEP_DAYS (30) days. Loaded on the conference MUC component (XMPP_MUC_MODULES).
local json = require "cjson.safe";
local st = require "util.stanza";
local lfs = require "lfs";
local now = require "util.time".now;
local jid_split = require "util.jid".split;
local jid_unescape = require "util.jid".unescape;
local util = module:require "util";
local is_focus = util.is_focus;
local is_jibri = util.is_jibri;
local is_healthcheck_room = util.is_healthcheck_room;

local SECRET = os.getenv("MEET_RECORDER_WATCH_SECRET") or "";
local DIR = (os.getenv("MEET_CAPTIONS_DIR") or "/var/lib/prosody/meet-captions"):gsub("/+$", "");
local KEEP_DAYS = tonumber(os.getenv("MEET_CAPTIONS_KEEP_DAYS") or "") or 30;
local NS = "http://jitsi.org/jitmeet";
local JIBRI_NS = "http://jitsi.org/protocol/jibri";
local INTERIM = 3            -- seconds between two writes of a caption still being said
local MAX_TEXT = 4000        -- characters: a minute of fast speech is ~900
local MAX_RATE = 20          -- messages a second from one person; the page sends at most ~4

lfs.mkdir(DIR);

local function round1(x) return math.floor(x * 10 + 0.5) / 10; end

local function name_of(occupant)
    local presence = occupant:get_presence();
    local nick = presence and presence:get_child_text("nick", "http://jabber.org/protocol/nick");
    return (nick and nick ~= "") and nick or "משתתף";
end

local function words(text)
    local n = 0;
    for _ in tostring(text or ""):gmatch("%S+") do n = n + 1; end
    return n;
end

-- One meeting per room lifetime, opened by its first caption.
local function meeting(room)
    local m = room.meet_captions;
    if m then return m; end
    local node = jid_split(room.jid) or "room";
    local started = now();
    local slug = node:gsub("[^%w%-]", "_"):sub(1, 48);
    local id = slug .. "_" .. os.date("!%Y%m%d-%H%M%S", math.floor(started));
    m = { id = id, room = jid_unescape(node), started = round1(started), segs = {}, order = {}, people = {},
          sessions = {}, rate = {}, attendees = room.meet_attendees or {}, users = room.meet_users or {} };
    room.meet_attendees, room.meet_users = m.attendees, m.users;
    for sid in pairs(room.meet_rec_sessions or {}) do m.sessions[sid] = true; end
    m.file = io.open(DIR .. "/" .. id .. ".jsonl", "a");
    if not m.file then module:log("error", "cannot write %s/%s.jsonl", DIR, id); end
    room.meet_captions = m;
    module:log("info", "%s: live captions are being written to %s.jsonl", room.jid, id);
    return m;
end

local function doc_of(m, ended)
    local list = {};
    for _, key in ipairs(m.order) do
        local s = m.segs[key];
        if s.text and s.text ~= "" then list[#list + 1] = { t = s.t, name = s.name, text = s.text, final = s.final }; end
    end
    table.sort(list, function (a, b) return a.t < b.t; end);
    local people, sessions, total, attendees, uncaptioned, users = {}, {}, 0, {}, {}, {};
    for name in pairs(m.people) do people[#people + 1] = name; end
    for sid in pairs(m.sessions) do sessions[#sessions + 1] = sid; end
    for _, s in ipairs(list) do total = total + words(s.text); end
    for _, a in pairs(m.attendees or {}) do
        attendees[#attendees + 1] = { name = a.name, captions = a.captions or "none" };
        if not m.people[a.name] then uncaptioned[#uncaptioned + 1] = a.name; end
    end
    for id in pairs(m.users or {}) do users[#users + 1] = id; end
    table.sort(people); table.sort(uncaptioned); table.sort(users);
    local function arr(t) return #t > 0 and t or json.empty_array; end
    return { id = m.id, room = m.room, started = m.started, ended = ended, live = ended == nil,
             people = arr(people), sessions = arr(sessions), segments = arr(list), words = total,
             attendees = arr(attendees), uncaptioned = arr(uncaptioned), users = arr(users), recovered = m.recovered or nil };
end

local function write_json(path, doc)
    local tmp = path .. ".tmp";
    local f = io.open(tmp, "w");
    if not f then return false; end
    f:write(json.encode(doc)); f:close();
    return os.rename(tmp, path);
end

local function finish(room)
    local m = room.meet_captions;
    if not m then return; end
    room.meet_captions = nil;
    if m.file then m.file:close(); end
    for sid in pairs(room.meet_rec_sessions or {}) do m.sessions[sid] = true; end
    local doc = doc_of(m, round1(now()));
    if write_json(DIR .. "/" .. m.id .. ".json", doc) then
        module:log("info", "%s: the live transcript is written: %s.json (%d segments, %d words, %d people)",
            room.jid, m.id, #m.order, doc.words, #doc.people == 0 and 0 or #doc.people);
    else
        module:log("error", "%s: cannot write %s.json", room.jid, m.id);
    end
end

module:hook("muc-occupant-groupchat", function (event)
    local room, occupant, stanza = event.room, event.occupant, event.stanza;
    if not room or not occupant or not stanza or is_healthcheck_room(room.jid) then return; end
    if is_focus(occupant.nick) or is_jibri(occupant) then return; end
    local holder = stanza:get_child("json-message", NS);
    if not holder then return; end
    local text = holder:get_text();
    if not text or #text > MAX_TEXT + 600 or not text:find("dgo%-caption", 1, false) then return; end
    local data = json.decode(text);
    if type(data) ~= "table" or data.type ~= "dgo-caption" or type(data.text) ~= "string"
        or type(data.sid) ~= "string" or #data.sid > 40 or type(data.seq) ~= "number" or #data.text > MAX_TEXT then
        return;
    end
    local m = meeting(room);
    local t = now();
    local second = math.floor(t);
    local rate = m.rate[occupant.nick];
    if not rate or rate.second ~= second then rate = { second = second, n = 0 }; m.rate[occupant.nick] = rate; end
    rate.n = rate.n + 1;
    if rate.n > MAX_RATE then return; end           -- relayed, not written: a broken page cannot fill the disk
    local name = name_of(occupant);
    m.people[name] = true;
    local key = occupant.nick .. "|" .. data.sid .. "|" .. math.floor(data.seq);
    local seg = m.segs[key];
    if not seg then
        seg = { t = round1(t), name = name };
        m.segs[key] = seg;
        m.order[#m.order + 1] = key;
    end
    seg.name, seg.text, seg.final = name, data.text, data.final == true;
    if seg.final or not seg.wrote or t - seg.wrote >= INTERIM then
        seg.wrote = t;
        if m.file then
            m.file:write(json.encode({ k = key, t = seg.t, name = name, text = seg.text, final = seg.final }), "\n");
            m.file:flush();
        end
    end
end);

-- Who signed in (their token's user id): a QA host's meeting is not the owner's (meet-start, QUIET).
module:hook("muc-occupant-joined", function (event)
    local room, origin = event.room, event.origin;
    local user = origin and origin.jitsi_meet_context_user;
    if room and user and user.id then
        room.meet_users = room.meet_users or {};
        room.meet_users[tostring(user.id)] = true;
    end
    if room and not room.meet_since then room.meet_since = os.time(); end
end);

-- The recordings this room had: jicofo's own presence names each one's session (the recording's folder).
-- And everyone else's: their name and their page's captions state (jitsi_participant_dgo_captions), so
-- the transcript can say who was there and not in it (a phone app sends no state at all).
module:hook("muc-broadcast-presence", function (event)
    local room, occupant, stanza = event.room, event.occupant, event.stanza;
    if not room or not occupant or not stanza or is_healthcheck_room(room.jid) then return; end
    if not is_focus(occupant.nick) then
        if is_jibri(occupant) or stanza.attr.type == "unavailable" then return; end
        room.meet_attendees = room.meet_attendees or {};
        local a = room.meet_attendees[occupant.nick] or {};
        local nick = stanza:get_child_text("nick", "http://jabber.org/protocol/nick");
        a.name = (nick and nick ~= "") and nick or a.name or "משתתף";
        a.captions = stanza:get_child_text("jitsi_participant_dgo_captions") or a.captions;
        room.meet_attendees[occupant.nick] = a;
        return;
    end
    local status = stanza:get_child("jibri-recording-status", JIBRI_NS);
    local sid = status and status.attr.session_id;
    if sid and sid ~= "" then
        room.meet_rec_sessions = room.meet_rec_sessions or {};
        room.meet_rec_sessions[sid] = true;
        if room.meet_captions then room.meet_captions.sessions[sid] = true; end
    end
end);

module:hook("muc-room-destroyed", function (event) finish(event.room); end);

local function each_room()
    local muc = prosody.hosts[module.host] and prosody.hosts[module.host].modules.muc;
    return muc and muc.each_room and muc.each_room() or function () return nil; end;
end

-- Prosody going down mid-meeting: what was said so far becomes the meeting's file.
module:hook_global("server-stopping", function ()
    for room in each_room() do finish(room); end
end);

-- A .jsonl with no .json: the meeting outlived the last prosody. Its last line per key is the text.
local function recover()
    for file in lfs.dir(DIR) do
        local id = file:match("^(.+)%.jsonl$");
        if id and not lfs.attributes(DIR .. "/" .. id .. ".json") then
            local m = { id = id, room = id:gsub("_%d+%-%d+$", ""), segs = {}, order = {}, people = {}, sessions = {}, recovered = true };
            local first, last = nil, nil;
            for line in io.lines(DIR .. "/" .. file) do
                local row = json.decode(line);
                if type(row) == "table" and row.k then
                    if not m.segs[row.k] then m.order[#m.order + 1] = row.k; end
                    m.segs[row.k] = { t = row.t, name = row.name, text = row.text, final = row.final };
                    m.people[row.name or "משתתף"] = true;
                    first = first and math.min(first, row.t) or row.t;
                    last = last and math.max(last, row.t) or row.t;
                end
            end
            m.started = first or round1(now());
            local attr = lfs.attributes(DIR .. "/" .. file);
            write_json(DIR .. "/" .. id .. ".json", doc_of(m, round1(math.max(last or 0, attr and attr.modification or 0))));
            module:log("warn", "recovered the live transcript of an interrupted meeting: %s.json", id);
        end
    end
end

local function prune()
    local cutoff = os.time() - KEEP_DAYS * 86400;
    for file in lfs.dir(DIR) do
        if file:match("%.jsonl?$") then
            local attr = lfs.attributes(DIR .. "/" .. file);
            if attr and attr.modification < cutoff then os.remove(DIR .. "/" .. file); end
        end
    end
end

pcall(recover);
pcall(prune);
module:add_timer(86400, function () pcall(prune); return 86400; end);

-- The door.
local summaries = {};      -- file name -> {mtime, summary}
local function summary_of(doc)
    return { id = doc.id, room = doc.room, started = doc.started, ended = doc.ended, live = doc.live == true,
             people = doc.people, sessions = doc.sessions, words = doc.words,
             segments = type(doc.segments) == "table" and #doc.segments or 0, recovered = doc.recovered };
end

local function read_doc(id)
    if not id or id:find("[/\\]") or id:find("%.%.") then return nil; end
    local f = io.open(DIR .. "/" .. id .. ".json", "r");
    if not f then return nil; end
    local doc = json.decode(f:read("*a")); f:close();
    return type(doc) == "table" and doc or nil;
end

local function answer(response, code, doc)
    response.status_code = code;
    response.headers.content_type = "application/json; charset=utf-8";
    return json.encode(doc);
end

local function authorized(request)
    local auth = request.headers and request.headers.authorization or "";
    return SECRET ~= "" and auth == "Bearer " .. SECRET;
end

-- The rooms now, for meet-start's watch: a meeting with people and no recording is told to the owner.
local function rooms_now()
    local out = {};
    for room in each_room() do
        if not is_healthcheck_room(room.jid) then
            local people, hosts, names, captions = 0, 0, {}, {};
            local status, failure = "none", nil;
            for _, occupant in room:each_occupant() do
                if is_focus(occupant.nick) then
                    local presence = occupant:get_presence();
                    local st_ = presence and presence:get_child("jibri-recording-status", JIBRI_NS);
                    if st_ then status, failure = st_.attr.status or "none", st_.attr.failure_reason; end
                elseif not is_jibri(occupant) then
                    people = people + 1;
                    if occupant.role == "moderator" then hosts = hosts + 1; end
                    local presence = occupant:get_presence();
                    local nick = presence and presence:get_child_text("nick", "http://jabber.org/protocol/nick") or "משתתף";
                    names[#names + 1] = nick;
                    captions[nick] = presence and presence:get_child_text("jitsi_participant_dgo_captions") or "none";
                end
            end
            local m = room.meet_captions;
            out[#out + 1] = { room = jid_unescape((jid_split(room.jid))), node = (jid_split(room.jid)), people = people, hosts = hosts,
                names = #names > 0 and names or json.empty_array, recording = status, failure = failure,
                since = room.meet_since, captions = next(captions) and captions or json.empty_array,
                captioned_words = m and (function () local n = 0; for _, s in pairs(m.segs) do n = n + words(s.text); end return n; end)() or 0,
                last_caption = m and (function () local t = 0; for _, s in pairs(m.segs) do t = math.max(t, s.wrote or 0); end return math.floor(t); end)() or 0 };
        end
    end
    return out;
end

module:depends("http");
module:provides("http", {
    default_path = "/meet-captions";
    route = {
        ["GET /rooms"] = function (event)
            if not authorized(event.request) then return answer(event.response, SECRET == "" and 503 or 401, { error = "unauthorized" }); end
            local out = rooms_now();
            return answer(event.response, 200, #out > 0 and out or json.empty_array);
        end;
        -- meet-start's watch tells ONE room something (a meeting that is not being recorded): the room
        -- named exactly (its node), never a fallback, so a message cannot land in another meeting.
        ["POST /tell"] = function (event)
            if not authorized(event.request) then return answer(event.response, SECRET == "" and 503 or 401, { error = "unauthorized" }); end
            local body = json.decode(event.request.body or "");
            if type(body) ~= "table" or type(body.node) ~= "string" or type(body.text) ~= "string" or body.text == "" or #body.text > 2000 then
                return answer(event.response, 400, { error = "{node, text} with a text of at most 2000 characters" });
            end
            local sent = 0;
            for room in each_room() do
                if jid_split(room.jid) == body.node then
                    for _, occupant in room:each_occupant() do
                        if not is_focus(occupant.nick) and not is_jibri(occupant) then
                            for real_jid in occupant:each_session() do
                                room:route_stanza(st.message({ from = room.jid, to = real_jid, type = "groupchat" })
                                    :tag("body"):text(body.text):up()
                                    :tag("display-name", { xmlns = "http://jitsi.org/protocol/display-name" }):text("הקלטה"):up());
                                sent = sent + 1;
                            end
                        end
                    end
                end
            end
            return answer(event.response, sent > 0 and 200 or 404, { sessions = sent });
        end;
        ["GET /meetings"] = function (event)
            if not authorized(event.request) then return answer(event.response, SECRET == "" and 503 or 401, { error = "unauthorized" }); end
            local out = {};
            for room in each_room() do
                if room.meet_captions then out[#out + 1] = summary_of(doc_of(room.meet_captions, nil)); end
            end
            for file in lfs.dir(DIR) do
                local id = file:match("^(.+)%.json$");
                if id then
                    local attr = lfs.attributes(DIR .. "/" .. file);
                    local cached = summaries[file];
                    if not cached or cached.mtime ~= (attr and attr.modification) then
                        local doc = read_doc(id);
                        cached = doc and { mtime = attr and attr.modification, summary = summary_of(doc) } or nil;
                        summaries[file] = cached;
                    end
                    if cached then out[#out + 1] = cached.summary; end
                end
            end
            table.sort(out, function (a, b) return (a.started or 0) > (b.started or 0); end);
            return answer(event.response, 200, #out > 0 and out or json.empty_array);
        end;
        ["GET /meetings/*"] = function (event, id)
            if not authorized(event.request) then return answer(event.response, SECRET == "" and 503 or 401, { error = "unauthorized" }); end
            for room in each_room() do
                if room.meet_captions and room.meet_captions.id == id then return answer(event.response, 200, doc_of(room.meet_captions, nil)); end
            end
            local doc = read_doc(id);
            if not doc then return answer(event.response, 404, { error = "no such meeting" }); end
            return answer(event.response, 200, doc);
        end;
    };
});

module:log("info", "live captions are written to %s (kept %d days); meet-start reads them at /meet-captions", DIR, KEEP_DAYS);
