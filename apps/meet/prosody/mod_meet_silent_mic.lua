-- mod_meet_silent_mic — apps/meet: tells a person whose microphone is not reaching the meeting
-- (DGO-959, the owner 2026-10-21: «When I shared the screen, it disabled the microphone … It's like 20
-- minutes of talking … no way this happens again»; and fireplace 2026-10-26: the host joined from a
-- Mac Chrome that had never been allowed the microphone, joined muted, the bridge got 0 kbps for the
-- whole call, the recording is silent, and nobody was told).
--
-- Three failures, one guard. It asks the bridge (its debug REST, `/debug/<conference>`) every TICK
-- seconds how much audio it receives from each person, and reads each person's presence (SourceInfo,
-- what Jitsi's clients write about their own tracks):
--
--  1. NO MICROPHONE TRACK AT ALL (SourceInfo lists no audio source): the browser gave no access (the
--     permission was never granted, or denied), or there is no audio device. Jitsi shows a crossed
--     microphone, which looks like an ordinary mute, and the person talks into nothing. Told
--     MEET_NO_MIC_SECONDS (10) after the bridge has the person's media connected (ICE), with the fix
--     (the lock icon in the address bar → Microphone → Allow). Not counted from the join: a client
--     writes its sources only once jicofo has invited it to the bridge, and jicofo invites nobody
--     while they are alone in the room (verify-261101-1448 on vps1: the host joined 16:49:15 with its
--     microphone on, was invited when the recorder joined, 16:49:31, and was told «no microphone» at
--     :27 with SourceInfo {} — its audio arrived at :37). The page shows its own red banner too
--     (web/plugin.head.html); this one reaches the phone apps and the others in the room.
--  2. UNMUTED BUT NEVER HEARD: the microphone is on, the bridge holds the endpoint, and no audio has
--     arrived since the join (a wrong device, a muted hardware switch, a browser that got the
--     permission but no sound). Told after MEET_NO_MIC_SECONDS once the bridge has their media
--     connected and lists their audio.
--  3. HEARD, THEN SILENT (the Android case): the Jitsi Meet Android app stopped sending audio in the
--     background — sharing a screen means showing another app — because on Android 13+ it keeps the
--     microphone there only through a foreground service it starts at join only when notifications
--     and the microphone are both allowed. Told after MEET_SILENT_MIC_SECONDS (20).
--
-- In every case the person is told with a room message (the kind mod_meet_share_notice sends: the
-- page and the phone apps pop it up — a phone in another app shows it on the way back), and the
-- others in the room are told whose voice is missing, so they can say so aloud. When the audio
-- arrives it says that too. Once per state: a state that does not change is not repeated.
--
-- A person who is merely quiet still sends audio (room noise is never digital silence); the bridge's
-- "Audio bitrate calculator" counts what is left after its silence discarder drops digital-silence
-- packets, so zero there means the microphone gives nothing — the failure, not a pause. A microphone
-- muted on purpose (a muted audio source in SourceInfo) is never a failure here.
--
-- Not for jicofo, the recorder, or jicofo's health-check rooms. Loaded on the conference MUC
-- component (XMPP_MUC_MODULES). Off with MEET_SILENT_MIC_SECONDS=0.
local st = require "util.stanza";
local datetime = require "util.datetime";
local json = require "cjson.safe";
local http = require "net.http";
local jid_split = require "util.jid".split;
local util = module:require "util";
local is_focus = util.is_focus;
local is_jibri = util.is_jibri;
local is_healthcheck_room = util.is_healthcheck_room;
local get_focus_occupant = util.get_focus_occupant;

local SILENT = tonumber(os.getenv("MEET_SILENT_MIC_SECONDS") or "") or 20;
if SILENT <= 0 then
    module:log("info", "the silent-microphone guard is off (MEET_SILENT_MIC_SECONDS=%s)", tostring(SILENT));
    return;
end
local NEVER = tonumber(os.getenv("MEET_NO_MIC_SECONDS") or "") or 10;
local BRIDGE = (os.getenv("MEET_JVB_DEBUG_URL") or "http://meet-jvb:8080"):gsub("/+$", "");
local TICK = 5;
-- M5-4.1-13 (call 5, 2026-10-28 [1:11:00]–[1:15:40]: «the barking drives me mad»). The «barking» was this
-- guard: one person quiet while the other talked was told «your voice stopped», then «it is back», every
-- 30–120 s (prosody log 09:30–09:50 local: 9 pairs for one endpoint), each a chat message that pops up and
-- RINGS on every page in the room. Case 3 below (heard, then silent) is the Android-background failure; on a
-- computer it is mostly a person listening. So, as settings (.env, no code):
--   MEET_SILENT_MIC_RING=0 (default)  case 3 and its «back» go to that person only, QUIET (kept in the chat,
--                                     no pop-up, no sound — as the captions already are); cases 1 and 2 (no
--                                     microphone at all / never heard since joining) still pop up, once.
--   MEET_SILENT_MIC_RING=1            the old behaviour (pop-up + sound, to the person and to the room).
--   MEET_SILENT_MIC_REPEAT_SECONDS    case 3 is said at most once per person in this many seconds (600).
local RING = (os.getenv("MEET_SILENT_MIC_RING") or "0") == "1";
local REPEAT = tonumber(os.getenv("MEET_SILENT_MIC_REPEAT_SECONDS") or "") or 600;

local SENDER = "פגישות וידאו";
-- 3. heard, then silent
local GONE = "⚠️ הקול שלך לא מגיע לפגישה — המיקרופון לא מושתק, אבל כבר %d שניות לא מגיע ממנו שום קול.";
local GONE_RECORDED = "⚠️ הקול שלך לא מגיע לפגישה ולא להקלטה — המיקרופון לא מושתק, אבל כבר %d שניות לא מגיע ממנו שום קול.";
local HOW = " באנדרואיד זה קורה כשההתראות של אפליקציית Jitsi כבויות ועוברים לאפליקציה אחרת: חזור ל-Jitsi, הפעל לה התראות (הגדרות ← אפליקציות ← Jitsi Meet ← התראות), צא מהפגישה והיכנס שוב."
    .. " · ⚠️ Your voice stopped reaching the meeting %d s ago although the microphone is not muted. On Android: return to Jitsi, allow its notifications (Settings → Apps → Jitsi Meet → Notifications), leave and rejoin.";
local BACK = "✅ הקול שלך מגיע שוב לפגישה. · ✅ Your voice reaches the meeting again.";
local OTHERS = "⚠️ הקול של %s לא מגיע לפגישה כבר %d שניות, אף שהמיקרופון לא מושתק — כדאי לומר ל-%s בקול. · ⚠️ %s's voice has not reached the meeting for %d s although the microphone is not muted — say so aloud.";
local OTHERS_BACK = "✅ הקול של %s מגיע שוב לפגישה. · ✅ %s's voice reaches the meeting again.";
-- 1. no microphone track — the fix is the browser's permission (or the device)
local FIX = " התיקון: לחצו על סמל המנעול 🔒 בשורת הכתובת ← מיקרופון ← אפשר, ואז רעננו את העמוד (בטלפון: הגדרות ← אפליקציות ← Jitsi Meet ← הרשאות ← מיקרופון).";
local FIX_EN = " Fix: click the lock icon 🔒 in the address bar → Microphone → Allow, then reload (on a phone: Settings → Apps → Jitsi Meet → Permissions → Microphone).";
local NO_MIC = "🎤 אין לך מיקרופון פעיל בפגישה — הדפדפן לא נתן גישה למיקרופון (או שאין מכשיר שמע), והקול שלך לא מגיע לפגישה%s." .. FIX
    .. " · 🎤 You have no working microphone in this meeting — the browser gave no microphone access (or there is no audio device): your voice is not reaching the meeting%s." .. FIX_EN;
local OTHERS_NO_MIC = "⚠️ ל-%s אין מיקרופון פעיל (אין הרשאה בדפדפן, או אין מכשיר שמע) — הקול שלו/ה לא מגיע לפגישה%s. כדאי לומר זאת בקול. · ⚠️ %s has no working microphone (no browser permission, or no audio device) — their voice is not reaching the meeting%s. Say so aloud.";
-- 2. unmuted, never heard
local NEVER_HEARD = "⚠️ הקול שלך לא מגיע לפגישה%s — המיקרופון מסומן כפתוח, אבל מאז ההצטרפות (%d שניות) לא הגיע ממנו שום קול. בדקו: סמל המנעול 🔒 בשורת הכתובת ← מיקרופון ← אפשר; בהגדרות ← התקנים שנבחר המיקרופון הנכון; ואז רעננו."
    .. " · ⚠️ Your voice is not reaching the meeting%s — the microphone shows as on, but no audio has arrived since you joined (%d s). Check: the lock icon 🔒 in the address bar → Microphone → Allow; Settings → Devices → the right microphone; then reload.";
local OTHERS_NEVER = "⚠️ הקול של %s לא מגיע לפגישה%s — המיקרופון מסומן כפתוח, אבל שום קול לא הגיע ממנו מאז ההצטרפות (%d שניות). כדאי לומר ל-%s בקול. · ⚠️ %s's voice is not reaching the meeting%s — the microphone shows as on but no audio has arrived since joining (%d s). Say so aloud.";
local FIRST = "✅ הקול שלך מגיע לפגישה. · ✅ Your voice reaches the meeting.";
local OTHERS_FIRST = "✅ הקול של %s מגיע עכשיו לפגישה. · ✅ %s's voice now reaches the meeting.";

-- The room a conference of the bridge is, on whichever MUC of this server holds it (the main one, or
-- the breakout rooms' component).
local function room_of(name)
    local _, host = jid_split(name);
    local component = host and prosody.hosts[host];
    local muc = component and component.modules and component.modules.muc;
    return muc and muc.get_room_from_jid and muc.get_room_from_jid(name) or nil;
end

-- What this person's presence says about their microphone. Jitsi's clients write their sources in
-- SourceInfo: an audio source (`<endpoint>-a0`), muted or not. "on": an unmuted audio source;
-- "muted": only muted ones; "none": no audio source at all (no track: no permission, no device);
-- "unknown": a client that writes no SourceInfo, about which nothing is claimed.
local function microphone(occupant)
    local presence = occupant:get_presence();
    local text = presence and presence:get_child_text("SourceInfo");
    local sources = text and json.decode(text);
    if type(sources) ~= "table" then return "unknown", text; end
    local found = "none";
    for name, source in pairs(sources) do
        if type(name) == "string" and name:match("%-a%d+$") and type(source) == "table" then
            if source.muted == false then return "on", text; end
            found = "muted";
        end
    end
    return found, text;
end

-- Is the room being recorded? jicofo says so in its own presence (mod_meet_share_notice reads it too).
local function recorded(room)
    local focus = get_focus_occupant(room);
    local presence = focus and focus:get_presence();
    local status = presence and presence:get_child("jibri-recording-status", "http://jitsi.org/protocol/jibri");
    return status ~= nil and (status.attr.status == "on" or status.attr.status == "pending");
end

-- quiet: a delay stamp makes the page take the line as history — kept in the chat, no pop-up, no sound
-- (jitsi-meet's chat middleware notifies only messages without a timestamp; mod_meet_recorder_watch's captions)
local function tell(room, occupant, message, quiet)
    for real_jid in occupant:each_session() do
        local msg = st.message({ from = room.jid, to = real_jid, type = "groupchat" })
            :tag("body"):text(message):up()
            :tag("display-name", { xmlns = "http://jitsi.org/protocol/display-name" }):text(SENDER):up();
        if quiet then
            msg:tag("delay", { xmlns = "urn:xmpp:delay", from = room.jid, stamp = datetime.datetime() }):up();
        end
        room:route_stanza(msg);
    end
end

local function person(occupant)
    return not is_focus(occupant.nick) and not is_jibri(occupant);
end

-- The name the others see for this person (their presence's nick), or a plain word.
local function name_of(occupant)
    local presence = occupant:get_presence();
    local nick = presence and presence:get_child_text("nick", "http://jabber.org/protocol/nick");
    return (nick and nick ~= "") and nick or "משתתף";
end

local function tell_others(room, occupant, message)
    for _, other in room:each_occupant() do
        if other.nick ~= occupant.nick and person(other) then tell(room, other, message); end
    end
end

-- What the bridge says about each endpoint now: the audio it receives, in packets per second
-- (endpoint id → pps; an endpoint the bridge holds without an audio counter yet is not listed), and
-- whose media is connected (endpoint id → true once its ICE has connected: jicofo allocates an
-- endpoint before it invites the person, so "held" alone does not mean the client has its media up).
local function bridge_view(conference)
    local rates, connected = {}, {};
    for endpoint, state in pairs(type(conference.endpoints) == "table" and conference.endpoints or {}) do
        if type(state) == "table" then
            local receiver = type(state.transceiver) == "table" and state.transceiver.receiver;
            local calc = type(receiver) == "table" and receiver["Audio bitrate calculator"];
            local pps = type(calc) == "table" and tonumber(calc.packet_rate_pps);
            if pps then rates[endpoint] = pps; end
            local ice = state.ice_transport;
            if type(ice) == "table" and ice.iceConnected == true then connected[endpoint] = true; end
        end
    end
    return rates, connected;
end

-- One room, against what the bridge said about it.
local function check(room, rates, connected, now)
    room.meet_silent = room.meet_silent or {};
    local seen = {};
    local rec = recorded(room);
    local rec_he, rec_en = rec and " ולא להקלטה" or "", rec and " or the recording" or "";
    for _, occupant in room:each_occupant() do
        if person(occupant) then
            local _, _, endpoint = jid_split(occupant.nick);
            local pps = endpoint and rates[endpoint];           -- nil: the bridge does not list them this round
            local s = room.meet_silent[occupant.nick] or { joined = now };
            seen[occupant.nick] = true;
            -- their media is up: the bridge says ICE connected, or their audio arrives (which it cannot without)
            if endpoint and (connected[endpoint] or (pps and pps > 0)) then s.connected = s.connected or now; end
            local mic, raw = microphone(occupant);
            local name = name_of(occupant);
            -- Heard means audio, not the handful of packets a track sends as it is unmuted (measured
            -- 2026-10-26: a microphone fed digital silence counted as "heard" for one round and was
            -- then judged by the 20-s rule instead of the 10-s one): speech-rate packets in one
            -- round (Opus sends 50 a second), or anything at all in two rounds running.
            if pps and pps > 0 then s.heard_rounds = (s.heard_rounds or 0) + 1; else s.heard_rounds = 0; end
            if pps and pps > 0 and not (pps >= 20 or s.heard_rounds >= 2) then
                -- the first packets: judged next round
            elseif pps and pps > 0 then
                -- heard now: whatever was said about them is over
                if s.told == "silent" then
                    if RING then
                        tell(room, occupant, BACK);
                        tell_others(room, occupant, string.format(OTHERS_BACK, name, name));
                    elseif s.silent_said then
                        tell(room, occupant, BACK, true);           -- quiet, to that person only
                    end
                    s.silent_said = nil;
                    module:log("info", "%s: %s's audio reaches the bridge again", room.jid, endpoint);
                elseif s.told then
                    tell(room, occupant, FIRST);
                    tell_others(room, occupant, string.format(OTHERS_FIRST, name, name));
                    module:log("info", "%s: %s's audio reaches the bridge for the first time (after %s)", room.jid, endpoint, s.told);
                end
                s.heard, s.since, s.quiet_since, s.told = true, nil, nil, nil;
            elseif mic == "none" then
                -- 1. no microphone track at all: the browser gave no access, or there is no device —
                -- judged only once their media is connected (before that, no client lists a source)
                s.since, s.quiet_since = nil, nil;
                if s.told ~= "nomic" and s.connected and now - s.connected >= NEVER then
                    tell(room, occupant, string.format(NO_MIC, rec_he, rec_en));
                    tell_others(room, occupant, string.format(OTHERS_NO_MIC, name, rec_he, name, rec_en));
                    s.told = "nomic";
                    module:log("warn", "%s: %s (%s) has no microphone track %d s after joining, %d s after its media connected (SourceInfo %s) — told them and the room",
                        room.jid, endpoint, name, math.floor(now - s.joined), math.floor(now - s.connected), tostring(raw));
                end
            elseif mic ~= "on" then
                -- muted on purpose (or a client that says nothing about its tracks): the silence is meant
                s.since, s.quiet_since = nil, nil;
                if s.told == "nomic" then s.told = nil; end      -- a track appeared, muted: that trouble is over
            elseif pps == nil or not s.connected then
                -- unmuted, but the bridge does not list their audio, or their media is not connected yet
            elseif s.heard then
                -- 3. heard, then silent
                s.since = s.since or now;
                if s.told ~= "silent" and now - s.since >= SILENT then
                    local seconds = math.floor(now - s.since);
                    if RING then
                        tell(room, occupant, string.format(rec and GONE_RECORDED or GONE, seconds) .. string.format(HOW, seconds));
                        tell_others(room, occupant, string.format(OTHERS, name, seconds, name, name, seconds));
                        s.silent_said = true;
                    elseif now - (s.silent_at or 0) >= REPEAT then
                        tell(room, occupant, string.format(rec and GONE_RECORDED or GONE, seconds) .. string.format(HOW, seconds), true);
                        s.silent_at, s.silent_said = now, true;
                    end
                    s.told = "silent";
                    module:log("warn", "%s: %s's microphone is on, and no audio has reached the bridge for %d s — told them",
                        room.jid, endpoint, seconds);
                end
            else
                -- 2. unmuted, listed by the bridge, never heard
                s.quiet_since = s.quiet_since or now;
                if s.told ~= "never" and now - s.quiet_since >= NEVER and now - s.joined >= NEVER then
                    local seconds = math.floor(now - s.joined);
                    tell(room, occupant, string.format(NEVER_HEARD, rec_he, seconds, rec_en, seconds));
                    tell_others(room, occupant, string.format(OTHERS_NEVER, name, rec_he, seconds, name, name, rec_en, seconds));
                    s.told = "never";
                    module:log("warn", "%s: %s (%s) is unmuted and the bridge has received no audio from them since they joined %d s ago — told them and the room",
                        room.jid, endpoint, name, seconds);
                end
            end
            room.meet_silent[occupant.nick] = s;
        end
    end
    for nick in pairs(room.meet_silent) do
        if not seen[nick] then room.meet_silent[nick] = nil; end
    end
end

-- A failed read is said, at most every ten minutes, and so is the first good one after it: a guard
-- that sees nothing must not look like a quiet room.
local last_warned, blinded = 0, false;
local function blind(url, why)
    blinded = true;
    if os.time() - last_warned >= 600 then
        last_warned = os.time();
        module:log("warn", "the silent-microphone guard cannot read %s (%s): it tells nobody until it can", url, why);
    end
end
local function sees()
    if blinded then
        blinded = false;
        module:log("info", "the silent-microphone guard reads the bridge again");
    end
end

-- The bridge sends its conference document chunked (Jetty, 32 KiB chunks), and Prosody 13's client
-- hands a chunked body to the callback with only its FIRST chunk unless a sink takes the stream (a
-- three-person call is ~57 KB: measured on vps1, 2026-10-21). So the body is gathered here, chunk by
-- chunk; a reply small enough to come whole arrives in `body` as before. The callback always runs:
-- with the document, or with nil (said by blind(), unless `gone_ok` and the bridge answered 404 — a
-- conference that ended between the list and its read).
local function get_json(url, callback, gone_ok)
    local parts = {};
    http.request(url, {
        method = "GET";
        streaming_handler = function ()
            return { write = function (_, data) parts[#parts + 1] = data; return true; end }, function () end;
        end;
    }, function (body, code)
        if code ~= 200 then
            if not (gone_ok and code == 404) then
                blind(url, ("HTTP %s %s"):format(tostring(code), type(body) == "string" and body:sub(1, 120) or ""));
            end
            return callback(nil);
        end
        local doc = json.decode(#parts > 0 and table.concat(parts) or body or "");
        if type(doc) ~= "table" then blind(url, "not a JSON document"); return callback(nil); end
        callback(doc);
    end);
end

-- The rooms with people in them, whether or not the bridge holds a conference for them: each
-- person's state (their join, their media's first connection) is kept from the first round they are
-- in the room, and nobody is told anything before the bridge has their media connected.
local function rooms_with_people()
    local out = {};
    local muc = prosody.hosts[module.host] and prosody.hosts[module.host].modules.muc;
    if not (muc and muc.each_room) then return out; end
    for room in muc.each_room() do
        if not is_healthcheck_room(room.jid) then
            for _, occupant in room:each_occupant() do
                if person(occupant) then out[room.jid] = { room = room, rates = {}, connected = {} }; break; end
            end
        end
    end
    return out;
end

-- One round at a time: the client has no timeout, so a bridge that stalls would otherwise gather a
-- request every tick. A round not finished in 30 s is given up, and its late answers are dropped.
-- Each room is judged once a round, on every conference the bridge holds for it (a room rejoined
-- before the old conference expired is two).
local round, pending, started = 0, 0, 0;
local function poll()
    local now = os.time();
    if pending > 0 then
        if now - started < 30 then return; end
        blind(BRIDGE, "no answer in 30 s");
    end
    round, pending, started = round + 1, 1, now;
    local mine, rooms = round, rooms_with_people();
    if next(rooms) == nil then pending = 0; return; end          -- nobody in any room: nothing to ask
    local function done()
        pending = pending - 1;
        if pending > 0 then return; end
        for _, entry in pairs(rooms) do check(entry.room, entry.rates, entry.connected, os.time()); end
    end
    get_json(BRIDGE .. "/debug", function (doc)
        if mine ~= round then return; end
        if doc then sees(); end
        for id in pairs(doc and type(doc.conferences) == "table" and doc.conferences or {}) do
            pending = pending + 1;
            get_json(BRIDGE .. "/debug/" .. id, function (full)
                if mine ~= round then return; end
                local conference = full and type(full.conferences) == "table" and full.conferences[id];
                local room = type(conference) == "table" and type(conference.name) == "string" and room_of(conference.name);
                if room and not is_healthcheck_room(room.jid) then
                    local entry = rooms[room.jid] or { room = room, rates = {}, connected = {} };
                    local rates, connected = bridge_view(conference);
                    for endpoint, pps in pairs(rates) do
                        entry.rates[endpoint] = math.max(entry.rates[endpoint] or 0, pps);
                    end
                    for endpoint in pairs(connected) do entry.connected[endpoint] = true; end
                    rooms[room.jid] = entry;
                end
                done();
            end, true);
        end
        done();
    end);
end

module:add_timer(TICK, function ()
    poll();
    return TICK;
end);

module:log("info", "the microphone guard asks %s every %d s; no microphone track or no audio is told %d s after the bridge has the person's media connected, a microphone that goes silent after %d s",
    BRIDGE, TICK, NEVER, SILENT);
