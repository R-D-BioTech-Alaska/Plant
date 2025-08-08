# Plant Kiosk

A modern, **offline-friendly, cloud-ready** kiosk and desktop app for plant care, sales, and knowledge.
Built with **Python + CustomTkinter + SQLite** (optional REST sync), it lets you manage a plant catalog, show care profiles, identify plants with AI, track watering/feeding schedules, and (optionally) send reminders.

> Runs great as a single PC kiosk today. Flip a couple config switches and you get cloud sync, AI image ID, and notifications.

---

## Highlights

* **Shop & Catalog** — images, price, stock, category filters, cart + demo checkout
* **Plant Profiles** — species/class/genus, care notes, safety flags, knowledge add-ons
* **Schedules** — watering/feeding with due/overdue highlighting and **auto-advance**
* **AI Identify (optional)** — plugs into **Plant.id**; falls back to local offline stub
* **Notifications (optional)** — email/SMS/webhook reminders with a background scheduler
* **Admin Tools** — CSV/JSON import, export, merge updates, image uploader, low-stock report, DB backup
* **Cloud Sync (optional)** — pull/push via simple REST endpoints
* **Safe by default** — all integrations are **opt-in**; app runs fully offline

---

## Quick Start

```bash
# 1) Python ≥ 3.10 recommended
pip install -r requirements.txt  # see below for minimal deps

# 2) Run the kiosk
python plant.py
```

First launch creates `config.ini`, `advanced_plant_manager.db`, and `plant_faq.json`.

---

## Requirements

* Python 3.9+ (3.10+ recommended)
* Minimal packages:

  * `customtkinter`, `Pillow`, `SQLAlchemy`
  * Optional integrations: `requests` (REST/Plant.id/webhooks), `smtplib` (stdlib), Twilio (via REST)

`requirements` 

```
customtkinter>=5
Pillow>=10
SQLAlchemy>=2
requests>=2   # optional but recommended
```

---

## Configuration (`config.ini`)

Created on first run. Everything is optional.

```ini
[ADMIN]
admin_password = admin

[APP]
plant_theme = green
timezone = UTC

[SERVER]        ; optional cloud sync
api_base_url =
api_token =

[AI]            ; optional Plant.id
plant_id_api_key =

[NOTIFY]        ; optional reminders
enabled = false
email_enabled = false
sms_enabled = false
email_from =
email_to =
smtp_host =
smtp_port = 587
smtp_user =
smtp_pass =
twilio_sid =
twilio_token =
twilio_from =
phone_to =
webhook_url =
```

---

## Using the App

### Navigation

* **Shop**: Browse, filter, view details, add to cart. “Checkout” just decrements local stock.
* **Plant Info**: Search by name; shows taxonomy, care, safety, knowledge.
* **Schedules**: See next watering/feeding; overdue turns red. Background engine can **notify** and **auto-advance** dates (if enabled).
* **Q\&A**: Simple keyword FAQ. Admin can add/edit entries.
* **Plant AI**: Select an image.

  * If `[AI].plant_id_api_key` is set → calls Plant.id.
  * Otherwise → runs the offline demo stub.
* **Admin** (password from `config.ini`):

  * Import CSV/JSON, Export JSON
  * Add/Edit plant
  * Upload images (saved under `images/`)
  * **Low-Stock Report**
  * **Merge Update (CSV)** — upsert common fields by `name`
  * **Backup DB**
  * **Sync Now (Pull/Push)** — hits your REST API if configured
  * **Notification Settings** (also available from Schedules)

---

## Data & Import/Export

* Database: `advanced_plant_manager.db` (SQLite, created automatically)
* Minimal **CSV** headers supported for import/merge:

  ```
  name,species,plant_class,genus,profile,recommended_nutrition,recommended_watering,safe_to_consume,price,inventory,category
  ```
* **Export** produces an array of plant dicts to JSON.

> Images are stored as file paths in `plant_images` and copied to `images/` on upload.

---

## Cloud Sync (Optional)

**Admin → Sync Now (Pull/Push)** calls your endpoints if set:

* `GET /plants` → list of plant dicts to upsert by `name`
* `GET /faq` → list of `{q,a}`
* `POST /plants/bulk_upsert` → entire local plant list (name, price, inventory, category, updated\_at)

Auth: Bearer token via `[SERVER].api_token`.

> Endpoints are **just examples**—map them to your backend (FastAPI/Django/etc.).

---

## AI Identification (Optional)

Set `[AI].plant_id_api_key` and the **Plant AI** screen will call **Plant.id**.
No key? The app falls back to a local randomized demo so the UI still works offline.

---

## Notifications (Optional)

Turn on reminders in **Schedules → Notification Settings**:

* **Email** (SMTP)
* **SMS** (Twilio REST)
* **Webhook** (POST JSON to your URL)

A background thread scans due watering/feeding tasks and:

1. sends a reminder (tries email → SMS → webhook; logs any skips),
2. **auto-advances** the schedule by its frequency.

---

## Admin CSV Merge (Upsert-by-Name)

**Admin → Merge Update (CSV)** updates existing plants using header names above.
Examples:

* Set sale pricing for a set of SKUs (`name`)
* Bulk category changes
* Quick inventory corrections

---

## Backups

**Admin → Backup DB** copies `advanced_plant_manager.db` to a location you choose.
You can also just back up the whole project folder for a snapshot (DB + images + config).

---

## Roadmap

* Weather-aware scheduling (**planned**; e.g., adapt watering frequency by local humidity/temp)
* User accounts & role-based access
* Web app / Electron wrapper for kiosk mode
* Realtime updates (WebSockets/GraphQL subscriptions)
* Deeper analytics (usage, unanswered Q\&A, AI success rate)

---

## Security Notes

* Runs fully offline by default.
* All integrations are opt-in via `config.ini`.
* If you enable cloud: use HTTPS, Bearer tokens, strong admin password, and regular DB backups.

---

## Troubleshooting

**No AI results / timeout**

* Add a valid `[AI].plant_id_api_key`.
* Ensure `requests` is installed and outbound HTTPS allowed.

**Emails not sending**

* Verify SMTP host/port/creds; try a test with `openssl s_client -starttls smtp`.
* Check spam folder and `notifications.log`.

**SMS not sending**

* Confirm Twilio SID/token/from/to and that your number is verified.

**Sync does nothing**

* Leave `[SERVER]` blank for offline use.
* If set, confirm endpoints exist and return 2xx.

---

## Contributing

* Issues and PRs welcome.

---

## License

MIT 

---


