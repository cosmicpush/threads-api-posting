<h1>
  <img src="https://cdn.simpleicons.org/threads/000000/ffffff" alt="" height="28" align="center">
  &nbsp;Threads Image Poster
</h1>

A long-running Docker container that, on a schedule, picks a random entry from a local `quotes.json`, fetches the matching image from a Backblaze B2 bucket, publishes it to Threads, and then removes both the entry from the JSON and every version of the image from B2.

Each entry in `quotes.json` must include at least `image` (the object key in the B2 bucket) and `caption` (the post text). All other fields are ignored.

## Architecture

- **One container**, started once, kept alive by `restart: unless-stopped`.
- Inside it, [supercronic](https://github.com/aptible/supercronic) fires `python -m threads_poster` on a schedule defined in [`crontab`](./crontab).
- Schedule times are interpreted in the container's timezone, set via `TZ` in `docker-compose.yml` (default: `Asia/Kolkata`).
- One post per cron firing. Default schedule = hourly at :30, 09:30–21:30 IST (13 posts/day).

## Published image

```
ghcr.io/cosmicpush/threads-api-posting:latest
```

CI pushes three tags on every push to `master`:
- `latest` — the most recent master build
- `sha-<short>` — pinned to commit
- `master-YYYYMMDD-HHMMSS` — pinned to build time

Built for `linux/amd64` and `linux/arm64`.

## One-time VPS setup

Assume VPS user `ubuntu`, working directory `/home/ubuntu/threads-api-posting/`.

```bash
mkdir -p /home/ubuntu/threads-api-posting
cd /home/ubuntu/threads-api-posting

# Fetch only the compose file from the repo (you don't need the rest on the VPS)
curl -fsSLO https://raw.githubusercontent.com/cosmicpush/threads-api-posting/master/docker-compose.yml

# Place quotes.json here (the image generator should write to this path,
# or copy it in once)
touch quotes.json
# The container runs as uid 10001 internally — give it write permission
sudo chown 10001:10001 quotes.json

# Create .env (see "Configuration" below)
nano .env
```

## Configuration (`.env`)

```dotenv
# === Threads Graph API (required) ===
THREADS_ACCESS_TOKEN=
THREADS_USER_ID=

# === Backblaze B2 (required) ===
B2_BUCKET=12amstories
B2_KEY_ID=
B2_APPLICATION_KEY=
B2_PREFIX=threads/

# === Host path to quotes.json (required for the bind mount) ===
QUOTES_HOST_PATH=/home/ubuntu/threads-api-posting/quotes.json

# === Tuning (optional) ===
THREADS_MEDIA_WAIT_SECONDS=30
THREADS_PRESIGN_EXPIRATION_SECONDS=900

# === Telegram notifications (optional) ===
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

You do **not** need to set `QUOTES_JSON_PATH`, `LOCKFILE_PATH`, or `TZ` in `.env` — `docker-compose.yml` sets them.

## Pull and start

```bash
docker compose pull            # fetch :latest from GHCR
docker compose up -d           # start the container detached
docker compose logs -f         # follow the logs
```

The container is now alive. Supercronic will fire `python -m threads_poster` at every scheduled time and you'll see each run in the logs.

If GHCR access requires login (e.g. the package is private):

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u cosmicpush --password-stdin
```

## Common operations

```bash
# Trigger a post immediately (one-shot, doesn't disturb the daemon)
docker compose exec poster python -m threads_poster

# View recent logs
docker compose logs --tail=200 poster

# Update to a newer image after a master push
docker compose pull && docker compose up -d

# Stop the container (will not auto-restart until you `up` again)
docker compose down

# Edit the schedule — change `crontab` in the repo, push to master,
# then on the VPS:
docker compose pull && docker compose up -d
```

## Changing the schedule

Edit [`crontab`](./crontab) in this repo:

```cron
# every two hours instead of every hour
30 9,11,13,15,17,19,21 * * * python -m threads_poster

# or run only at 10:30 and 18:30
30 10,18 * * * python -m threads_poster
```

Push to master → CI builds a new image → on the VPS `docker compose pull && docker compose up -d`.

## Changing the timezone

Edit `TZ:` in `docker-compose.yml`. Any IANA timezone (`Asia/Kolkata`, `UTC`, `America/New_York`, …) works.

## Building locally (for testing changes before pushing)

```bash
docker build -t threads-poster:dev .
QUOTES_HOST_PATH=$(pwd)/quotes.json \
docker compose -f docker-compose.yml up -d
```

…or override the image temporarily with `image: threads-poster:dev` in compose.

## How a successful post is processed

1. Acquire a lockfile (`/var/lock/threads_poster/...`) — concurrent firings exit silently.
2. Pick a random entry from `quotes.json`.
3. HEAD the entry's image in B2. Missing? Prune the stale entry and exit non-zero.
4. Generate a presigned URL, create a Threads media container, wait, publish.
5. Remove the entry from `quotes.json` (atomic write via temp file + `os.replace` + `fsync`).
6. Purge every B2 version of the image via `list_object_versions` + `delete_objects` with each `VersionId` — bypasses the lifecycle rule entirely so no ghost data lingers.

## Repo layout

```
.
├── .github/workflows/docker-publish.yml   # CI: build + push to GHCR on master
├── Dockerfile                              # multi-stage; pulls supercronic, installs deps
├── crontab                                 # supercronic schedule
├── docker-compose.yml                      # deploy unit for the VPS
├── requirements.txt
├── threads_poster/                         # Python source
│   ├── __init__.py
│   ├── __main__.py
│   ├── b2_storage.py
│   ├── config.py
│   ├── main.py
│   ├── quotes_store.py
│   └── threads_api.py
└── temp/                                   # previous non-Docker implementation
```
