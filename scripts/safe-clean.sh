#!/bin/bash

# Debian Safe System Cleanup Script
# This script performs safe cleanup operations on Debian systems

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

echo -e "${GREEN}=== Debian System Cleanup Script ===${NC}\n"

# Function to show disk usage before and after
show_disk_usage() {
    echo -e "${YELLOW}Current disk usage:${NC}"
    df -h / | tail -1
    echo ""
}

# Initial disk usage
echo -e "${GREEN}[1/9] Initial Disk Usage${NC}"
show_disk_usage

# APT cleanup
echo -e "${GREEN}[2/9] Cleaning APT cache and old packages${NC}"
apt-get clean
apt-get autoclean
apt-get autoremove -y
echo -e "${GREEN}✓ APT cleanup complete${NC}\n"

# Remove old kernels (keep current and one previous)
echo -e "${GREEN}[3/9] Removing old kernel versions${NC}"
current_kernel=$(uname -r | sed 's/-generic//;s/-amd64//')
kernels_to_keep=$(dpkg -l | grep -E "linux-image-[0-9]" | grep -v "$current_kernel" | sort -V | tail -n 1 | awk '{print $2}' | sed 's/linux-image-//')
dpkg -l | grep -E "linux-image-[0-9]|linux-headers-[0-9]" | awk '{print $2}' | grep -v "$current_kernel" | grep -v "$kernels_to_keep" | xargs -r apt-get -y purge 2>/dev/null || echo "No old kernels to remove"
echo -e "${GREEN}✓ Old kernels cleaned${NC}\n"

# Clean journal logs
echo -e "${GREEN}[4/9] Cleaning systemd journal logs (keeping last 7 days)${NC}"
journalctl --vacuum-time=7d
echo -e "${GREEN}✓ Journal logs cleaned${NC}\n"

# Clean temporary files
echo -e "${GREEN}[5/9] Cleaning temporary files${NC}"
rm -rf /tmp/*
rm -rf /var/tmp/*
echo -e "${GREEN}✓ Temporary files cleaned${NC}\n"

# Clean thumbnail cache
echo -e "${GREEN}[6/9] Cleaning user thumbnail caches${NC}"
for user_home in /home/*; do
    if [ -d "$user_home/.cache/thumbnails" ]; then
        rm -rf "$user_home/.cache/thumbnails"/*
        echo "  Cleaned thumbnails for $(basename $user_home)"
    fi
done
echo -e "${GREEN}✓ Thumbnail caches cleaned${NC}\n"

# Docker cleanup
echo -e "${GREEN}[7/9] Docker Cleanup${NC}"
if command -v docker &> /dev/null; then
    echo "Removing unused Docker images..."
    docker image prune -a -f
    
    echo "Removing stopped containers..."
    docker container prune -f
    
    echo "Removing unused volumes..."
    docker volume prune -f
    
    echo "Removing unused networks..."
    docker network prune -f
    
    echo "Removing build cache..."
    docker builder prune -a -f
    
    echo -e "${GREEN}✓ Docker cleanup complete${NC}\n"
else
    echo -e "${YELLOW}Docker not installed, skipping${NC}\n"
fi

# Clean package manager cache
echo -e "${GREEN}[8/9] Cleaning package manager caches${NC}"
rm -rf /var/cache/apt/archives/*.deb
echo -e "${GREEN}✓ Package caches cleaned${NC}\n"

# Find and report large files
echo -e "${GREEN}[9/9] Finding largest files and directories${NC}"
echo -e "${YELLOW}Top 10 largest directories in /var:${NC}"
du -h /var 2>/dev/null | sort -rh | head -10

echo -e "\n${YELLOW}Top 10 largest files in /var/log:${NC}"
find /var/log -type f -exec du -h {} + 2>/dev/null | sort -rh | head -10

# Final disk usage
echo -e "\n${GREEN}=== Cleanup Complete ===${NC}\n"
show_disk_usage

echo -e "${GREEN}Summary of cleanup actions performed:${NC}"
echo "  • APT cache and old packages removed"
echo "  • Old kernel versions removed"
echo "  • System journal logs truncated"
echo "  • Temporary files cleaned"
echo "  • Thumbnail caches cleared"
echo "  • Docker images, containers, volumes, and cache cleaned"
echo "  • Package manager caches cleared"
echo ""
echo -e "${YELLOW}Note: You may want to review large files listed above for manual cleanup${NC}"
echo -e "${YELLOW}Note: You may want to review large files listed above for manual cleanup${NC}"