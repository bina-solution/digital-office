
// ── apps/meet: the office's additions, appended by the web image after its generated config.js ──

// The XMPP addresses follow the page's OWN host, so one container serves meet.<domain>,
// meet.localhost and a linked office's alias alike. The image would write PUBLIC_URL's host here,
// and always as wss://, which is wrong on a plain-http .localhost office.
// Only in a browser page: Jitsi's phone apps evaluate this file with no `location`, and keep the
// addresses the image wrote (PUBLIC_URL's host, which on a domain office is the right one).
(function () {
    if (typeof location === 'undefined' || !location.host) { return; }
    var dir = typeof subdir === 'string' ? subdir : '';
    config.bosh = '/' + dir + 'http-bind';
    config.websocket = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/' + dir + 'xmpp-websocket';
})();

// Hebrew is the office's language. interface_config sets LANG_DETECTION off, so a browser set to
// English still opens in Hebrew; a person who picks another language keeps it (Jitsi stores it).
config.defaultLanguage = 'he';

// Everything stays on the office's own servers: no third-party avatars, GIFs, analytics or STUN.
config.disableThirdPartyRequests = true;
config.gravatar = { disabled: true };
config.giphy = { enabled: false };
config.analytics = { disabled: true };
config.feedbackPercentage = 0;
config.p2p = Object.assign(config.p2p || {}, { enabled: false });

// A name on every participant: the meeting's record is who was there.
config.requireDisplayName = true;
config.prejoinConfig = Object.assign(config.prejoinConfig || {}, { enabled: true });

// Deep linking is left as Jitsi ships it (DGO-829): on a phone, a meeting link opens Jitsi's own page
// first, "join in the app" or "join in the browser". A phone browser cannot capture the screen
// (Chrome on Android, Safari on iOS), so in it Jitsi shows no share button; this was the owner's
// phone on 2026-10-20 (Chrome on Android, in vps1's log). The Jitsi Meet app can share, and it is
// handed the whole link, ?jwt= included, so a host is the moderator there too. The app runs no page
// script; its meetings are recorded by the server (prosody/mod_meet_auto_record.lua, DGO-831).
// Computers never see the page.

config.disableInviteFunctions = false;

// Recording is the office's: Jibri writes it to the office's own volume (meet_recordings), and the
// door's /recordings lists it. So the "stored for 24 hours" warning (jitsi.org's service) is not true here, a
// local, in-the-browser recording would leave the record on one laptop, and everyone joining is
// told before they join that the meeting may be recorded.
config.recordingService = Object.assign(config.recordingService || {}, { enabled: true, sharingEnabled: false, hideStorageWarning: true });
config.recordings = Object.assign(config.recordings || {}, { showPrejoinWarning: true, showRecordingLink: false, suggestRecording: false });
config.localRecording = Object.assign(config.localRecording || {}, { disable: true });
// Every meeting a host opens is recorded from its start by the server, from any client
// (prosody/mod_meet_auto_record.lua; MEET_AUTO_RECORD in .env, 0 = only from the record button).

// Live captions from each person's own browser (web/plugin.head.html; prosody/mod_meet_captions.lua writes
// them down): 'on' for every person on a computer browser that can recognize speech, 'off' for nobody.
// lang is the speech language until a person picks another on the chip (an English Jitsi = en-US).
// The recognizer is the browser's speech service (Chrome: Google's), so the voice of whoever is captioned
// goes there; the recording and its transcript stay on the office's server.
// OFF (the owner, 2026-10-27: «זה שולח לשירות חיצוני את הקול? … הכל חייב להיות מקומי או בדפדפן או אצלנו»): the
// browsers' recognizers send the voice out (Chrome: Google; no on-device Hebrew model), so captions come from the
// office's own transcriber instead (jibri/watch.py, MEET_LIVE_CAPTIONS). 'on' only for a recognizer that runs locally.
config.dgoCaptions = Object.assign({ mode: 'off', lang: 'he-IL' }, config.dgoCaptions || {});

// THE 2-CORE OFFICE (fireplace, 2026-10-27, measured with load ramps: one full page + light participants with
// moving cameras, their own Hebrew speech and a shared screen; README «Load, measured on the 2-core office»).
// The recorder is the first thing a growing meeting spends on. Its big cost was Jitsi's blurred background
// (custom-interface_config.js turns it off on the recorder's page: 1.25 → 0.57 cores with a shared screen). Here:
//  - the recorder's page receives at most RECORDER_LAST_N videos (the last speakers; the shared screen first),
//    so its CPU stops growing with the number of cameras. People's own pages are untouched;
//  - VP8 first for cameras: no difference for the server (measured), but AV1 is the heaviest codec for the
//    participants' own laptops (the test laptop: 90-99 % CPU at 3-4 people with AV1, 51-62 % with VP8).
config.videoQuality = Object.assign(config.videoQuality || {}, {
    codecPreferenceOrder: ['VP8', 'VP9', 'AV1', 'H264'],
    mobileCodecPreferenceOrder: ['VP8', 'H264', 'VP9', 'AV1']
});
(function () {
    var RECORDER_LAST_N = 6;
    if (typeof location !== 'undefined' && /iAmRecorder=true/.test(location.hash || '')) {
        config.channelLastN = RECORDER_LAST_N;
    }
})();

// ── MT-11 (fireplace, 2026-10-29, lane R2-L7 — STAGED: applied by apply-web-config.sh with no meeting on, then a restart
// of `meet`). What the owner ran into on a phone browser (Samsung Internet) and on a computer, in fpg2 and fpg105.
// Researched against this exact release (jitsi-meet 1.0.9442 = stable/jitsi-meet_11248, lib-jitsi-meet v2205.0.0).

// THE «BARKING» (fpg105 [1:11]): this office's server speaks to the room in chat messages (prosody/mod_meet_silent_mic.lua
// on every silent/back change; the live caption lines), and this release plays its incoming-message sound for every
// message received while the chat is closed, delay-stamped ones too (react/features/chat/middleware.ts). Off on the pages
// and in the phone apps; a message still pops up.
config.disabledSounds = (config.disabledSounds || []).concat(['INCOMING_MSG_SOUND']);

// SHARING FROM A COMPUTER (fpg105 [0:25], the endless mirror): lib-jitsi-meet builds Chrome's getDisplayMedia request from
// screenShareSettings — its own defaults made explicit, and the picker opens on tabs. The meeting's own tab is never
// offered, so a shared tab cannot mirror; a shared WINDOW or SCREEN that shows the meeting does (Jitsi draws your own share).
config.screenShareSettings = Object.assign({}, config.screenShareSettings, {
    desktopDisplaySurface: 'browser',
    desktopSelfBrowserSurface: 'exclude',
    desktopPreferCurrentTab: false,
    desktopSurfaceSwitching: 'include'
});

// «ADD PEOPLE» ON A PHONE BROWSER (fpg2 [02:07]): the page has Invite, but up to 370 px wide the bar holds only microphone,
// camera and chat. Each array replaces Jitsi's bar of the same length (3 buttons up to 370 px, 4 up to 420, 5 up to 470);
// computers keep theirs. Browser pages only: the phone app evaluates this file too (no `location`), and its own 4- and
// 5-button bars carry «⋯» and hang-up, which a same-length array would replace.
(function () {
    if (typeof location === 'undefined' || !location.host) { return; }
    config.mainToolbarButtons = [
        ['microphone', 'camera', 'chat', 'participants-pane', 'invite'],
        ['microphone', 'camera', 'chat', 'invite'],
        ['microphone', 'camera', 'invite']
    ];
})();

// CAMERA OFF ON JOINING, ONE'S OWN PICTURE SHOWN (fpg2 [04:33], [1:17:35]). In this release the browser's STORED Jitsi
// settings outrank config.js (getPropertyValue: jwt → #config. → stored → config) and are stored as «camera on» from the
// first visit, so config.startWithVideoMuted alone changes nothing; a «Hide self view» once clicked stays (config OR
// stored). So each page load stores camera off and self-view on; a person can still turn either back during a meeting,
// and the next join starts the same. Not on the recorder's page; the phone apps keep their own settings.
config.startWithVideoMuted = true;
(function () {
    if (typeof location === 'undefined' || !location.host || /iAmRecorder=true/.test(location.hash || '')) { return; }
    try {
        var key = 'features/base/settings';
        var stored = JSON.parse(localStorage.getItem(key) || '{}') || {};
        stored.startWithVideoMuted = true;
        stored.disableSelfView = false;
        localStorage.setItem(key, JSON.stringify(stored));
    } catch (e) { /* storage blocked: Jitsi's defaults stay (camera on) */ }
})();
