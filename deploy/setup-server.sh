#!/bin/sh
# One-time preparation of a fresh Ubuntu server (22.04 or 24.04). Run as root:
#
#   sudo sh deploy/setup-server.sh
#
# It installs Docker, turns on automatic security updates, closes every port
# but SSH, HTTP and HTTPS, adds swap, and schedules the nightly backup.
set -eu

[ "$(id -u)" = "0" ] || { echo "Run with sudo." >&2; exit 1; }
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y docker.io docker-compose-v2 unattended-upgrades ufw git

# Security updates install themselves; the server restarts at 09:30 UTC when one needs it.
cat > /etc/apt/apt.conf.d/52achalara-updates <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "09:30";
CONF

# The server's own firewall, as well as the one in the Lightsail console.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

# Room to build the images on a small server.
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Container logs are capped, so they cannot fill the disk.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'CONF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5" } }
CONF
systemctl enable docker
systemctl restart docker

# Nightly at 07:15 UTC, after the day's jobs and before the US market opens.
mkdir -p /srv/achalara-backups
chmod 700 /srv/achalara-backups
chmod +x "$DEPLOY_DIR/backup.sh" "$DEPLOY_DIR/restore.sh"
echo "15 7 * * * root $DEPLOY_DIR/backup.sh >> /srv/achalara-backups/cron.log 2>&1" > /etc/cron.d/achalara-backup
chmod 644 /etc/cron.d/achalara-backup

echo "Server prepared. Next: create deploy/.env, then 'docker compose up -d --build' in $DEPLOY_DIR."
