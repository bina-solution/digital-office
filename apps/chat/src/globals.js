// Globals for whatsapp_auto system 
// all modules in project can get info about the app state and properties from here
// and set up hooks for global events like onWhatsAppConnected
// serves as global singletons



const appProperties = {
    botNumber: null,
    is_connected: false,
    lastDisconnect: null,
    qr_text: null,
    sock: null
}


const onWhatsAppConnectedHooks = [];

const onWhatsAppConnected = async () => {
    console.log('Bot started!, connected to WhatsApp');
    console.log('Bot number:', appProperties.botNumber);
    console.log("Running Hooks...", onWhatsAppConnectedHooks);
    
    // call all hooks
    onWhatsAppConnectedHooks.forEach(hook => hook());
}



module.exports = { appProperties, onWhatsAppConnected, onWhatsAppConnectedHooks };