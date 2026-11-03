-- mod_meet_share_notice — apps/meet: tells the person who shares a screen that the server has it
-- (DGO-832, the owner 2026-10-21: «when I click share screen, I get no feedback about my screen
-- started being shared … It must be clear that it's working»).
--
-- A phone app shows no preview of its own shared screen (Jitsi's design on phones), and Android's
-- picker says nothing once it closes. So the word comes from the server: the moment a participant's
-- presence first announces a live desktop source (its SourceInfo: videoType "desktop", not muted),
-- this sends that participant, and only them, a chat message from the room itself. It says the
-- screen is shared, and recorded when it is; when the share ends, it says that too.
--
-- WHY A ROOM MESSAGE AND NOT JITSI'S "SYSTEM" ONE. The stanza Jitsi's own mod_system_chat_message
-- sends (a json-message) is shown as a chat line only: the client gives it a timestamp, and a message
-- with a timestamp raises no pop-up (jitsi-meet react/features/chat/middleware.ts,
-- _handleReceivedMessage: notify only when `!timestamp`). A groupchat message from the room's bare
-- JID, with a body and a display name, is read by lib-jitsi-meet (ChatRoom.onMessage) as a live
-- chat message from a non-participant: the page and the phone apps pop it up, play the message
-- sound, and keep it in the chat. It is routed to the sharer's own sessions only, so nobody else sees it.
--
-- Not for jicofo, the recorder, or jicofo's health-check rooms. Loaded on the conference MUC
-- component (XMPP_MUC_MODULES). Off with the module: it has no switch of its own.
local st = require "util.stanza";
local json = require "cjson.safe";   -- reads the clients' SourceInfo
local util = module:require "util";
local is_focus = util.is_focus;
local is_jibri = util.is_jibri;
local is_healthcheck_room = util.is_healthcheck_room;
local get_focus_occupant = util.get_focus_occupant;

local SENDER = "פגישות וידאו";
-- …and, before it can happen, what took the owner's voice out of a 21-minute recording (DGO-959): on
-- Android 13+ the Jitsi app keeps its microphone while another app is shown only through a foreground
-- service, and it starts that service (JitsiMeetOngoingConferenceService.launch, at join) only when
-- notifications AND the microphone are allowed. mod_meet_silent_mic tells whoever it happens to; this
-- says so first, while the sharer is still looking at Jitsi.
local PHONE = " באנדרואיד: הפעל התראות לאפליקציית Jitsi (הגדרות ← אפליקציות ← Jitsi Meet ← התראות), אחרת אנדרואיד מנתק את המיקרופון כשעוברים לאפליקציה אחרת; אם הפעלת אותן עכשיו, צא מהפגישה והיכנס שוב.";
local STARTED = "✅ המסך שלך משותף עכשיו — כל המשתתפים רואים אותו." .. PHONE;
local STARTED_RECORDED = "✅ המסך שלך משותף עכשיו ומוקלט — כל המשתתפים רואים אותו." .. PHONE;
local STOPPED = "שיתוף המסך שלך הופסק.";

-- Does this presence announce a live screen share? Jitsi's clients write their sources here.
local function shares(stanza)
    local text = stanza and stanza:get_child_text("SourceInfo");
    local sources = text and json.decode(text);
    if type(sources) ~= "table" then return false; end
    for _, source in pairs(sources) do
        if type(source) == "table" and source.videoType == "desktop" and source.muted == false then
            return true;
        end
    end
    return false;
end

-- Is the room being recorded? jicofo says so in its own presence, as every client reads it ("pending"
-- in the seconds the recorder takes to join: mod_meet_auto_record has asked for it).
local function recorded(room)
    local focus = get_focus_occupant(room);
    local presence = focus and focus:get_presence();
    local status = presence and presence:get_child("jibri-recording-status", "http://jitsi.org/protocol/jibri");
    return status ~= nil and (status.attr.status == "on" or status.attr.status == "pending");
end

local function tell(room, occupant, message)
    for real_jid in occupant:each_session() do
        room:route_stanza(st.message({ from = room.jid, to = real_jid, type = "groupchat" })
            :tag("body"):text(message):up()
            :tag("display-name", { xmlns = "http://jitsi.org/protocol/display-name" }):text(SENDER):up());
    end
end

module:hook("muc-broadcast-presence", function (event)
    local room, occupant, stanza = event.room, event.occupant, event.stanza;
    if not room or not occupant or not stanza or is_healthcheck_room(room.jid)
        or is_focus(occupant.nick) or is_jibri(occupant) then
        return;
    end
    room.meet_sharing = room.meet_sharing or {};
    if stanza.attr.type == "unavailable" then          -- they left: nothing to say, forget them
        room.meet_sharing[occupant.nick] = nil;
        return;
    end
    local now = shares(stanza);
    if now == (room.meet_sharing[occupant.nick] or false) then return; end
    room.meet_sharing[occupant.nick] = now;
    if now then
        tell(room, occupant, recorded(room) and STARTED_RECORDED or STARTED);
    else
        tell(room, occupant, STOPPED);
    end
end);
