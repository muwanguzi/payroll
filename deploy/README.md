# Deploying payroll.nextmedia.co.ug — Docker + CI/CD

I don't have SSH access to `5.189.175.18`, GitHub access to create secrets,
or DNS/registrar access — all three steps below need you. Everything I
*can* prepare (Dockerfile, compose file, pipeline, server-side script) is
done and in this repo.

**One-time only.** After the pipeline is wired up (step 3), every future
`git push` to `main` builds a new image, pushes it to GitHub Container
Registry, and redeploys it on the server automatically — nothing below is
repeated for ordinary code changes.

## 0. DNS

In whatever manages `nextmedia.co.ug`'s DNS, add (skip if already done):

```
A    payroll.nextmedia.co.ug    ->    5.189.175.18
```

## 1. Push a git repo somewhere GitHub Actions can build from

This project has no git remote yet. On **your local machine**:

```bash
cd "/home/francis-muwanguzi/Pay Roll"
git init
cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.pyc
db.sqlite3
media/
staticfiles/
data/
.env
cookies
cj
cj2
*.output
EOF
git add .
git commit -m "Next Media Payroll"
```

Then create a repo on GitHub (empty, no README) and:

```bash
git remote add origin git@github.com:<you>/<repo>.git
git branch -M main
git push -u origin main
```

## 2. Push the deploy files to the server — run **locally**, not the SSH session

```bash
bash deploy/push_to_server.sh
```

Copies `Dockerfile`, `docker-compose.yml`, `.env.example`, `docker/`, and
`deploy/` to `/opt/payroll/app` — that's all the server needs; the app code
itself arrives later as a prebuilt image, not as source files. Re-run this
only when those infra files themselves change, not for ordinary app code
changes (those ship via the pipeline).

## 3. One-time server setup — run in your **already-open root SSH terminal**

```bash
cd /opt/payroll/app
bash deploy/docker-provision.sh
```

- installs Docker if it isn't already there
- creates `.env` with a real, freshly generated `DJANGO_SECRET_KEY` (server-only,
  never in git) and the right `DJANGO_ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`
- creates `data/` `media/` `staticfiles/` with the ownership the container
  expects
- brings the app up (builds locally the first time, since the pipeline
  hasn't pushed a real image yet)
- **detects what's already fronting ports 80/443** before touching web-server
  config — if this server already runs Caddy or nginx for other sites (e.g.
  the main `nextmedia.co.ug` site), it adds an additive, validated site block
  rather than risk colliding with something else. If Caddy: HTTPS is
  automatic, no certbot needed. If nginx: run certbot yourself once DNS
  resolves (script prints the exact command). If neither and something else
  owns those ports: it stops and tells you rather than guessing.

Paste me its output — especially the "Detecting what's already serving :80 /
:443" line — same as before; I'll adjust the script if it hits something
unexpected.

## 4. Wire up the pipeline — GitHub repo Settings → Secrets and variables → Actions

Add three **repository secrets**:

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | `5.189.175.18` |
| `DEPLOY_USER` | `root` |
| `DEPLOY_SSH_KEY` | a **dedicated** private key for this purpose (see below) |

**Generate the deploy key yourself** — in a local terminal, not through me:

```bash
ssh-keygen -t ed25519 -f payroll_deploy_key -N "" -C "github-actions-payroll-deploy"
```

Then, in your **open root SSH terminal** on the server:

```bash
echo "<paste the contents of payroll_deploy_key.pub>" >> ~/.ssh/authorized_keys
```

Paste `payroll_deploy_key` (the **private** key) into the `DEPLOY_SSH_KEY`
GitHub secret directly via the GitHub web UI (or `gh secret set DEPLOY_SSH_KEY < payroll_deploy_key`)
— never into this chat. Then delete the local copy:

```bash
rm payroll_deploy_key payroll_deploy_key.pub
```

Optional: in **Settings → Environments**, create an environment named
`production` and require a manual approval before deploys run — the
workflow already targets an environment called `production`, so this is
just a checkbox away if you want a human in the loop on every deploy.

Optional but recommended: make the GHCR package public once it exists
(**your GitHub profile → Packages → payroll → Package settings → Change
visibility**) — otherwise `docker compose pull` only works from *within* a
pipeline run (which logs in with a short-lived token); a manual pull on the
server between deploys would need its own long-lived token.

## 5. First deploy

```bash
git push origin main
```

Watch it in the repo's **Actions** tab: `test` → `build-and-push` → `deploy`.
The deploy job SSHes in, `docker compose pull`s the image the previous job
just pushed, and `docker compose up -d`.

## 6. First login

```bash
docker compose exec web python manage.py createsuperuser
```

Then sign in at `https://payroll.nextmedia.co.ug/` and, from **Admin →
Groups**, create the real Head of Human Capital / Chief People Officer /
Chief Audit Officer / Chief Finance Officer / HR Data Entry users for your
actual staff (see `docs/user-manual.html` — Documents in the app once it's
up — for what each role does).

## Everyday use after this

- **Ship a code change**: just `git push` to `main`. Nothing else.
- **Roll back**: re-run an older successful workflow run from the Actions
  tab (`Re-run all jobs`), or on the server: `IMAGE=ghcr.io/<owner>/<repo>:<old-sha> docker compose up -d`.
- **Logs**: `docker compose logs -f web` (app), `journalctl -u caddy -f` or
  `/var/log/nginx/error.log` (web server, whichever was detected).
- **Database**: one SQLite file at `/opt/payroll/app/data/db.sqlite3` — fine
  at this scale. Back it up (`cp data/db.sqlite3 data/db.sqlite3.bak-$(date +%F)`,
  or a cron job) — nothing does that automatically yet. Say the word if
  you'd rather move to Postgres (easy to add as a second `docker-compose.yml`
  service).
- **Payslip emails** currently just log to `docker compose logs web` until
  you set real SMTP — add to `.env` on the server and `docker compose up -d`
  to pick it up:
  ```
  DJANGO_EMAIL_HOST=smtp.yourhost.com
  DJANGO_EMAIL_PORT=587
  DJANGO_EMAIL_HOST_USER=...
  DJANGO_EMAIL_HOST_PASSWORD=...
  DJANGO_DEFAULT_FROM_EMAIL=payroll@nextmedia.co.ug
  ```

## Testing the image locally before any of this

```bash
cp .env.example .env   # edit DJANGO_SECRET_KEY etc. for a local try
mkdir -p data media staticfiles && sudo chown -R 1000:1000 data media staticfiles
docker compose up --build
```

Then `http://127.0.0.1:8001/`.
