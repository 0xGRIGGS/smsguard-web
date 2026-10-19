# SMSGuard ES — Web

Account + recovery dashboard for **SMSGuard ES**, the SMS-based phone-recovery
system. It pairs with the Android app in `smsguard-org/smsguard`:

- **This website** lets an owner register a phone's IMEI, flag it lost, queue
  remote actions, and read messages from whoever finds the device.
- **The Android app** carries out the SMS commands and reports telemetry
  (location, battery) back to the API here.

## What it does

| Area | Details |
| --- | --- |
| Accounts | Sign up / log in, hashed passwords (Werkzeug), change password |
| Devices | Register by IMEI (15-digit, Luhn-checked), edit model/colour/notes |
| Lost & found | Flag lost (activates the public recovery link), mark found |
| Remote actions | Queue `locate`, `alarm`, or `lock` for the app to run |
| Telemetry | Last known position + battery, plus a **location trail** of recent fixes |
| Finder messages | Public `/r/<imei>` page; unread messages are badged for the owner |
| API | `/api/status`, `/api/checkin`, `/api/ack` for the Android client |

## Quick start (local)

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python run.py
```

Open <http://127.0.0.1:5000>. The SQLite database and the session secret are
created automatically under `data/` (both are git-ignored).

Run the tests:

```bash
./venv/bin/python -m pytest tests/ -q
```

## Configuration

All settings are environment variables (see `.env.example`):

| Variable | Purpose |
| --- | --- |
| `SMSGUARD_SECRET_KEY` | Session signing key. **Set a long random value in production.** |
| `SMSGUARD_DATABASE` | SQLite file path. Point at a persistent disk in production. |
| `SMSGUARD_COOKIE_SECURE` | `1` to mark the session cookie `Secure` (requires HTTPS). |
| `SMSGUARD_TRUST_PROXY` | `1` when running behind a reverse proxy so client IPs are read from `X-Forwarded-For`. |

## Deployment notes

- **Persistent storage.** Most free hosts reset their filesystem on restart.
  Point `SMSGUARD_DATABASE` at a mounted persistent disk, or all accounts and
  devices are lost on the next deploy.
- **Single process.** Rate limiting lives in memory, so keep one worker
  (`Procfile` uses `--workers 1 --threads 8`). Multiple workers would each have
  their own counters, weakening the limits.
- **HTTPS + cookies.** Serve over HTTPS and set `SMSGUARD_COOKIE_SECURE=1`.
- **Reverse proxy.** Set `SMSGUARD_TRUST_PROXY=1` so per-IP rate limiting works.
- Health check endpoint: `GET /healthz` → `{"status": "ok"}`.

Start command (also in `Procfile`):

```bash
gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 60
```
