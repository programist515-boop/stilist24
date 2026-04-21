# Deploy — how stilist24.com actually runs

The production site is already up at https://stilist24.com and
automatically redeploys on every push to `main`. This document
describes that setup so a new maintainer can debug, roll back, or
rebuild it without archaeology.

---

## Architecture

Single VPS (`194.67.99.214`, `/home/ubuntu/stilist24-com`, Ubuntu), one
Docker Compose stack, host-level nginx for TLS and routing.

```
browser
  │  HTTPS
  ▼
nginx  (port 443 on host, Ubuntu's nginx/1.24)
  │
  ├── /        → 127.0.0.1:3002     (web: Next.js standalone)
  ├── /api/…   → 127.0.0.1:8002     (api: FastAPI, strip /api prefix)
  └── /s3/…    → 127.0.0.1:9000     (minio: public wardrobe photos)

docker compose -p stilist24com
  ├── api            (image: stilist24com-api,  FastAPI + alembic upgrade on start)
  ├── web            (image: stilist24com-web,  Next.js standalone)
  ├── db             (postgres:16-alpine, volume: postgres_data)
  ├── redis          (redis:7-alpine, volume: redis_data)
  ├── minio          (minio/minio, volume: minio_data)
  └── createbuckets  (one-shot: creates ai-stylist bucket + anonymous download ACL)
```

Nginx config lives on the server (not in git). Port 443 terminates TLS
for `stilist24.com`. Hostnames in the browser all end in
`stilist24.com` — there are no `api.` / `media.` subdomains. The API
lives at `/api/*`, media at `/s3/*`.

---

## CI/CD pipeline

File: [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)

On every push to `main`:

1. **`test-frontend`** — `npm ci` → `npm run typecheck` → `npm run build`
   inside `frontend/`. Fails the pipeline on any TS or build error.
2. **`test-backend`** — runs a curated subset of pytest files that do
   not require Postgres/MinIO/MediaPipe (only pure-logic + mocked DB):
   `test_rules`, `test_scoring`, `test_scoring_engine`,
   `test_outfit_engine_step4`, `test_events`, `test_insights`,
   `test_wear_log`. To extend: add a file here that doesn't need real
   infra, and add it to the `pytest -q` list.
3. **`deploy`** (only on push to main, not on PRs) — runs
   `appleboy/ssh-action` against `194.67.99.214` as `root`:
   - `git fetch origin main && git reset --hard origin/main` in
     `/home/ubuntu/stilist24-com`
   - Writes a fresh `.env.prod` from GitHub Secrets (see next section)
   - `docker compose -p stilist24com -f docker-compose.prod.yml up -d --build`
     with 3 retries in case Docker Hub TLS flakes
   - `docker image prune -f`
   - Waits up to 60 s for `/docs` on 8002 and `/` on 3002 to answer.

Alembic migrations run automatically in `ai-stylist-starter/entrypoint.sh`
on every api container start, so schema changes land without manual
intervention.

---

## GitHub Secrets

The deploy workflow reads these secrets (set in GitHub → Settings →
Secrets → Actions):

| Secret | Purpose |
|---|---|
| `DEPLOY_SSH_KEY` | Private key for `root@194.67.99.214` |
| `JWT_SECRET` | `JWT_SECRET` in .env.prod |
| `POSTGRES_PASSWORD` | Postgres password + embedded in `DATABASE_URL` |
| `S3_ACCESS_KEY` | MinIO root user + API S3 access key |
| `S3_SECRET_KEY` | MinIO root password + API S3 secret key |
| `FASHN_API_KEY` | FASHN virtual try-on (blank → stub adapter) |
| `NEXT_PUBLIC_API_URL` | Baked into the web build. Prod value: `https://stilist24.com/api` |

`S3_PUBLIC_BASE_URL` is hard-coded in the deploy script's here-doc to
`https://stilist24.com/s3` — if you ever move media to a CDN or a
subdomain, change it there.

See [`.env.prod.example`](../.env.prod.example) for the full list of
variables the server env ends up with.

---

## Day-2 operations

### Redeploy

Any push to `main` redeploys automatically. To force a redeploy without
a code change: empty commit + push.

```bash
git commit --allow-empty -m "ci: redeploy" && git push
```

### Read beta feedback

SSH to the server, then:

```bash
docker exec stilist24com-db-1 psql -U postgres -d aistylist \
  -c "SELECT created_at,
             payload_json->>'message' AS msg,
             payload_json->>'contact' AS contact,
             payload_json->'context'->>'path' AS page
      FROM user_events
      WHERE event_type='beta_feedback'
      ORDER BY created_at DESC;"
```

(`docker ps` if the container name differs.)

### Funnel metrics

Same table, any event type. E.g. per-page views last 7 days:

```bash
docker exec stilist24com-db-1 psql -U postgres -d aistylist \
  -c "SELECT payload_json->>'path' AS page, count(*)
      FROM user_events
      WHERE event_type='page_viewed'
        AND created_at > now() - interval '7 days'
      GROUP BY 1 ORDER BY 2 DESC;"
```

### Backups

Minimal daily `pg_dump` + weekly `minio_data` tarball. Not yet wired —
add to root crontab when ready:

```cron
0 3 * * * docker exec stilist24com-db-1 pg_dump -U postgres aistylist \
  | gzip > /srv/backups/pg-$(date +\%F).sql.gz && \
  find /srv/backups -name 'pg-*.sql.gz' -mtime +14 -delete

0 4 * * 0 tar -czf /srv/backups/minio-$(date +\%F).tgz -C /var/lib/docker/volumes/ stilist24com_minio_data
```

### Uptime monitor

Point any external monitor at `https://stilist24.com/api/health` —
it's cheap (no DB hit) and returns `{"status":"ok"}`.

### Rollback

Git is the source of truth. To revert a bad deploy:

```bash
# on your machine
git revert <bad_sha>
git push
```

CI runs again and the revert rolls out like any other push. For a
faster manual path when the site is visibly broken, SSH in and pin the
compose stack to the previous image before the next redeploy:

```bash
cd /home/ubuntu/stilist24-com
git log --oneline | head
git reset --hard <good_sha>
docker compose -p stilist24com -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

If a migration is incompatible, restore the latest
`/srv/backups/pg-*.sql.gz` before the compose up.

### SSH-tunneling to MinIO console

MinIO's admin UI isn't exposed publicly. To reach it:

```bash
ssh -L 9001:127.0.0.1:9001 root@194.67.99.214
# then open http://127.0.0.1:9001 locally
```

Uses S3_ACCESS_KEY / S3_SECRET_KEY from .env.prod as the login.

---

## What's not here yet

- Separate worker process (the workers/ package is imported in-process).
- Prometheus/Grafana — `/health` + nginx access logs cover the
  closed-beta phase.
- CDN in front of media — add when `/s3/` bandwidth starts to matter.
- Staging environment — PRs run typecheck/build but don't deploy
  anywhere. Add when the team is > 1.
