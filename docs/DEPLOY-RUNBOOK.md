# DriverDNA — Deploy Runbook (Oracle VM + SQLite)

The step-by-step for the deployment of record adopted in **SPEC.md A40**:
SQLite on an Oracle Cloud Always Free VM, published over a Cloudflare Tunnel +
Access, replacing the retired Cloud Run + Supabase setup. It exists so the box
is **rebuildable, not a pet** (DEPLOY-SPEC H3).

Design context: `docs/DEPLOY-SPEC.md` (H1 auth, H2 network, H3 ops) and
`docs/SPEC.md` A23 (the backend abstraction) and A40 (this migration).

## What you need before starting

- An Oracle Cloud account (Always Free tier).
- A domain on a Cloudflare account (for Access; ~$10/yr — the one non-free
  piece). Skip this and use Tailscale instead if you don't want a public URL.
- **The Supabase connection URL, still readable.** The whole clean migration is
  one `store-copy` off it. Confirm you can still connect before you tear
  anything down.
- **Your source lap CSVs**, to restore historical raw traces (`backfill-blobs`).
- The current secrets: `DRIVERDNA_SESSION_SECRET`, `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `GEMINI_API_KEY`, `GARAGE61_TOKEN`.

Commands below run **on the VM over SSH (bash)** unless marked otherwise. Where
a step runs on your own Windows machine, PowerShell syntax is given.

---

## Part B — Provision the VM

1. Create an **Always Free A1 (ARM64/aarch64)** compute instance (Ampere) with
   a block volume. Regional A1 capacity is the usual reason a free instance
   won't launch — retry or change availability domain if creation fails.
2. Base OS packages and a service user:
   ```bash
   sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv git sqlite3
   sudo useradd --system --home /var/lib/driverdna --create-home driverdna
   ```
   (On Oracle Linux, use `dnf install python3.12 git sqlite` and the same
   `useradd`.) Any Python **3.11 or 3.12** is fine.
3. Install the app into a dedicated venv:
   ```bash
   sudo git clone https://github.com/tht78hzdn5-crypto/driverdna /opt/driverdna/DriverDNA
   sudo python3.12 -m venv /opt/driverdna/venv
   sudo /opt/driverdna/venv/bin/pip install -e "/opt/driverdna/DriverDNA[ui,ai-gemini]"
   ```
   The built SPA ships in the package (`src/driverdna/ui/static/`), so **no
   Node build is needed**. No `pg` extra — this is a SQLite deployment.
4. **Verify the ARM wheels installed without a source build** (don't assume):
   ```bash
   /opt/driverdna/venv/bin/python -c "import numpy, scipy; print(numpy.__version__, scipy.__version__)"
   ```

---

## Part C — Migrate the data

This is the load-bearing step. Run it on the VM (which can reach Supabase).

1. Copy every compact row (PKs preserved, checksum-verified):
   ```bash
   sudo -u driverdna /opt/driverdna/venv/bin/driverdna store-copy \
     --from "postgresql://USER:PASSWORD@HOST:6543/postgres?sslmode=require" \
     --to /var/lib/driverdna/driverdna.db
   ```
   > On your Windows machine instead, keep the URL out of history:
   > ```powershell
   > $env:SRC = "postgresql://…"
   > driverdna store-copy --from $env:SRC --to driverdna.db
   > ```
2. **Gate on the last line.** Proceed only on
   `verified: all N tables checksum-identical`. If it prints
   `MISMATCH … the copy is NOT faithful — do not cut over`, stop and
   investigate — that check exists precisely to catch a bad copy at the row
   level rather than months later in a report.
3. Restore historical raw traces from your CSVs (optional but recommended — a
   plain re-import is a no-op, since the copied rows already dedup by content
   hash):
   ```bash
   sudo -u driverdna /opt/driverdna/venv/bin/driverdna backfill-blobs \
     --from /path/to/your/csvs --db /var/lib/driverdna/driverdna.db
   ```
   It matches each CSV to a lap by content fingerprint and writes only the
   missing `<lap_pk>.npz`, never touching a lap row. Laps it couldn't match and
   CSVs that matched nothing are itemized. Going forward, every lap you
   `import`/`sync` on the VM gets a durable blob automatically.

---

## Part D — Bring up the service

1. Generate a stable session secret (do this once and keep it — rotating it
   signs everyone out):
   ```bash
   openssl rand -hex 32
   ```
   Secrets file, `0600`, owned by the service user:
   ```bash
   sudo install -d -m 0700 -o driverdna -g driverdna /etc/driverdna
   sudo -u driverdna tee /etc/driverdna/driverdna.env >/dev/null <<'EOF'
   DRIVERDNA_SESSION_SECRET=...      # required — keep STABLE, rotating logs you out
   GEMINI_API_KEY=...                # required for AI coaching/chat
   GARAGE61_TOKEN=...                # required for driverdna sync
   GOOGLE_CLIENT_ID=...              # optional — enables Google OAuth login
   GOOGLE_CLIENT_SECRET=...          # optional — required only if GOOGLE_CLIENT_ID is set
   EOF
   sudo chmod 0600 /etc/driverdna/driverdna.env
   ```
   `DRIVERDNA_DATABASE_URL`/`DRIVERDNA_BLOB_ROOT` are already set by the unit,
   so they don't belong here.
2. Install the systemd units from `deploy/`:
   ```bash
   sudo cp /opt/driverdna/DriverDNA/deploy/driverdna.service /etc/systemd/system/
   sudo cp /opt/driverdna/DriverDNA/deploy/driverdna-backup.* /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now driverdna driverdna-backup.timer
   sudo systemctl status driverdna --no-pager
   sudo journalctl -u driverdna -n 20 --no-pager
   ```
   The service binds `127.0.0.1:8710` only; the tunnel publishes it. **Confirm
   the startup log line reads `auth=yes behind_proxy=yes`** — the unit already
   passes `--behind-proxy` (SPEC.md A41): without it, the auth interlock still
   protects you (a missing secret refuses to start either way), but per-client
   login throttling and rate limiting silently collapse to one shared bucket
   keyed on the tunnel's own loopback address instead of the real caller.
3. Cloudflare Tunnel + Access — follow `deploy/cloudflared/README.md`. In
   short: `cloudflared tunnel login && create`, copy
   `deploy/cloudflared/config.example.yml` → `/etc/cloudflared/config.yml`
   (fill UUID + hostname), `cloudflared tunnel route dns …`,
   `cloudflared service install`, then add a self-hosted **Access application**
   whose policy allowlists your single owner email.
4. **Update the Google OAuth redirect URI** in the Google Cloud console to the
   new Cloudflare hostname (e.g. `https://driverdna.example.com/api/auth/google/callback`).
   Miss this and sign-in breaks — the most common cutover mistake. Skip if you
   are not using Google OAuth.
5. **Create your account.** On a fresh deployment (or after a store-copy from
   Supabase), there is no usable login yet — the DB seed row at
   `owner@example.com` is a migration scaffold with no real password. Visit
   the app URL through the Cloudflare Access gate; the SPA shows a sign-in
   screen. Click **Register**, enter your email and a password (≥ 8
   characters), and submit. On success you're signed in and your account
   (`user_pk=2`) is the one all future Driver Model history accrues to. If you
   set up Google OAuth and prefer that path, click the Google button instead —
   it creates the account automatically on first sign-in.

---

## Part E — Verify (H done-criteria)

- **Faithful copy:** the `store-copy` checksum line was green (Part C.2).
- **Full suite on the VM against the real SQLite DB:**
  ```bash
  cd /opt/driverdna/DriverDNA && sudo /opt/driverdna/venv/bin/pip install -e ".[dev]"
  sudo /opt/driverdna/venv/bin/python -m pytest -rs
  ```
  Report the receipt: command, that the backend was SQLite, and that the only
  skips are Postgres-absent (a skip is not a pass).
- **Determinism on ARM:** import a cohort twice into throwaway DBs and confirm
  the generated reports are byte-identical — the existing mechanical check, now
  on aarch64.
- **Parity spot-check:** a report generated on the migrated SQLite matches one
  generated from Supabase pre-cutover (A23's byte-identical guarantee).
- **Auth / unreachability:** sign in through the Cloudflare URL; load Driver
  home, a cohort, and one chat turn; confirm a request from an
  un-allowlisted identity is blocked at Access, and that `/api/*` returns 401
  without a session.
- **Configuration is visible, not inferred:** `curl https://<vm-domain>/health`
  reports `{"status":"ok","store":"sqlite","auth":true}`. If `auth` ever reads
  `false` here after this setup, the session secret didn't load — stop and
  fix it before relying on the deployment; don't infer correctness from the
  site merely rendering (docs/VM-MIGRATION.md §1, on exactly this mistake).
- **A restart doesn't sign you out:** `sudo systemctl restart driverdna`, then
  reload the site without clearing cookies — you should still be signed in.
  (This is what the retired ephemeral-secret fallback used to break.)

---

## Part F — Decommission (only after the VM is verified stable for a few days)

1. Take a final safety copy: re-run `store-copy` to a dated SQLite file and
   keep it off the box.
2. Tear down the Cloud Run service (`driverdna`, `northamerica-northeast1`).
3. **Delete the Supabase project** — this is what actually ends the egress
   billing.
4. Remove/rotate the now-unused `DRIVERDNA_DATABASE_URL` (Supabase) GitHub
   Actions secret. The Cloud Run deploy workflow was already removed in the
   A40 change, so nothing will try to redeploy.

## Ongoing

- **Lap intake:** `driverdna sync` on a systemd timer pulls owned laps from
  Garage61 directly on the VM (idempotent by content-hash dedup); `#/upload`
  remains for manual/reference CSVs from the phone browser.
- **Backups:** `driverdna-backup.timer` snapshots the DB daily to
  `/var/lib/driverdna/backups/`. Pull one to your own machine occasionally —
  the dated Driver-Model history and chat/coach transcripts are the
  irreplaceable rows.

---

## Part G — Troubleshooting

BUG-018 was lost because journald defaulted to volatile storage — the service
crashed (or refused to start), and the evidence vanished on the next reboot.
The steps below make that impossible going forward.

### 1. Enable persistent journal storage

Without this, `journalctl -u driverdna` shows nothing after a reboot.

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp /opt/driverdna/DriverDNA/deploy/journald-driverdna.conf \
    /etc/systemd/journald.conf.d/
sudo systemctl restart systemd-journald
```

Verify: `journalctl --disk-usage` should report a non-zero archived size after
the next service restart.

### 2. Service won't start (Cloudflare 1033 / port unreachable)

```bash
# What the unit thinks happened:
sudo systemctl status driverdna --no-pager
sudo journalctl -u driverdna -n 100 --no-pager

# Health probe (if the port is up at all):
curl -s http://127.0.0.1:8710/health | python3 -m json.tool

# Common causes, most likely first:
# - auth=false in /health → DRIVERDNA_SESSION_SECRET missing or empty in
#   /etc/driverdna/driverdna.env. The interlock (A41) refuses a non-loopback
#   bind without one, and --behind-proxy makes every bind non-loopback.
# - "Address already in use" → another process on port 8710.
# - Import error after pip install → a dependency shifted. Check the traceback.
```

### 3. Garage61 sync fails with an auth error

A `Garage61AuthError` in the journal means the stored OAuth token expired.
The SPA shows "Garage61 sign-in expired — reconnect" with a link; the CLI
prints the same. Reconnect through the OAuth flow at `#/import` → "Connect
Garage61" (or set a fresh `GARAGE61_TOKEN` in the env file and restart).

### 4. Capturing a full diagnostic snapshot

If the service is misbehaving and you need to share the state:

```bash
sudo journalctl -u driverdna --since "1 hour ago" --no-pager > ~/driverdna-journal.txt
sudo systemctl status driverdna --no-pager >> ~/driverdna-journal.txt
curl -s http://127.0.0.1:8710/health >> ~/driverdna-journal.txt 2>&1
```

This captures the journal, the unit status, and the health probe in one file.
**Never include `/etc/driverdna/driverdna.env`** — it contains secrets.
