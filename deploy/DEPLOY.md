# Running Achalara on one server

Everything runs on a single Ubuntu server as three containers: the database, the backend, and
the web front (the built app plus HTTPS). The app and its API share one address, so there is
one certificate and no cross-site cookie to configure.

```
browser ──https──> web (Caddy) ──/api, /health──> backend (FastAPI + daily jobs) ──> db (Postgres)
                       └── everything else: the built app
```

Files here:

| File | What it is |
|---|---|
| `docker-compose.yml` | The three containers |
| `web.Dockerfile`, `Caddyfile` | Builds the app and serves it over HTTPS |
| `.env.example` | The settings the server needs; copy to `.env` there |
| `setup-server.sh` | One-time preparation of a fresh server |
| `backup.sh`, `restore.sh` | Nightly database backup, and putting one back |

## Rules that must hold

- **Run one backend, never two.** The daily jobs run inside it; a second copy runs each twice.
- **Only one place may run the daily jobs against the brokerage.** Once the server is live, set
  `SCHEDULER_ENABLED=false` in the `.env` of any development machine that holds the same
  brokerage keys. Two schedulers would spend the brokerage's daily limits twice.
- **`deploy/.env` holds the secrets.** It exists only on the server, readable by its owner
  (`chmod 600`), and is never committed.
- **The database is not reachable from outside.** It publishes no port; do not add one.

## First deployment

### 1. Create the server (AWS console)

1. Lightsail → Create instance → Linux, **Ubuntu 24.04 LTS**, in a US region.
2. Size: **2 GB memory** (the $12 plan).
3. After it starts: Networking → **attach a static IP**. Note the address.
4. Networking → firewall: keep **SSH (22)**, add **HTTP (80)** and **HTTPS (443)**. Restrict SSH
   to your own IP address if it is stable.
5. Snapshots → turn on **automatic snapshots**.

### 2. Point the name at it (Cloudflare)

DNS → Records, both with the proxy **off** (grey cloud, "DNS only"), so the server can obtain
its own certificate:

| Type | Name | Content |
|---|---|---|
| A | `@` | the static IP |
| A | `www` | the static IP |

### 3. Prepare the server

Connect with SSH (the Lightsail console has a browser terminal), then:

```sh
sudo mkdir -p /srv && sudo chown "$USER" /srv
git clone https://github.com/<owner>/achalara.git /srv/achalara
sudo sh /srv/achalara/deploy/setup-server.sh
sudo usermod -aG docker "$USER" && newgrp docker
```

### 4. Settings

```sh
cd /srv/achalara/deploy
cp .env.example .env && chmod 600 .env
nano .env
```

Fill in `DOMAIN`, a long random `POSTGRES_PASSWORD` (`openssl rand -base64 32`), and the
market-data and brokerage keys. Use keys issued for production, not ones that have been in a
development file.

### 5. Start

```sh
docker compose up -d --build      # the first build takes several minutes
docker compose ps                  # db and backend should say "healthy"
curl -s https://<your domain>/health
```

The certificate is issued on the first request; allow a minute.

### 6. Data and the first login

Either start empty, or bring an existing database across.

**Start empty:** create the first advisor login.

```sh
docker compose exec backend python -m app.cli create-advisor --email you@example.com --name "Your Name"
```

**Bring a database across:** on the machine that has it,

```sh
pg_dump -Fc -U <user> <database> > achalara.dump
scp achalara.dump <server>:/srv/achalara-backups/
```

then on the server,

```sh
cd /srv/achalara/deploy && ./restore.sh /srv/achalara-backups/achalara.dump
```

Logins come across with the data. Delete the dump from both machines afterwards.

### 7. After it is live

- Set `SCHEDULER_ENABLED=false` on the development machine (see the rules above).
- In the brokerage provider's dashboard, set the webhook address to
  `https://<your domain>/api/v1/webhooks/snaptrade`.
- Add a free uptime monitor on `https://<your domain>/health` that emails you.

## Routine

**Times.** The server's clock is US Eastern. Security updates install themselves, and when one
needs a restart the server restarts at 2:30am Eastern; the site is back within about a minute.
The app's own daily jobs keep their UTC times.

**Update to the latest code**

```sh
cd /srv/achalara && git pull
cd deploy && docker compose up -d --build
```

Database changes are applied by the backend as it starts. The site is unavailable for under a
minute while the containers restart.

**Look at what is happening**

```sh
docker compose ps
docker compose logs --tail 100 backend
tail -3 /srv/achalara-backups/backup.log
df -h /        # disk space
```

**Backups** run nightly at 3:15am Eastern into `/srv/achalara-backups`, keeping 14 days. The
server's automatic snapshots carry those files off the disk. Every few months, prove one
restores: copy a dump to another machine and load it into a scratch database.

**Restore**

```sh
cd /srv/achalara/deploy && ./restore.sh /srv/achalara-backups/achalara-<date>.dump
```

This replaces the whole database and asks you to confirm first.

## If something is wrong

| What you see | Likely cause | What to do |
|---|---|---|
| Site does not load at all | Server stopped, or the name no longer points at it | Lightsail console: is the instance running? Cloudflare: do the A records still hold the static IP? |
| Browser warns about the certificate | The name was not pointing here when the server started, or the proxy is on | Fix the DNS record (proxy off), then `docker compose restart web` |
| Page loads but sign-in fails for everyone | Backend or database is down | `docker compose ps`, then `docker compose logs --tail 100 backend` |
| A day's figures are missing | The server was down at the daily capture | It catches up when the backend starts; restart it the same day |
| Disk is full | Old images from many rebuilds | `docker image prune -af` |

**The server is lost entirely:** create a new instance from the latest snapshot in the
Lightsail console and attach the same static IP to it. Nothing else changes.
