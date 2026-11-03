-- mod_meet_auto_record — apps/meet: every meeting a host opens is recorded from its first moment
-- (DGO-831, the owner: «שזה יקליט לי את המסך גם כשאני לבד וישמור הכל»). From any client: the web
-- page, the Jitsi Meet phone apps (which run no page script), the host alone in the room.
--
-- When a room's first moderator who is a person (not jicofo, not the recorder) is in, this sends the
-- request the record button sends (a jibri `start`, file mode, to the room's focus), posted from that
-- host's own session, with prosody's pre-events. So Jitsi's own modules treat it exactly as the
-- button: mod_filter_iq_jibri (moderators only, its rate limits) and mod_jibri_session (the host as
-- the recording's initiator). jicofo then invites the recorder, which also makes the room's second
-- participant, so a host alone gets the media session jicofo otherwise starts at two.
--
-- Once per room: a host who stops the recording is not overruled while the room lives (rooms are in
-- memory, so after a prosody restart a rebuilt room records again). Not in breakout or lobby rooms
-- (other components) or jicofo's health-check rooms. jicofo answers the host's client, which
-- drops it, so a start that fails (the one recorder busy, a rate limit) shows nothing on screen:
-- the recording status jicofo publishes is read 20 s later and a failure is logged here.
-- Loaded on the conference MUC component (XMPP_MUC_MODULES); MEET_AUTO_RECORD=0 turns it off.
local st = require "util.stanza";
local json = require "cjson.safe";
local uuid = require "util.uuid".generate;
local util = module:require "util";
local is_focus = util.is_focus;
local is_jibri = util.is_jibri;
local is_transcriber = util.is_transcriber;
local is_healthcheck_room = util.is_healthcheck_room;
local get_focus_occupant = util.get_focus_occupant;

local switch = (os.getenv("MEET_AUTO_RECORD") or "1"):lower();
if switch == "0" or switch == "false" or switch == "no" or switch == "off" then
    module:log("info", "automatic recording is off (MEET_AUTO_RECORD=%s)", switch);
    return;
end

-- jicofo grants the host's role a moment after the join; the request waits for it to settle.
local SETTLE_SECONDS = 2;
local CHECK_SECONDS = 20;
local JIBRI_NS = "http://jitsi.org/protocol/jibri";

local function a_person(occupant)
    return occupant.role == "moderator" and not is_focus(occupant.nick) and not is_jibri(occupant)
        and not is_transcriber(occupant.jid);
end

-- What jicofo says about the room's recording, in its own presence (as every client reads it).
local function recording_status(room)
    local focus = get_focus_occupant(room);
    local presence = focus and focus:get_presence();
    local status = presence and presence:get_child("jibri-recording-status", JIBRI_NS);
    return status and status.attr.status or "none";
end


-- THE RECORDER TAKES ~13 s TO ARRIVE (Chrome starts, joins): measured on fireplace 2026-10-26, a 15 s
-- call kept 2 s. So the room is told the recording is starting, and told again when it is on — people
-- wait for the second line instead of talking into nothing (issues/meet-recording-misses-the-first-13-seconds…).
local SENDER = "הקלטה";
local function tell_room(room, message)
    for _, occupant in room:each_occupant() do
        if not is_focus(occupant.nick) and not is_jibri(occupant) then
            for real_jid in occupant:each_session() do
                room:route_stanza(st.message({ from = room.jid, to = real_jid, type = "groupchat" })
                    :tag("body"):text(message):up()
                    :tag("display-name", { xmlns = "http://jitsi.org/protocol/display-name" }):text(SENDER):up());
            end
        end
    end
end

local function announce_until_on(room, left)
    if left <= 0 or not get_focus_occupant(room) then return; end
    if recording_status(room) == "on" then
        tell_room(room, "⏺ ההקלטה פועלת — אפשר לדבר. · Recording is on — go ahead.");
        return;
    end
    module:add_timer(2, function () announce_until_on(room, left - 2); end);
end

local function start_recording(room)
    if room._data.meet_auto_record then return; end
    local focus = get_focus_occupant(room);
    if not focus then return; end
    local already = recording_status(room);
    if already == "on" or already == "pending" then
        room._data.meet_auto_record = true;  -- a host pressed record first
        return;
    end
    for _, occupant in room:each_occupant() do
        if a_person(occupant) then
            for real_jid in occupant:each_session() do
                local session = prosody.full_sessions[real_jid];
                if session then
                    room._data.meet_auto_record = true;
                    local iq = st.iq({ type = "set", id = "meet-auto-record-" .. uuid(), from = real_jid, to = focus.nick })
                        :tag("jibri", { xmlns = "http://jitsi.org/protocol/jibri", action = "start", recording_mode = "file",
                            app_data = json.encode({ file_recording_metadata = { share = false } }) }):up();
                    module:log("info", "recording %s from its start, for %s", room.jid, occupant.bare_jid);
                    prosody.core_post_stanza(session, iq, true);
                    tell_room(room, "⏳ ההקלטה מתחילה (כ-15 שניות) — חכו להודעה שהיא פועלת. · Recording is starting (~15 s) — wait for the next line.");
                    announce_until_on(room, 60);
                    module:add_timer(CHECK_SECONDS, function ()
                        local status = recording_status(room);
                        if get_focus_occupant(room) and status ~= "on" and status ~= "pending" then
                            module:log("warn", "%s is not recording %d s after the request (jicofo says %s:"
                                .. " a failed start, or a host who stopped it)", room.jid, CHECK_SECONDS, status);
                        end
                    end);
                    return;
                end
            end
        end
    end
end

module:hook("muc-broadcast-presence", function (event)
    local room, occupant = event.room, event.occupant;
    if not room or not occupant or room._data.meet_auto_record or room.meet_auto_record_waiting then return; end
    if is_healthcheck_room(room.jid) or not a_person(occupant) then return; end
    room.meet_auto_record_waiting = true;
    module:add_timer(SETTLE_SECONDS, function ()
        room.meet_auto_record_waiting = nil;
        start_recording(room);
    end);
end);
