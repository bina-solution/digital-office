-- mod_meet_recorder_watch — apps/meet: the recorder's watchdog, and the captions, speak to the room
-- (fireplace, 2026-10-26: the recorder was starved to 0.48 of a core, ffmpeg ran at 0.93-0.97x, 40 %
-- of every second of audio became zeros, and nobody in the room was told).
--
-- The watching itself happens inside meet-jibri (jibri/watch.py: ffmpeg's pace, the cgroup's
-- throttling, its errors), where the facts are. What that script cannot do is talk to a room, so
-- this module gives it a door: a tiny HTTP endpoint on prosody's own HTTP port (5280, meet-net only,
-- never routed by the edge), behind a bearer secret hooks/prepare mints into .env
-- (MEET_RECORDER_WATCH_SECRET). A POST names no room: the message goes to the room(s) whose focus
-- says they are being recorded (jicofo's jibri-recording-status), which with one recorder is one room.
--
--   POST /meet-recorder-watch/recorder  {"text": …, "room": optional}   → from «הקלטה», pops up
--   POST /meet-recorder-watch/caption   {"text": …, "room": optional}   → from «כתוביות», a quiet
--        chat line: it carries a delay stamp, which the page takes as history — no pop-up and no
--        sound every 30 s (jitsi-meet chat middleware: a message with a timestamp is not notified)
--   GET  /meet-recorder-watch/rooms                                     → which rooms are recorded
-- All answer JSON {"rooms": [names]}; 401 without the secret; 503 while none is set.
-- Loaded on the conference MUC component (XMPP_MUC_MODULES), so the HTTP host is that component's
-- name: a caller sends `Host: muc.meet.jitsi` (watch.py does).
--
-- …and one thing only prosody sees: a recording that jicofo reports as failed (status off with a
-- failure reason, the recorder gone) is said to the room by the same voice, so the chat keeps it.
local st = require "util.stanza";
local json = require "cjson.safe";
local datetime = require "util.datetime";
local jid_split = require "util.jid".split;
local util = module:require "util";
local is_focus = util.is_focus;
local is_jibri = util.is_jibri;
local is_healthcheck_room = util.is_healthcheck_room;
local get_focus_occupant = util.get_focus_occupant;

local SECRET = os.getenv("MEET_RECORDER_WATCH_SECRET") or "";
local JIBRI_NS = "http://jitsi.org/protocol/jibri";
local RECORDER = "הקלטה";
local CAPTIONS = "כתוביות";
local FAILED = "⚠️ ההקלטה נפלה (%s) — מהרגע הזה הדברים לא מוקלטים עד שההקלטה מופעלת שוב (כפתור ההקלטה, או יציאה וכניסה מחדש של המארח). · ⚠️ The recording stopped unexpectedly (%s): from now on nothing is recorded until it is started again (the record button, or the host leaves and rejoins).";

module:depends("http");

local function recording_status(room)
    local focus = get_focus_occupant(room);
    local presence = focus and focus:get_presence();
    local status = presence and presence:get_child("jibri-recording-status", JIBRI_NS);
    return status and status.attr.status or "none", status and status.attr.failure_reason or nil;
end

-- Every person in the room, never jicofo or the recorder: a message the recorder's own page shows
-- would be recorded.
local function tell_room(room, sender, message, quiet)
    local sent = 0;
    for _, occupant in room:each_occupant() do
        if not is_focus(occupant.nick) and not is_jibri(occupant) then
            for real_jid in occupant:each_session() do
                local msg = st.message({ from = room.jid, to = real_jid, type = "groupchat" })
                    :tag("body"):text(message):up()
                    :tag("display-name", { xmlns = "http://jitsi.org/protocol/display-name" }):text(sender):up();
                if quiet then
                    msg:tag("delay", { xmlns = "urn:xmpp:delay", from = room.jid, stamp = datetime.datetime() }):up();
                end
                room:route_stanza(msg);
                sent = sent + 1;
            end
        end
    end
    return sent;
end

-- The room named (the recording's file name carries the room), or — when no room of that name is
-- known, a Hebrew name escaped in the file — every room jicofo says is being recorded.
local function recorded_rooms(wanted)
    local muc = prosody.hosts[module.host] and prosody.hosts[module.host].modules.muc;
    local recorded, named = {}, {};
    if not (muc and muc.each_room) then return recorded; end
    wanted = wanted and wanted ~= "" and wanted:lower() or nil;
    for room in muc.each_room() do
        if not is_healthcheck_room(room.jid) then
            local node = jid_split(room.jid);
            local status = recording_status(room);
            if status == "on" or status == "pending" then recorded[#recorded + 1] = room; end
            if wanted and node == wanted then named[#named + 1] = room; end
        end
    end
    return #named > 0 and named or recorded;
end

local function names(rooms)
    local out = {};
    for i, room in ipairs(rooms) do out[i] = (jid_split(room.jid)); end
    return #out > 0 and out or json.empty_array;      -- cjson writes an empty table as {}
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

local function post(event, sender, quiet)
    local request, response = event.request, event.response;
    if SECRET == "" then return answer(response, 503, { error = "MEET_RECORDER_WATCH_SECRET is empty" }); end
    if not authorized(request) then return answer(response, 401, { error = "unauthorized" }); end
    local body = json.decode(request.body or "");
    if type(body) ~= "table" or type(body.text) ~= "string" or body.text == "" or #body.text > 4000 then
        return answer(response, 400, { error = "a JSON object {text, room?} with a text of at most 4000 characters" });
    end
    local rooms = recorded_rooms(type(body.room) == "string" and body.room or nil);
    local sent = 0;
    for _, room in ipairs(rooms) do
        sent = sent + tell_room(room, sender, body.text, quiet);
    end
    if not quiet then
        module:log("info", "the recorder's watchdog told %d room(s), %d session(s): %s", #rooms, sent, body.text:sub(1, 80));
    end
    return answer(response, 200, { rooms = names(rooms), sessions = sent });
end

module:provides("http", {
    default_path = "/meet-recorder-watch";
    route = {
        ["POST /recorder"] = function (event) return post(event, RECORDER, false); end;
        ["POST /caption"] = function (event) return post(event, CAPTIONS, true); end;
        ["GET /rooms"] = function (event)
            if SECRET == "" then return answer(event.response, 503, { error = "MEET_RECORDER_WATCH_SECRET is empty" }); end
            if not authorized(event.request) then return answer(event.response, 401, { error = "unauthorized" }); end
            return answer(event.response, 200, { rooms = names(recorded_rooms(nil)) });
        end;
    };
});

-- A recording that fails is said in the chat too: jicofo's status goes off with a failure reason
-- (the recorder died, was kicked, or lost the room), and Jitsi's own pop-up is gone in seconds.
module:hook("muc-broadcast-presence", function (event)
    local room, occupant, stanza = event.room, event.occupant, event.stanza;
    if not room or not occupant or not stanza or is_healthcheck_room(room.jid) or not is_focus(occupant.nick) then return; end
    local status = stanza:get_child("jibri-recording-status", JIBRI_NS);
    local now = status and status.attr.status or "none";
    local before = room.meet_recorder_status or "none";
    room.meet_recorder_status = now;
    if now == "off" and (before == "on" or before == "pending") and status.attr.failure_reason then
        local why = status.attr.failure_reason;
        module:log("warn", "%s: the recording failed (%s) — told the room", room.jid, why);
        tell_room(room, RECORDER, string.format(FAILED, why, why), false);
    end
end);

if SECRET == "" then
    module:log("warn", "MEET_RECORDER_WATCH_SECRET is empty: the recorder's watchdog cannot speak to the rooms (apps/meet/hooks/prepare mints it)");
else
    module:log("info", "the recorder's watchdog may speak to the recorded room at /meet-recorder-watch (host %s)", module.host);
end
