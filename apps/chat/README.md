# WhatsApp Hacohanim Bot

## Overview
The WhatsApp Hacohanim Bot is a feature-rich application designed to manage WhatsApp interactions for the Hacohanim organization. It includes an admin panel, a bot for automated messaging, and various utilities for managing users, referrals, and campaigns.

## Features

### Bot Features
- **Automated Messaging**: Handles user interactions, including registration, referrals, and daily message limits.
- **Referral System**: Tracks referrals and rewards users based on milestones.
- **Menu System**: Provides users with options like lottery information, referral status, and bot details.
- **Daily Message Limit**: Restricts the number of messages a user can send per day.

### Admin Panel Features
- **Dashboard**: Displays bot connection status, user statistics, and quick actions.
- **User Management**: Allows admins to view, delete, back up, and restore user data.
- **Broadcast Messaging**: Enables admins to send messages to all users.
- **Document Sending**: Allows admins to send PDF documents to specific users.

### Security Features
- **Authentication**: Admin panel access is secured with username and password.
- **Rate Limiting**: Protects against brute force and denial-of-service attacks.
- **File Upload Validation**: Ensures only valid file types are uploaded.
- **Session Management**: Uses secure sessions for user authentication.

## Project Structure

```
chat/
├── src/
│   ├── api/                # API and middleware
│   │   ├── controller.js   # Handles API logic
│   │   ├── middleware/     # Middleware for auth, rate limiting, uploads
│   │   ├── ui/             # EJS templates for admin panel
│   │   └── api.js          # API routes
│   ├── whatsapp/           # WhatsApp bot logic
│   ├── data/               # Database and data utilities
│   ├── config.js           # Configuration settings
│   └── globals.js          # Global app state
├── tests/                  # End-to-end tests
├── Dockerfile              # Docker configuration
├── docker-compose.yml      # Docker Compose configuration
├── README.md               # Project documentation
└── package.json            # Node.js dependencies and scripts
```

## Installation

### Prerequisites
- Node.js (v18 or higher)
- Docker (optional, for containerized deployment)

### Steps
1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd chat
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Set up environment variables:
   - Copy `.env.example` to `.env` and update the values as needed.

4. Start the application:
   ```bash
   npm start
   ```

## Usage

### Admin Panel
- Access the admin panel at `http://localhost:3000`.
- Log in using the credentials specified in the `.env` file.

### Bot
- The bot automatically connects to WhatsApp and starts handling messages.

## Testing
Run end-to-end tests using Jest:
```bash
npm run test:e2e
```

## Deployment

### Docker
1. Build the Docker image:
   ```bash
   docker build -t chat .
   ```
2. Run the container:
   ```bash
   docker-compose up
   ```

### Google Cloud
- Use the `cloudbuild.yaml` file for deploying to Google Cloud.

## Contributing
Contributions are welcome! Please follow the guidelines below:
- Fork the repository.
- Create a new branch for your feature or bug fix.
- Submit a pull request with a detailed description of your changes.

## License
This project is licensed under the MIT License.


