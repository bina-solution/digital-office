#!/bin/bash

# ==============================================================================
#   Robust Deployment Tools Installation Script for Debian/Ubuntu
#
#   This script installs:
#   - Git (Version Control)
#   - Docker Engine & Docker Compose (Containerization)
#   - Google Gemini CLI (via Node.js/npm)
#
#   Features:
#   - Idempotent: Checks if software is already installed before trying to install.
#   - Robust: Exits immediately on error (`set -e`, `set -o pipefail`).
#   - User-Aware: Detects if running as root and uses `sudo` only if necessary
#     and available.
# ==============================================================================

# Exit immediately if a command exits with a non-zero status.
set -e
# Treat errors in a pipeline as a failure.
set -o pipefail

# --- Helper for logging ---
log() {
  echo "--- $1 ---"
}

# --- Step 0: Check for root privileges and set SUDO command ---
SUDO=''
if [ "$(id -u)" -ne 0 ]; then
  log "Script not run as root. Checking for sudo..."
  if ! command -v sudo &> /dev/null; then
    echo "Error: This script requires root privileges. Please run as root or ensure 'sudo' is installed." >&2
    exit 1
  fi
  SUDO='sudo'
  log "Sudo found. Proceeding with sudo for privileged commands."
else
  log "Script run as root. No sudo needed."
fi

# --- Step 1: System Update ---
update_system() {
  log "Updating package lists"
  $SUDO apt-get update
  echo "Package lists updated successfully."
}

# --- Step 2: Install Git ---
install_git() {
  log "Checking for Git"
  if command -v git &> /dev/null; then
    echo "Git is already installed."
    return
  fi

  log "Installing Git"
  $SUDO apt-get install -y git
  echo "Git installed successfully."
}

# --- Step 3: Install Docker and Docker Compose ---
# Docker CE 28.5.2 + compose 2.40.3, PINNED and held — the same engine as packaging/macos/engine.yaml,
# the Windows distro and the production VPS. Docker 29 raised the daemon's hard API floor to 1.40,
# and traefik v3.3's docker client speaks 1.24: on 29 traefik starts, reports healthy, discovers
# zero routers and every host 404s (CLAUDE.md, "Docker 29 does not work, and fails silently").
# An unpinned `apt-get install docker-ce` installs 29 today, so a fresh machine provisioned by this
# script used to be broken on arrival — the remote-dgo-extend app provisions every new office here.
DOCKER_MAJOR=28
DOCKER_VER=5:28.5.2
COMPOSE_VER=2.40.3
install_docker() {
  log "Checking for Docker"
  if command -v docker &> /dev/null; then
    local have
    have="$(docker version --format '{{.Server.Version}}' 2>/dev/null || docker --version | sed -E 's/[^0-9]*([0-9.]+).*/\1/')"
    if [ "${have%%.*}" != "${DOCKER_MAJOR}" ]; then
      echo "Error: Docker ${have} is installed; this platform needs Docker ${DOCKER_MAJOR}.x." >&2
      echo "       Re-run with BBOX_REPLACE_DOCKER=1 to replace it (containers stop; volumes are kept)." >&2
      [ "${BBOX_REPLACE_DOCKER:-0}" = 1 ] || exit 3
    elif docker compose version &> /dev/null; then
      echo "Docker ${have} and the Compose plugin are installed."
      return
    fi
  fi

  log "Installing Docker ${DOCKER_VER#5:} and Docker Compose ${COMPOSE_VER} (pinned)"

  # Install prerequisites
  $SUDO apt-get install -y ca-certificates curl

  # The distro decides the repository path AND the package suffix (debian vs ubuntu).
  local distro codename
  distro="$(. /etc/os-release && echo "$ID")"
  codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  case "$distro" in debian|ubuntu) ;; *) echo "Error: unsupported distro '$distro' (debian or ubuntu)" >&2; exit 1 ;; esac

  $SUDO install -m 0755 -d /etc/apt/keyrings
  $SUDO curl -fsSL "https://download.docker.com/linux/${distro}/gpg" -o /etc/apt/keyrings/docker.asc
  $SUDO chmod a+r /etc/apt/keyrings/docker.asc
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${distro} \
    ${codename} stable" | \
    $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null
  $SUDO apt-get update

  # Resolve the exact package versions for THIS distro/codename from the repo itself, rather than
  # hand-writing a suffix per release ("5:28.5.2-1~debian.12~bookworm", "…~ubuntu.24.04~noble").
  local v c
  v="$(apt-cache madison docker-ce | awk '{print $3}' | grep -F "${DOCKER_VER}-" | head -1)"
  c="$(apt-cache madison docker-compose-plugin | awk '{print $3}' | grep -F "${COMPOSE_VER}-" | head -1)"
  [ -n "$v" ] || { echo "Error: docker-ce ${DOCKER_VER} is not published for ${distro} ${codename}" >&2; exit 1; }
  [ -n "$c" ] || { echo "Error: docker-compose-plugin ${COMPOSE_VER} is not published for ${distro} ${codename}" >&2; exit 1; }

  $SUDO apt-mark unhold docker-ce docker-ce-cli docker-compose-plugin >/dev/null 2>&1 || true
  $SUDO apt-get install -y --allow-downgrades "docker-ce=${v}" "docker-ce-cli=${v}" containerd.io \
    docker-buildx-plugin "docker-compose-plugin=${c}"
  $SUDO apt-mark hold docker-ce docker-ce-cli docker-compose-plugin
  $SUDO systemctl enable --now docker >/dev/null 2>&1 || true
  echo "Docker ${v} and Compose ${c} installed and held."

  # --- Post-installation steps for Docker ---
  # Add the current user to the docker group to avoid using sudo
  if [ -n "$SUDO" ]; then
    log "Adding current user to the docker group..."
    # Get the original user who invoked sudo
    ORIGINAL_USER=${SUDO_USER:-$USER}
    $SUDO usermod -aG docker "$ORIGINAL_USER"
    log "User $ORIGINAL_USER added to the docker group."
    log "You will need to log out and log back in for this to take effect."
    # The 'newgrp' command is tricky to use in scripts as it replaces the shell process.
    # We will not run it here, and the user should log out and back in.
  fi
}

# --- Step 4: Install Gemini CLI ---
install_gemini_cli() {
  log "Checking for Gemini CLI"
  if command -v gemini &> /dev/null; then
    echo "Gemini CLI is already installed."
    return
  fi

  log "Installing Gemini CLI"

  # Check for Node.js and npm first
  if ! command -v node &> /dev/null || ! command -v npm &> /dev/null; then
    log "Node.js/npm not found. Installing Node.js v22.x..."
    # The nodesource script needs to be piped to bash, using sudo if available.
    if [ -n "$SUDO" ]; then
      curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO -E bash -
    else
      # Running as root, no need for sudo
      curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    fi
    $SUDO apt-get install -y nodejs
    echo "Node.js and npm installed successfully."
  else
    echo "Node.js and npm are already installed."
  fi

  log "Installing @google/gemini-cli via npm..."
  $SUDO npm install -g @google/gemini-cli
  echo "Gemini CLI installed successfully."
}

# --- Step 5: Setup Docker Network ---
setup_docker_network() {
  log "Setting up Docker network"
  if ! docker network inspect traefik-network &>/dev/null; then
    log "Creating 'traefik-network' Docker network..."
    docker network create traefik-network
    log "'traefik-network' created successfully."
  else
    log "'traefik-network' already exists. Skipping creation."
  fi
}

# --- Step 6: Setup Portainer Password ---
setup_portainer_password() {
  log "Setting up Portainer password file"
  PASSWORD_FILE="apps/portainer/portainer_password.txt"
  if [ ! -f "$PASSWORD_FILE" ]; then
    log "Creating $PASSWORD_FILE with a random password..."
    if command -v openssl &> /dev/null; then
        openssl rand -base64 24 > "$PASSWORD_FILE"
    else
        head /dev/urandom | tr -dc A-Za-z0-9 | head -c 32 > "$PASSWORD_FILE"
    fi
    log "$PASSWORD_FILE created successfully."
  else
    log "$PASSWORD_FILE already exists. Skipping creation."
  fi
}


# --- Step 7: setup default env variables --- 
setup_env_variables() {
  log "Setting up default environment variables"

  ENV_FILE=".env"
  ENV_EX_FILE=".env.ex"
  if [ ! -f "$ENV_FILE" ] && [ -f "$ENV_EX_FILE" ]; then
    log "Copying default environment variables from $ENV_EX_FILE to $ENV_FILE"
    cp "$ENV_EX_FILE" "$ENV_FILE"
    echo "Default environment variables set up successfully."
  else
    if [ -f "$ENV_FILE" ]; then
      log "$ENV_FILE already exists. Skipping setup."
    else
      log "No default environment file found. Skipping setup."
    fi
  fi
}

# --- Step 8: Verification ---
verify_installations() {
  echo
  echo "===================================================================="
  log "Verifying Installations"
  echo "===================================================================="
  
  # Use command -v to be sure, then get version
  command -v git &> /dev/null && git --version || echo "Git: Not Found"
  command -v docker &> /dev/null && docker --version || echo "Docker: Not Found"
  command -v docker &> /dev/null && docker compose version || echo "Docker Compose: Not Found"
  command -v gemini &> /dev/null && gemini --version || echo "Gemini CLI: Not Found"
  echo
}

# --- Main Execution Logic ---
main() {
  echo "===================================================================="
  echo " Starting Deployment Tools Installation Script for Debian/Ubuntu"
  echo "===================================================================="
  
  update_system
  install_git
  install_docker
  # The Gemini CLI is a personal operator tool, not part of the platform — opt in. A remote office
  # provisioned by apps/dgo-extend does not want Node.js + a global npm package on its machine.
  [ "${BBOX_WITH_GEMINI:-0}" = 1 ] && install_gemini_cli
  setup_docker_network
  setup_portainer_password
  setup_env_variables
  verify_installations
  
  
  echo "===================================================================="
  echo " Installation Complete!"
  echo "===================================================================="
  echo
  echo "Next Steps:"
  echo "1. Git: Configure your user with 'git config --global user.name \"Your Name\"' and 'git config --global user.email \"you@example.com\"'."
  echo "2. Docker: To run Docker commands without 'sudo', add your user to the 'docker' group with '$SUDO usermod -aG \$USER'. You will need to log out and log back in for this to take effect."
  echo "3. Gemini CLI: Run 'gemini' to start the tool. It may prompt you to log in with your Google account."
  echo
}

# --- Run the main function ---
main

