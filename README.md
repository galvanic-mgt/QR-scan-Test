Sample QR Kiosk (Cloudflare Relay + Static CMS)

This project loops images on a display PC and opens a browser when a QR code is scanned.
The QR scan hits a backend relay API, and the kiosk app polls for new scans.
CMS management is a static web page (`cms/index.html`) that calls backend APIs.

Structure
- `worker/`: Cloudflare Worker relay + CMS API backend
- `kiosk/app.py`: Slideshow + scan polling + CMS sync kiosk app
- `cms/index.html`: Static CMS frontend (works with VS Code Live Server)
- `local/mock_worker.py`: Local-only backend for quick testing

Online mode (Cloudflare Worker)
1. Install Wrangler and login:
   - `npm install -g wrangler`
   - `wrangler login`
2. Create a KV namespace:
   - `wrangler kv namespace create SCANS`
   - `wrangler kv namespace create SCANS --preview`
3. Paste KV IDs into `worker/wrangler.toml`.
4. Set CMS password secret:
   - `cd worker`
   - `wrangler secret put CMS_PASSWORD`
5. Deploy:
   - `wrangler deploy`
6. In `kiosk/`, switch config to online template:
   - `python3 switch_config.py online`
7. Edit `kiosk/config.json` with your real Worker URL values for:
   - `poll_url`
   - `cms_public_url`

GitHub deployment
1. Push this repo to GitHub.
2. In GitHub, enable Pages with `GitHub Actions` as the source.
3. Add these repository secrets for the Worker deployment workflow:
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
   - `CMS_PASSWORD`
4. In Cloudflare, create the KV namespaces used by the Worker:
   - `wrangler kv namespace create SCANS`
   - `wrangler kv namespace create SCANS --preview`
5. Paste the returned namespace IDs into `worker/wrangler.toml`.
6. Set `worker/wrangler.toml` values for production:
   - `name`
   - `CMS_USERNAME`
   - `CMS_ALLOWED_ORIGIN`
   - `CMS_SESSION_TTL_SECONDS`
7. Push to `main`.
   - `.github/workflows/deploy-worker.yml` deploys the Worker to Cloudflare.
   - `.github/workflows/deploy-cms-pages.yml` publishes `cms/` to GitHub Pages.
8. After the Pages workflow completes, set `CMS_ALLOWED_ORIGIN` to your exact GitHub Pages origin and redeploy the Worker.
9. Update `kiosk/config.online.json` with your real Worker URL before using online mode.

GitHub + Cloudflare URLs
- Worker API base URL:
  - `https://<your-worker-name>.<your-subdomain>.workers.dev`
- CMS public URL for the kiosk sync:
  - `https://<your-worker-name>.<your-subdomain>.workers.dev/cms/public`
- CMS admin page URL after GitHub Pages deploy:
  - `https://<your-github-user>.github.io/<your-repo>/`

Local-only quick test
1. Install kiosk deps:
   - `cd kiosk`
   - `python3 -m venv .venv`
   - `source .venv/bin/activate` (Windows: `.venv\\Scripts\\activate`)
   - `pip install -r requirements.txt`
2. Install local backend dep:
   - `pip install -r ../local/requirements.txt`
3. Switch to local config:
   - `python3 switch_config.py local`
4. Start local backend (new terminal):
   - `cd local`
   - `python3 mock_worker.py`
5. Start kiosk app (new terminal):
   - `cd kiosk`
   - `python3 app.py`
6. Open `cms/index.html` with Live Server.
7. In CMS page use:
   - Worker base URL: `http://127.0.0.1:8787`
   - Device ID: `KIOSK123`
   - Username: `admin`
   - Password: `localpass`
8. Test scan trigger in browser:
   - `http://127.0.0.1:8787/scan?device=KIOSK123`

Local API smoke test
1. From the repo root, create and activate a venv:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Install both kiosk and local backend deps:
   - `pip install -r kiosk/requirements.txt -r local/requirements.txt`
3. Start the local backend:
   - `python local/mock_worker.py`
4. In a second terminal, run the smoke test:
   - `python local/smoke_test.py`
5. Expected result:
   - `Smoke test passed for device DEMO...`

The smoke test verifies the full local backend contract:
- CMS login
- CMS state read/write
- slide upload
- public sync payload
- image fetch
- scan trigger
- poll response
- slide delete

Switch back to online
1. Run:
   - `cd kiosk`
   - `python3 switch_config.py online`
2. Confirm `kiosk/config.json` has your Worker URLs.
3. Run `python3 app.py`.

How sync works
- CMS writes settings/images to backend storage.
- `kiosk/app.py` fetches `cms_public_url?device=<id>` periodically.
- On revision changes, kiosk downloads latest slides to `kiosk/photos`.
- Scan-triggered browser opens the CMS-managed `website_url`.

Security notes
- Local quick test credentials are fixed defaults for convenience.
- For online mode, use Worker auth (`CMS_USERNAME`, `CMS_PASSWORD`) and set `CMS_PASSWORD` with Wrangler secret.
- Set strict CORS origin in Worker (`CMS_ALLOWED_ORIGIN`) for production.

Deprecated local CMS
- `kiosk/cms_app.py` is deprecated and no longer used.
