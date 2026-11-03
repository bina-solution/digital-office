
// ── apps/meet: the office's additions, appended by the web image after interface_config.js ──

interfaceConfig.APP_NAME = 'פגישות וידאו';
interfaceConfig.PROVIDER_NAME = 'בינה';

// The office's default language wins over the browser's (see config.defaultLanguage).
interfaceConfig.LANG_DETECTION = false;

// No jitsi.org watermark link, no community support link. MOBILE_APP_PROMO stays Jitsi's (on): it is
// the phone page that leads to the Jitsi Meet app, which can share the screen (custom-config.js, DGO-829).
interfaceConfig.SHOW_JITSI_WATERMARK = false;
interfaceConfig.SHOW_BRAND_WATERMARK = false;
interfaceConfig.JITSI_WATERMARK_LINK = '';
interfaceConfig.SUPPORT_URL = '';

// The welcome page's own extension point: the card in welcomePageAdditionalCard.html.
interfaceConfig.DISPLAY_WELCOME_PAGE_ADDITIONAL_CARD = true;

interfaceConfig.DEFAULT_LOCAL_DISPLAY_NAME = 'אני';
interfaceConfig.DEFAULT_REMOTE_DISPLAY_NAME = 'משתתף';

// The recorder's page draws no blurred copy of the big video behind it (fireplace, 2026-10-27, load ramps): in a box
// with no GPU that CSS blur is redrawn in software every frame, and the recorder spent ~1.25 cores drawing a meeting
// with a shared screen. People's own pages keep it.
if (typeof location !== 'undefined' && /iAmRecorder=true/.test(location.hash || '')) {
    interfaceConfig.DISABLE_VIDEO_BACKGROUND = true;
}
