// Use PM2 to ensure your bot stays running
// ecosystem.config.js
module.exports = {
    apps: [{
      name: "whatsapp-bot",
      script: "index.js",
      watch: true,
      max_memory_restart: "500M",
      env: {
        NODE_ENV: "production"
      }
    }]
  }