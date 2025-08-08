import os, sys, threading, time, json, csv, math, random, shutil, traceback, queue
from datetime import datetime, timedelta, timezone

try:
    import requests  
except Exception:  
    requests = None

import smtplib
from email.mime.text import MIMEText

import customtkinter as ctk
from tkinter import messagebox, filedialog, simpledialog
from PIL import Image, ImageTk

from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Text, DateTime, Float
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.exc import OperationalError

import configparser

CONFIG_FILE = 'config.ini'
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w') as f:
        f.write("[ADMIN]\nadmin_password=admin\n")
        f.write("[APP]\nplant_theme=green\ntimezone=UTC\n\n")
        f.write("[SERVER]\napi_base_url=\napi_token=\n\n")
        f.write("[AI]\nplant_id_api_key=\n\n")
        f.write("[NOTIFY]\n# global defaults used by kiosk (no per-user accounts yet)\n"
                "enabled=false\nemail_enabled=false\nsms_enabled=false\n"
                "email_from=\nemail_to=\nsmtp_host=\nsmtp_port=587\nsmtp_user=\nsmtp_pass=\n"
                "twilio_sid=\ntwilio_token=\ntwilio_from=\nphone_to=\n"
                "webhook_url=\n")
config = configparser.ConfigParser()
config.read(CONFIG_FILE)

def cfg(section, key, default=""):
    try:
        return config.get(section, key, fallback=default)
    except Exception:
        return default

ADMIN_PASSWORD = cfg('ADMIN','admin_password','admin')
APP_TZ = timezone.utc
try:
    tz_name = cfg('APP','timezone','UTC')
    if tz_name.upper() == "UTC":
        APP_TZ = timezone.utc
except Exception:
    pass

Base = declarative_base()

def utcnow():
    return datetime.now(timezone.utc)

class Plant(Base):
    __tablename__ = 'plants'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    profile = Column(Text)
    species = Column(String)
    plant_class = Column(String)
    genus = Column(String)
    recommended_nutrition = Column(Text)
    safe_to_consume = Column(Boolean)
    recommended_watering = Column(Text)
    price = Column(Float, default=0.0)
    inventory = Column(Integer, default=0)
    category = Column(String, default="General")
    barcode_number = Column(String, default=None)
    barcode_image_path = Column(String, default=None)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    images = relationship("PlantImage", back_populates="plant")
    knowledge = relationship("PlantKnowledge", uselist=False, back_populates="plant")
    watering_schedules = relationship("WateringSchedule", back_populates="plant")
    nutrient_schedules = relationship("NutrientSchedule", back_populates="plant")

class PlantImage(Base):
    __tablename__ = 'plant_images'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'))
    image_path = Column(String)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    plant = relationship("Plant", back_populates="images")

class PlantKnowledge(Base):
    __tablename__ = 'plant_knowledge'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'), unique=True)
    scientific_name = Column(String)
    common_name = Column(String)
    water_requirements = Column(Text)
    sunlight_requirements = Column(Text)
    soil_type = Column(String)
    nutrient_recommendations_detailed = Column(Text)
    growth_cycle_info = Column(Text)
    pest_control_info = Column(Text)
    detailed_profile = Column(Text)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    plant = relationship("Plant", back_populates="knowledge")

class WateringSchedule(Base):
    __tablename__ = 'watering_schedules'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'))
    next_water = Column(DateTime)
    frequency_days = Column(Integer, default=7)  
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    plant = relationship("Plant", back_populates="watering_schedules")

class NutrientSchedule(Base):
    __tablename__ = 'nutrient_schedules'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'))
    next_feed = Column(DateTime)
    frequency_days = Column(Integer, default=30)
    nutrient_info = Column(Text)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    plant = relationship("Plant", back_populates="nutrient_schedules")

class CareLog(Base):
    __tablename__ = 'care_logs'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'))
    timestamp = Column(DateTime, default=utcnow)
    observation = Column(Text)
    routine = Column(Text)
    plant = relationship("Plant")

class NotificationLog(Base):
    __tablename__ = 'notification_logs'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=utcnow)
    channel = Column(String)   
    recipient = Column(String) 
    subject = Column(String)
    body = Column(Text)
    status = Column(String)  
    error = Column(Text, nullable=True)

DB_FILE = 'advanced_plant_manager.db'
engine = create_engine(f'sqlite:///{DB_FILE}', echo=False, connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

def _ensure_new_columns():
    """Adds new columns if running over an older DB (SQLite allows simple ALTER ADD COLUMN)."""
    import sqlite3
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(plants)")
        cols = [r[1] for r in cur.fetchall()]
        if 'updated_at' not in cols:
            cur.execute("ALTER TABLE plants ADD COLUMN updated_at TEXT")
        for table, col in [('plant_images','updated_at'),
                           ('plant_knowledge','updated_at'),
                           ('watering_schedules','updated_at'),
                           ('nutrient_schedules','updated_at'),
                           ]:
            cur.execute(f"PRAGMA table_info({table})")
            tcols = [r[1] for r in cur.fetchall()]
            if col not in tcols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
        con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass

_ensure_new_columns()

class CloudAPI:
    """Thin REST client. All methods are best-effort; if config empty or requests==None, they no-op."""
    def __init__(self):
        self.base = cfg('SERVER', 'api_base_url', '').rstrip('/')
        self.token = cfg('SERVER', 'api_token', '')
        self.enabled = bool(self.base and requests)

    def _headers(self):
        h = {'Content-Type': 'application/json'}
        if self.token:
            h['Authorization'] = f'Bearer {self.token}'
        return h

    def get(self, path):
        if not self.enabled: return None
        try:
            r = requests.get(self.base + path, headers=self._headers(), timeout=8)
            if r.status_code//100 == 2:
                return r.json()
        except Exception:
            return None
        return None

    def post(self, path, payload):
        if not self.enabled: return False
        try:
            r = requests.post(self.base + path, headers=self._headers(), json=payload, timeout=8)
            return r.status_code//100 == 2
        except Exception:
            return False

class SyncManager:
    STATE_FILE = 'sync_state.json'
    def __init__(self, api: CloudAPI):
        self.api = api
        self.state = {'last_pull': None, 'last_push': None}
        if os.path.exists(self.STATE_FILE):
            try:
                self.state.update(json.load(open(self.STATE_FILE, 'r', encoding='utf-8')))
            except Exception:
                pass

    def save(self):
        try:
            json.dump(self.state, open(self.STATE_FILE,'w',encoding='utf-8'), indent=2)
        except Exception:
            pass

    def pull(self):
        if not self.api.enabled: return False, "Cloud API not configured"
        plants = self.api.get('/plants') 
        faq = self.api.get('/faq')     
        updated = 0
        try:
            if plants:
                for p in plants:
                    name = p.get('name')
                    if not name: continue
                    row = session.query(Plant).filter_by(name=name).first()
                    if not row:
                        row = Plant(name=name)
                        session.add(row)
                    row.profile = p.get('profile') or row.profile
                    row.species = p.get('species') or row.species
                    row.plant_class = p.get('plant_class') or row.plant_class
                    row.genus = p.get('genus') or row.genus
                    row.recommended_nutrition = p.get('recommended_nutrition') or row.recommended_nutrition
                    if 'safe_to_consume' in p:
                        row.safe_to_consume = bool(p.get('safe_to_consume'))
                    row.recommended_watering = p.get('recommended_watering') or row.recommended_watering
                    if 'price' in p:
                        try: row.price = float(p['price'])
                        except: pass
                    if 'inventory' in p:
                        try: row.inventory = int(p['inventory'])
                        except: pass
                    row.category = p.get('category') or row.category
                    row.updated_at = utcnow()
                    updated += 1
            if faq:
                save_qa(faq)
            session.commit()
            self.state['last_pull'] = utcnow().isoformat()
            self.save()
            return True, f"Pulled {updated} plants and {'FAQ' if faq else 'no FAQ'}"
        except Exception as e:
            session.rollback()
            return False, f"Pull failed: {e}"

    def push(self):
        if not self.api.enabled: return False, "Cloud API not configured"
        payload = []
        for p in session.query(Plant).all():
            payload.append({
                "name": p.name, "price": p.price, "inventory": p.inventory,
                "category": p.category, "updated_at": (p.updated_at or utcnow()).isoformat()
            })
        ok = self.api.post('/plants/bulk_upsert', payload)
        if ok:
            self.state['last_push'] = utcnow().isoformat()
            self.save()
            return True, f"Pushed {len(payload)} plants"
        return False, "Push failed (server unavailable?)"

class Notifier:
    """Email/SMS/Webhook. If nothing configured, writes to notifications.log + DB log."""
    def __init__(self):
        self.enabled = cfg('NOTIFY','enabled','false').lower() == 'true'
        self.email_enabled = cfg('NOTIFY','email_enabled','false').lower() == 'true'
        self.sms_enabled = cfg('NOTIFY','sms_enabled','false').lower() == 'true'
        self.webhook_url = cfg('NOTIFY','webhook_url','').strip()

        self.email_from = cfg('NOTIFY','email_from','')
        self.email_to = cfg('NOTIFY','email_to','')
        self.smtp_host = cfg('NOTIFY','smtp_host','')
        self.smtp_port = int(cfg('NOTIFY','smtp_port','587') or '587')
        self.smtp_user = cfg('NOTIFY','smtp_user','')
        self.smtp_pass = cfg('NOTIFY','smtp_pass','')

        self.tw_sid = cfg('NOTIFY','twilio_sid','')
        self.tw_token = cfg('NOTIFY','twilio_token','')
        self.tw_from = cfg('NOTIFY','twilio_from','')
        self.phone_to = cfg('NOTIFY','phone_to','')

        self.log_file = 'notifications.log'

    def _log(self, channel, to, subject, body, status='sent', error=None):
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat()}] {channel} -> {to} | {subject}\n{body}\nstatus={status} error={error}\n\n")
        except Exception:
            pass
        session.add(NotificationLog(channel=channel, recipient=to, subject=subject, body=body, status=status, error=error))
        session.commit()

    def send_email(self, subject, body):
        if not (self.enabled and self.email_enabled and self.smtp_host and self.email_from and self.email_to):
            self._log('log', self.email_to or '(unset)', subject, body, status='skipped')
            return False
        try:
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = self.email_from
            msg['To'] = self.email_to
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as s:
                s.starttls()
                if self.smtp_user and self.smtp_pass:
                    s.login(self.smtp_user, self.smtp_pass)
                s.sendmail(self.email_from, [self.email_to], msg.as_string())
            self._log('email', self.email_to, subject, body, status='sent')
            return True
        except Exception as e:
            self._log('email', self.email_to, subject, body, status='failed', error=str(e))
            return False

    def send_sms(self, body):
        if not (self.enabled and self.sms_enabled and self.tw_sid and self.tw_token and self.tw_from and self.phone_to and requests):
            self._log('log', self.phone_to or '(unset)', '(sms)', body, status='skipped')
            return False
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.tw_sid}/Messages.json"
            data = {'From': self.tw_from, 'To': self.phone_to, 'Body': body}
            r = requests.post(url, data=data, auth=(self.tw_sid, self.tw_token), timeout=8)
            ok = r.status_code//100 == 2
            self._log('sms', self.phone_to, '(sms)', body, status='sent' if ok else f'failed:{r.status_code}')
            return ok
        except Exception as e:
            self._log('sms', self.phone_to, '(sms)', body, status='failed', error=str(e))
            return False

    def send_webhook(self, subject, body):
        if not (self.enabled and self.webhook_url and requests):
            self._log('log', self.webhook_url or '(unset)', subject, body, status='skipped')
            return False
        try:
            r = requests.post(self.webhook_url, json={'subject': subject, 'body': body}, timeout=8)
            ok = r.status_code//100 == 2
            self._log('webhook', self.webhook_url, subject, body, status='sent' if ok else f'failed:{r.status_code}')
            return ok
        except Exception as e:
            self._log('webhook', self.webhook_url, subject, body, status='failed', error=str(e))
            return False

class ReminderEngine:
    """Background thread that scans schedules and dispatches notifications."""
    def __init__(self, notifier: Notifier, poll_seconds=60):
        self.notifier = notifier
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                traceback.print_exc()
            self._stop.wait(self.poll_seconds)

    def _tick(self):
        now = utcnow()
        plants = session.query(Plant).all()
        messages = []
        for p in plants:
            due_w = None
            if p.watering_schedules:
                due_w = min((ws.next_water for ws in p.watering_schedules if ws.next_water), default=None)
                if due_w and due_w.date() <= now.date():
                    messages.append(f"Water {p.name} today ({due_w.date().isoformat()}).")
                    for ws in p.watering_schedules:
                        if ws.next_water == due_w and ws.frequency_days:
                            ws.next_water = (due_w + timedelta(days=ws.frequency_days)).replace(tzinfo=timezone.utc)
            due_n = None
            if p.nutrient_schedules:
                due_n = min((ns.next_feed for ns in p.nutrient_schedules if ns.next_feed), default=None)
                if due_n and due_n.date() <= now.date():
                    messages.append(f"Feed {p.name} today ({due_n.date().isoformat()}).")
                    for ns in p.nutrient_schedules:
                        if ns.next_feed == due_n and ns.frequency_days:
                            ns.next_feed = (due_n + timedelta(days=ns.frequency_days)).replace(tzinfo=timezone.utc)
        if messages:
            body = "\n".join(messages)
            subject = "Plant Kiosk — Today’s reminders"
            sent = self.notifier.send_email(subject, body) or self.notifier.send_sms(body) or self.notifier.send_webhook(subject, body)
            session.commit()
            return sent
        return False

FAQ_FILE = "plant_faq.json"

def load_qa():
    if not os.path.exists(FAQ_FILE):
        sample = [
            {"q": "What plant is safe for cats?", "a": "Spider Plant, Areca Palm, Boston Fern, and more are considered pet-safe."},
            {"q": "Why are my leaves yellow?", "a": "Often overwatering, poor drainage, or lack of nutrients."},
            {"q": "How often should I water succulents?", "a": "Let soil dry completely before watering (≈2–3 weeks)."},
        ]
        with open(FAQ_FILE, "w", encoding="utf-8") as f:
            json.dump(sample, f, indent=2)
    with open(FAQ_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_qa(qa_list):
    with open(FAQ_FILE, "w", encoding="utf-8") as f:
        json.dump(qa_list, f, indent=2)

PLANT_GREEN = "#27661a"
PLANT_LIGHT = "#e8f7e2"
PLANT_YELLOW = "#eedc82"
PLANT_DARK = "#11380c"
FONT = ("Segoe UI", 16)
BIGFONT = ("Segoe UI", 22, "bold")

def pil2ctk(pil_img, size):
    img = pil_img.copy().resize(size, Image.LANCZOS)
    return ctk.CTkImage(img, size=size)

def load_or_placeholder(img_path, size=(200,200)):
    if img_path and os.path.exists(img_path):
        img = Image.open(img_path)
    else:
        img = Image.new("RGB", size, PLANT_GREEN)
    return pil2ctk(img, size)

class AIIdentifier:
    """Plant.id integration if configured; otherwise uses a deterministic-ish local guess."""
    def __init__(self):
        self.api_key = cfg('AI','plant_id_api_key','').strip()
        self.enabled = bool(self.api_key and requests)

    def identify(self, image_path):
        if self.enabled:
            try:
                url = "https://api.plant.id/v3/identification"
                headers = {"Api-Key": self.api_key}
                with open(image_path, 'rb') as f:
                    files = {'images': (os.path.basename(image_path), f, 'application/octet-stream')}
                    data = {'similar_images': 'false', 'health': 'true'}
                    r = requests.post(url, headers=headers, files=files, data=data, timeout=15)
                if r.status_code//100 == 2:
                    j = r.json()
                    suggestions = j.get('result',{}).get('classification',{}).get('suggestions',[]) or \
                                  j.get('suggestions',[])  
                    if suggestions:
                        best = suggestions[0]
                        name = best.get('name') or best.get('plant_name') or 'Unknown'
                        conf = float(best.get('probability', best.get('confidence', 0)))  
                    else:
                        name, conf = 'Unknown', 0.0
                    disease = "Healthy"
                    health = j.get('result',{}).get('is_healthy', None)
                    if isinstance(health, bool) and not health:
                        disease = "Possible issue detected"
                    return name, conf, disease
            except Exception as e:
                pass
        plants = [p.name for p in session.query(Plant).all()]
        guess = random.choice(plants) if plants else "Unknown"
        conf = random.uniform(0.65, 0.98)
        disease = random.choice(["No disease detected", "Possible nutrient deficiency", "Leaf spots (fungal)", "Underwatering symptoms", "Healthy"])
        return guess, conf, disease

class PlantKioskApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Plant Kiosk")
        self.geometry("1300x850")
        self.minsize(1100, 700)
        self.attributes("-fullscreen", False)
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")
        self.configure(fg_color=PLANT_LIGHT)

        self.role = "Guest"
        self.cart = {}
        self.qa = load_qa()

        self.api = CloudAPI()
        self.sync = SyncManager(self.api)
        self.notifier = Notifier()
        self.reminders = ReminderEngine(self.notifier, poll_seconds=90)  # every 90s
        self.reminders.start()
        self.ai = AIIdentifier()

        self.sidebar = ctk.CTkFrame(self, width=180, fg_color=PLANT_GREEN)
        self.sidebar.pack(side="left", fill="y")
        self.logo = ctk.CTkLabel(self.sidebar, text="🌱\nPlant Kiosk", font=("Segoe UI", 24, "bold"),
                                 fg_color="transparent", text_color="white")
        self.logo.pack(pady=(24,12))

        nav_btns = [
            ("Home", self.show_home),
            ("Shop", self.show_shop),
            ("Schedules", self.show_schedules),
            ("Plant Info", self.show_profile),
            ("Q&A", self.show_qa),
            ("Plant AI", self.show_ai),
            ("Admin", self.show_admin),
            ("Logout", self.logout),
        ]
        for txt, cmd in nav_btns:
            btn = ctk.CTkButton(self.sidebar, text=txt, command=cmd, font=FONT,
                                fg_color=PLANT_GREEN, text_color="white", hover_color=PLANT_YELLOW)
            btn.pack(pady=7, fill="x", padx=18)

        self.main = ctk.CTkFrame(self, fg_color=PLANT_LIGHT)
        self.main.pack(side="left", fill="both", expand=True)

        self.footer = ctk.CTkLabel(self, text="Enhanced Plant Kiosk — Cloud-ready, AI-powered",
                                   font=("Segoe UI", 12), fg_color=PLANT_GREEN, text_color="white")
        self.footer.pack(side="bottom", fill="x")
        self.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.bind("<Escape>", lambda e: self.quit())

        self.show_home()

    def clear_main(self):
        for c in self.main.winfo_children():
            c.destroy()

    def show_home(self):
        self.clear_main()
        frm = ctk.CTkFrame(self.main, fg_color=PLANT_LIGHT)
        frm.pack(expand=True, fill="both")
        ctk.CTkLabel(frm, text="Welcome to the Plant Kiosk!", font=BIGFONT,
                     fg_color="transparent", text_color=PLANT_GREEN).pack(pady=30)
        txt = ("Explore, learn, and shop plants. This build adds cloud sync hooks, AI identify, and reminders.\n"
               "Use Admin → Sync Now to pull/push with a server (if configured).")
        ctk.CTkLabel(frm, text=txt, font=FONT, fg_color="transparent", text_color=PLANT_DARK).pack(pady=16)

    def show_shop(self):
        self.clear_main()
        ShopScreen(self.main, self)

    def show_profile(self):
        self.clear_main()
        ProfileScreen(self.main, self)

    def show_schedules(self):
        self.clear_main()
        ScheduleScreen(self.main, self)

    def show_ai(self):
        self.clear_main()
        PlantAIScreen(self.main, self)

    def show_qa(self):
        self.clear_main()
        QAScreen(self.main, self)

    def show_admin(self):
        if self.role != "Admin":
            pw = simpledialog.askstring("Admin Login", "Enter admin password:", show="*")
            if not pw or pw != ADMIN_PASSWORD:
                messagebox.showerror("Access denied", "Incorrect password.")
                return
            self.role = "Admin"
            self.footer.configure(text="Admin mode enabled")
        self.clear_main()
        AdminScreen(self.main, self)

    def logout(self):
        self.role = "Guest"
        self.footer.configure(text="Logged out. Guest mode.")
        self.show_home()

    def toggle_fullscreen(self):
        self.attributes("-fullscreen", not self.attributes("-fullscreen"))

    def alert(self, msg, title="Notice"):
        messagebox.showinfo(title, msg, parent=self)

class ShopScreen(ctk.CTkFrame):
    def __init__(self, parent, app: PlantKioskApp):
        super().__init__(parent, fg_color=PLANT_LIGHT)
        self.pack(fill="both", expand=True)
        self.app = app

        bar = ctk.CTkFrame(self, fg_color=PLANT_GREEN)
        bar.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(bar, text="Shop Plants", font=BIGFONT, fg_color="transparent", text_color="white").pack(side="left", padx=12)

        self.categories = ["All"] + [row[0] for row in session.query(Plant.category).distinct()]
        self.cat_var = ctk.StringVar(value="All")
        ctk.CTkComboBox(bar, variable=self.cat_var, values=self.categories, command=self.refresh, width=130).pack(side="left", padx=12)

        self.srch_var = ctk.StringVar()
        ctk.CTkEntry(bar, textvariable=self.srch_var, placeholder_text="Search...", width=220).pack(side="left", padx=12)
        ctk.CTkButton(bar, text="Go", command=self.refresh, fg_color=PLANT_YELLOW, text_color="black").pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Cart", command=self.show_cart, fg_color=PLANT_YELLOW, text_color="black").pack(side="right", padx=12)

        frm = ctk.CTkScrollableFrame(self, fg_color=PLANT_LIGHT)
        frm.pack(fill="both", expand=True, padx=8, pady=(5,15))
        self.product_area = frm
        self.refresh()

    def refresh(self, *a):
        for w in self.product_area.winfo_children():
            w.destroy()
        catsel = self.cat_var.get()
        q = session.query(Plant)
        if catsel != "All":
            q = q.filter(Plant.category==catsel)
        items = q.all()
        txt = self.srch_var.get().lower().strip()
        if txt:
            items = [i for i in items if txt in i.name.lower() or (i.species or '').lower().find(txt)>=0]
        # grid
        c, r = 0, 0
        for plant in items:
            card = ctk.CTkFrame(self.product_area, width=280, height=360, fg_color="#f7fff5")
            card.grid(row=r, column=c, padx=22, pady=18)
            img = load_or_placeholder(plant.images[0].image_path if plant.images else None, (180,180))
            ctk.CTkLabel(card, image=img, text="").pack(pady=(12,4))
            ctk.CTkLabel(card, text=plant.name, font=BIGFONT, text_color=PLANT_GREEN).pack()
            ctk.CTkLabel(card, text=f"${plant.price:.2f} | In stock: {plant.inventory}", font=FONT, text_color=PLANT_DARK).pack(pady=2)
            ctk.CTkButton(card, text="Details", command=lambda p=plant: self.show_detail(p), fg_color=PLANT_GREEN).pack(side="left", padx=12, pady=10)
            ctk.CTkButton(card, text="Add to Cart", command=lambda p=plant: self.add_to_cart(p), fg_color=PLANT_YELLOW, text_color=PLANT_DARK).pack(side="right", padx=12, pady=10)
            c += 1
            if c >= 3: c, r = 0, r+1

    def show_detail(self, plant: Plant):
        win = ctk.CTkToplevel(self.app)
        win.title(plant.name)
        win.geometry("520x700")
        img = load_or_placeholder(plant.images[0].image_path if plant.images else None, (320,320))
        ctk.CTkLabel(win, image=img, text="").pack(pady=12)
        info = (f"{plant.name} ({plant.species or ''})\n"
                f"Class: {plant.plant_class}\nGenus: {plant.genus}\n\n{plant.profile or ''}\n\n"
                f"Nutrition: {plant.recommended_nutrition}\nWatering: {plant.recommended_watering}\n"
                f"Price: ${plant.price:.2f}\nStock: {plant.inventory}\nCategory: {plant.category}")
        ctk.CTkLabel(win, text=info, font=FONT, text_color=PLANT_DARK, wraplength=460, fg_color=PLANT_LIGHT).pack(padx=14)
        ctk.CTkButton(win, text="Add to Cart", command=lambda:self.add_to_cart(plant)).pack(pady=12)

    def add_to_cart(self, plant: Plant):
        self.app.cart[plant.id] = self.app.cart.get(plant.id, 0)+1
        self.app.alert(f"{plant.name} added to cart.")

    def show_cart(self):
        win = ctk.CTkToplevel(self.app)
        win.title("Your Cart")
        win.geometry("480x520")
        ctk.CTkLabel(win, text="Shopping Cart", font=BIGFONT, fg_color=PLANT_GREEN, text_color="white").pack(fill="x")
        box = ctk.CTkScrollableFrame(win, fg_color=PLANT_LIGHT)
        box.pack(expand=True, fill="both")
        total = 0.0
        for pid, qty in self.app.cart.items():
            plant = session.query(Plant).get(pid)
            if not plant: continue
            item = ctk.CTkFrame(box, fg_color=PLANT_LIGHT)
            item.pack(fill="x", padx=10, pady=8)
            ctk.CTkLabel(item, text=f"{plant.name} x {qty}", font=FONT, width=240, anchor="w").pack(side="left")
            ctk.CTkLabel(item, text=f"${plant.price*qty:.2f}", font=FONT, width=110, anchor="e").pack(side="right")
            total += plant.price*qty
        ctk.CTkLabel(win, text=f"Total: ${total:.2f}", font=BIGFONT, text_color=PLANT_GREEN).pack(pady=10)
        def checkout():
            if not self.app.cart:
                self.app.alert("Your cart is empty.")
                return
            for pid, qty in list(self.app.cart.items()):
                plant = session.query(Plant).get(pid)
                if plant: plant.inventory = max(0, plant.inventory-qty)
            session.commit()
            self.app.cart = {}
            self.app.alert("Thank you for your purchase! (Demo only, no payment processed.)")
            win.destroy()
            self.refresh()
        ctk.CTkButton(win, text="Checkout", command=checkout, fg_color=PLANT_GREEN).pack(pady=6)
        ctk.CTkButton(win, text="Close", command=win.destroy, fg_color=PLANT_YELLOW, text_color=PLANT_DARK).pack(pady=2)

class ProfileScreen(ctk.CTkFrame):
    def __init__(self, parent, app: PlantKioskApp):
        super().__init__(parent, fg_color=PLANT_LIGHT)
        self.pack(fill="both", expand=True)
        self.app = app

        top = ctk.CTkFrame(self, fg_color=PLANT_GREEN)
        top.pack(fill="x", pady=8)
        ctk.CTkLabel(top, text="Plant Profile / Search", font=BIGFONT, fg_color="transparent", text_color="white").pack(side="left", padx=18)
        self.search_var = ctk.StringVar()
        ctk.CTkEntry(top, textvariable=self.search_var, placeholder_text="Enter plant name...", width=220).pack(side="left", padx=12)
        ctk.CTkButton(top, text="Search", command=self.search, fg_color=PLANT_YELLOW, text_color=PLANT_DARK).pack(side="left", padx=6)
        self.profile = ctk.CTkFrame(self, fg_color="#fff")
        self.profile.pack(fill="both", expand=True, padx=15, pady=15)

    def search(self):
        for c in self.profile.winfo_children(): c.destroy()
        name = self.search_var.get().strip()
        if not name:
            ctk.CTkLabel(self.profile, text="Enter a plant name to search.", font=FONT, text_color="gray").pack(pady=60)
            return
        plant = session.query(Plant).filter(Plant.name.ilike(name)).first()
        if not plant:
            ctk.CTkLabel(self.profile, text="Plant not found.", font=FONT, text_color="gray").pack(pady=60)
            return
        img = load_or_placeholder(plant.images[0].image_path if plant.images else None, (240,240))
        ctk.CTkLabel(self.profile, image=img, text="").pack(pady=10)
        ctk.CTkLabel(self.profile, text=f"{plant.name} ({plant.species or ''})", font=BIGFONT, text_color=PLANT_GREEN).pack()
        info = f"Class: {plant.plant_class or '-'}   Genus: {plant.genus or '-'}   Category: {plant.category or '-'}"
        ctk.CTkLabel(self.profile, text=info, font=FONT, text_color=PLANT_DARK).pack()
        ctk.CTkLabel(self.profile, text=plant.profile or "", font=FONT, wraplength=780, text_color=PLANT_DARK).pack(pady=4)
        ctk.CTkLabel(self.profile, text=f"Nutrition: {plant.recommended_nutrition or '-'}", font=FONT, text_color=PLANT_DARK).pack()
        ctk.CTkLabel(self.profile, text=f"Watering: {plant.recommended_watering or '-'}", font=FONT, text_color=PLANT_DARK).pack()
        if plant.knowledge:
            kn = plant.knowledge
            ctk.CTkLabel(self.profile, text=f"Sunlight: {kn.sunlight_requirements or '-'}", font=FONT, text_color=PLANT_DARK).pack()
            ctk.CTkLabel(self.profile, text=f"Water: {kn.water_requirements or '-'}", font=FONT, text_color=PLANT_DARK).pack()
            ctk.CTkLabel(self.profile, text=f"Growth cycle: {kn.growth_cycle_info or '-'}", font=FONT, text_color=PLANT_DARK).pack()
            ctk.CTkLabel(self.profile, text=f"Soil type: {kn.soil_type or '-'}", font=FONT, text_color=PLANT_DARK).pack()
        ctk.CTkLabel(self.profile, text=f"Safe to consume: {'Yes' if plant.safe_to_consume else 'No'}",
                     font=FONT, text_color=PLANT_GREEN if plant.safe_to_consume else "red").pack(pady=5)

class ScheduleScreen(ctk.CTkFrame):
    def __init__(self, parent, app: PlantKioskApp):
        super().__init__(parent, fg_color=PLANT_LIGHT)
        self.pack(fill="both", expand=True)
        self.app = app
        top = ctk.CTkFrame(self, fg_color=PLANT_GREEN)
        top.pack(fill="x")
        ctk.CTkLabel(top, text="Plant Schedules", font=BIGFONT, text_color="white").pack(side="left", padx=12, pady=10)

        ctk.CTkButton(top, text="Notification Settings", command=self.open_notify_settings,
                      fg_color=PLANT_YELLOW, text_color=PLANT_DARK).pack(side="right", padx=10, pady=10)
        ctk.CTkButton(top, text="Refresh", command=self.refresh, fg_color=PLANT_YELLOW, text_color=PLANT_DARK).pack(side="right", padx=10, pady=10)

        self.box = ctk.CTkScrollableFrame(self, fg_color=PLANT_LIGHT)
        self.box.pack(fill="both", expand=True, padx=15, pady=12)
        self.refresh()

    def open_notify_settings(self):
        win = ctk.CTkToplevel(self.app)
        win.title("Notifications")
        win.geometry("460x520")
        fields = [
            ("Enable (true/false)", ("NOTIFY","enabled")),
            ("Email enabled (true/false)", ("NOTIFY","email_enabled")),
            ("Email from", ("NOTIFY","email_from")),
            ("Email to", ("NOTIFY","email_to")),
            ("SMTP host", ("NOTIFY","smtp_host")),
            ("SMTP port", ("NOTIFY","smtp_port")),
            ("SMTP user", ("NOTIFY","smtp_user")),
            ("SMTP pass", ("NOTIFY","smtp_pass")),
            ("SMS enabled (true/false)", ("NOTIFY","sms_enabled")),
            ("Twilio SID", ("NOTIFY","twilio_sid")),
            ("Twilio Token", ("NOTIFY","twilio_token")),
            ("Twilio From", ("NOTIFY","twilio_from")),
            ("Phone to", ("NOTIFY","phone_to")),
            ("Webhook URL (optional)", ("NOTIFY","webhook_url")),
        ]
        entries = {}
        for lbl,(sec,key) in fields:
            ctk.CTkLabel(win, text=lbl, font=FONT).pack(anchor="w", padx=10, pady=3)
            val = cfg(sec,key,"")
            ent = ctk.CTkEntry(win); ent.insert(0, val or ""); ent.pack(fill="x", padx=10)
            entries[(sec,key)] = ent

        def save():
            for (sec,key),ent in entries.items():
                if not config.has_section(sec): config.add_section(sec)
                config.set(sec,key, ent.get())
            with open(CONFIG_FILE,'w') as f:
                config.write(f)
            self.app.notifier = Notifier()
            self.app.reminders.notifier = self.app.notifier
            self.app.alert("Notification settings saved.")
            win.destroy()
        ctk.CTkButton(win, text="Save", command=save, fg_color=PLANT_GREEN).pack(pady=12)

    def refresh(self):
        for w in self.box.winfo_children(): w.destroy()
        plants = session.query(Plant).all()
        now = datetime.now()
        for plant in plants:
            nextw = None
            if plant.watering_schedules:
                nextw = min((ws.next_water for ws in plant.watering_schedules if ws.next_water), default=None)
            nextn = None
            if plant.nutrient_schedules:
                nextn = min((ns.next_feed for ns in plant.nutrient_schedules if ns.next_feed), default=None)
            if not nextw and not nextn: continue
            fr = ctk.CTkFrame(self.box, fg_color="#e2ffe0")
            fr.pack(fill="x", padx=10, pady=6)
            ctk.CTkLabel(fr, text=plant.name, font=BIGFONT, text_color=PLANT_GREEN).pack(side="left", padx=10)
            if nextw:
                overdue = (now - (nextw.replace(tzinfo=None) if isinstance(nextw, datetime) else nextw)).days >= 0
                ctk.CTkLabel(fr, text=f"Water: {nextw.strftime('%Y-%m-%d')}", font=FONT,
                             text_color="red" if overdue else PLANT_DARK).pack(side="left", padx=15)
            if nextn:
                ctk.CTkLabel(fr, text=f"Feed: {nextn.strftime('%Y-%m-%d')}", font=FONT, text_color=PLANT_DARK).pack(side="left", padx=8)

class QAScreen(ctk.CTkFrame):
    def __init__(self, parent, app: PlantKioskApp):
        super().__init__(parent, fg_color=PLANT_LIGHT)
        self.pack(fill="both", expand=True)
        self.app = app
        ctk.CTkLabel(self, text="Plant Q&A / FAQ", font=BIGFONT, text_color=PLANT_GREEN).pack(pady=18)
        self.qentry = ctk.CTkEntry(self, placeholder_text="Ask a plant question...", width=460, font=FONT)
        self.qentry.pack(pady=8)
        ctk.CTkButton(self, text="Search", command=self.search, fg_color=PLANT_GREEN).pack()
        self.result = ctk.CTkTextbox(self, width=900, height=240, font=FONT)
        self.result.pack(pady=22, fill="x", expand=True)
        if self.app.role == "Admin":
            ctk.CTkButton(self, text="Add FAQ", command=self.add_faq, fg_color=PLANT_YELLOW, text_color=PLANT_DARK).pack(pady=4)
            ctk.CTkButton(self, text="Edit FAQ", command=self.edit_faq, fg_color=PLANT_YELLOW, text_color=PLANT_DARK).pack(pady=4)

    def search(self):
        q = self.qentry.get().lower().strip()
        if not q:
            self.result.delete("1.0", "end")
            self.result.insert("end", "Enter a question to search.")
            return
        for faq in self.app.qa:
            if q in faq["q"].lower():
                self.result.delete("1.0", "end"); self.result.insert("end", f"Q: {faq['q']}\nA: {faq['a']}"); return
        for faq in self.app.qa:
            if any(word in faq["q"].lower() or word in faq["a"].lower() for word in q.split()):
                self.result.delete("1.0", "end"); self.result.insert("end", f"Q: {faq['q']}\nA: {faq['a']}"); return
        self.result.delete("1.0", "end"); self.result.insert("end", "No FAQ matched. (Admins can add answers.)")

    def add_faq(self):
        q = simpledialog.askstring("Add FAQ", "Enter question:");  a = simpledialog.askstring("Add FAQ", "Enter answer:") if q else None
        if q and a:
            self.app.qa.append({"q": q, "a": a}); save_qa(self.app.qa); self.app.alert("FAQ added.")

    def edit_faq(self):
        idx = simpledialog.askinteger("Edit FAQ", f"Which FAQ # to edit? (1-{len(self.app.qa)})")
        if not idx or idx < 1 or idx > len(self.app.qa): return
        faq = self.app.qa[idx-1]
        q = simpledialog.askstring("Edit Question", "Edit question:", initialvalue=faq["q"])
        a = simpledialog.askstring("Edit Answer", "Edit answer:", initialvalue=faq["a"]) if q else None
        if q and a:
            self.app.qa[idx-1] = {"q": q, "a": a}; save_qa(self.app.qa); self.app.alert("FAQ updated.")

class PlantAIScreen(ctk.CTkFrame):
    def __init__(self, parent, app: PlantKioskApp):
        super().__init__(parent, fg_color=PLANT_LIGHT)
        self.pack(fill="both", expand=True)
        self.app = app
        ctk.CTkLabel(self, text="Plant AI: Identify Plant / Diagnose", font=BIGFONT, text_color=PLANT_GREEN).pack(pady=18)
        ctk.CTkButton(self, text="Select Image", command=self.choose_img, fg_color=PLANT_GREEN).pack(pady=12)
        self.img_label = ctk.CTkLabel(self, text="", fg_color=PLANT_LIGHT); self.img_label.pack(pady=5)
        self.result = ctk.CTkTextbox(self, width=820, height=240, font=FONT); self.result.pack(pady=14)
        self.img_path = None

    def choose_img(self):
        path = filedialog.askopenfilename(title="Choose plant image", filetypes=[("Image Files","*.jpg *.png *.jpeg *.bmp")])
        if not path: return
        self.img_path = path
        img = Image.open(path).resize((240,240), Image.LANCZOS)
        self.img_label.configure(image=ctk.CTkImage(img, size=(240,240)), text="")
        self.result.delete("1.0","end"); self.result.insert("end", "Processing...\n")
        threading.Thread(target=self._run_ai, args=(path,), daemon=True).start()

    def _run_ai(self, path):
        try:
            name, conf, disease = self.app.ai.identify(path)
        except Exception as e:
            name, conf, disease = "Unknown", 0.0, f"Error: {e}"
        self.after(0, lambda: self.display_result(name, conf, disease))

    def display_result(self, plant, confidence, disease):
        self.result.delete("1.0","end")
        self.result.insert("end", f"Identified as: {plant}\nConfidence: {confidence*100:.1f}%\nDiagnosis: {disease}\n")

class AdminScreen(ctk.CTkFrame):
    def __init__(self, parent, app: PlantKioskApp):
        super().__init__(parent, fg_color=PLANT_LIGHT)
        self.pack(fill="both", expand=True)
        self.app = app
        ctk.CTkLabel(self, text="Admin Panel", font=BIGFONT, text_color=PLANT_GREEN).pack(pady=18)

        btns = [
            ("Import Plants (CSV/JSON)", self.import_plants, PLANT_YELLOW),
            ("Export Plants (JSON)", self.export_plants, PLANT_YELLOW),
            ("Add New Plant", self.add_plant, PLANT_GREEN),
            ("Edit Plant", self.edit_plant, PLANT_GREEN),
            ("Upload Image to Plant", self.upload_img, PLANT_GREEN),
            ("Low-Stock Report", self.low_stock_report, PLANT_YELLOW),
            ("Merge Update (CSV)", self.merge_update_csv, PLANT_YELLOW),
            ("Backup DB", self.backup_db, PLANT_YELLOW),
            ("Sync Now (Pull)", self.sync_pull, PLANT_GREEN),
            ("Sync Now (Push)", self.sync_push, PLANT_GREEN),
            ("Notification Settings", self.open_notify_settings, PLANT_YELLOW),
            ("Logout Admin", app.logout, PLANT_DARK),
        ]
        for text, cmd, color in btns:
            ctk.CTkButton(self, text=text, command=cmd, fg_color=color, text_color=("black" if color==PLANT_YELLOW else "white")).pack(pady=7)

    def open_notify_settings(self):
        ScheduleScreen(self, self.app).open_notify_settings()

    def sync_pull(self):
        ok, msg = self.app.sync.pull()
        self.app.alert(msg, "Cloud Pull" if ok else "Cloud Pull Error")

    def sync_push(self):
        ok, msg = self.app.sync.push()
        self.app.alert(msg, "Cloud Push" if ok else "Cloud Push Error")

    def low_stock_report(self):
        thresh = simpledialog.askinteger("Low Stock", "Threshold (<=):", initialvalue=3)
        if thresh is None: return
        low = session.query(Plant).filter(Plant.inventory <= thresh).all()
        if not low:
            self.app.alert("No low-stock items at or below threshold.")
            return
        lines = [f"{p.name} — {p.inventory}" for p in low]
        self.app.alert("Low stock:\n\n" + "\n".join(lines))

    def merge_update_csv(self):
        file = filedialog.askopenfilename(filetypes=[("CSV","*.csv")], title="CSV with name + fields to update")
        if not file: return
        rows = []
        with open(file,"r",encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        updated = 0
        for row in rows:
            name = row.get("name")
            if not name: continue
            p = session.query(Plant).filter_by(name=name).first()
            if not p: continue
            for key in ["profile","species","plant_class","genus","recommended_nutrition","recommended_watering","category"]:
                if row.get(key): setattr(p, key, row.get(key))
            if row.get("safe_to_consume") in ("True","False","true","false","1","0"):
                p.safe_to_consume = row.get("safe_to_consume").lower() in ("true","1")
            if row.get("price"):
                try: p.price = float(row.get("price"))
                except: pass
            if row.get("inventory"):
                try: p.inventory = int(row.get("inventory"))
                except: pass
            p.updated_at = utcnow()
            updated += 1
        session.commit()
        self.app.alert(f"Merged CSV updates into {updated} plants.")

    def backup_db(self):
        dest = filedialog.asksaveasfilename(defaultextension=".db", title="Save DB backup as")
        if not dest: return
        session.commit()
        shutil.copyfile(DB_FILE, dest)
        self.app.alert("Database backed up.")

    def import_plants(self):
        file = filedialog.askopenfilename(filetypes=[("CSV","*.csv"),("JSON","*.json")])
        if not file: return
        if file.endswith(".csv"):
            with open(file,"r",encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                name = row.get("name")
                if not name: continue
                if session.query(Plant).filter_by(name=name).first(): continue
                session.add(Plant(
                    name=name,
                    profile=row.get("profile"),
                    species=row.get("species"),
                    plant_class=row.get("plant_class"),
                    genus=row.get("genus"),
                    recommended_nutrition=row.get("recommended_nutrition"),
                    safe_to_consume=row.get("safe_to_consume")=="True",
                    recommended_watering=row.get("recommended_watering"),
                    price=float(row.get("price", "0.0")),
                    inventory=int(row.get("inventory","0")),
                    category=row.get("category") or "General"
                ))
            session.commit()
            self.app.alert("Plants imported from CSV.")
        elif file.endswith(".json"):
            with open(file,"r",encoding="utf-8") as f:
                data = json.load(f)
            for pdict in data:
                name = pdict.get("name")
                if not name: continue
                if session.query(Plant).filter_by(name=name).first(): continue
                session.add(Plant(
                    name=name,
                    profile=pdict.get("profile",""),
                    species=pdict.get("species",""),
                    plant_class=pdict.get("plant_class",""),
                    genus=pdict.get("genus",""),
                    recommended_nutrition=pdict.get("recommended_nutrition",""),
                    safe_to_consume=pdict.get("safe_to_consume",False),
                    recommended_watering=pdict.get("recommended_watering",""),
                    price=float(pdict.get("price",0.0)),
                    inventory=int(pdict.get("inventory",0)),
                    category=pdict.get("category","General")
                ))
            session.commit()
            self.app.alert("Plants imported from JSON.")

    def export_plants(self):
        file = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if not file: return
        data = []
        for plant in session.query(Plant).all():
            data.append({
                "name": plant.name,
                "profile": plant.profile,
                "species": plant.species,
                "plant_class": plant.plant_class,
                "genus": plant.genus,
                "recommended_nutrition": plant.recommended_nutrition,
                "safe_to_consume": plant.safe_to_consume,
                "recommended_watering": plant.recommended_watering,
                "price": plant.price,
                "inventory": plant.inventory,
                "category": plant.category
            })
        with open(file,"w",encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.app.alert("Plants exported as JSON.")

    def add_plant(self):
        win = ctk.CTkToplevel(self.app)
        win.title("Add New Plant")
        win.geometry("520x650")
        fields = [
            ("Name", "name"), ("Profile", "profile"),
            ("Species", "species"), ("Class", "plant_class"),
            ("Genus", "genus"), ("Nutrition", "recommended_nutrition"),
            ("Safe to Consume (True/False)", "safe_to_consume"),
            ("Watering", "recommended_watering"),
            ("Price", "price"), ("Inventory", "inventory"), ("Category", "category")
        ]
        entries = {}
        for i, (lbl, key) in enumerate(fields):
            ctk.CTkLabel(win, text=lbl, font=FONT).pack()
            ent = ctk.CTkEntry(win); ent.pack(); entries[key] = ent
        def submit():
            name = entries["name"].get().strip()
            if not name: self.app.alert("Plant name required."); return
            if session.query(Plant).filter_by(name=name).first():
                self.app.alert("Plant already exists."); return
            plant = Plant(
                name=name,
                profile=entries["profile"].get(),
                species=entries["species"].get(),
                plant_class=entries["plant_class"].get(),
                genus=entries["genus"].get(),
                recommended_nutrition=entries["recommended_nutrition"].get(),
                safe_to_consume=(entries["safe_to_consume"].get() or "").lower() == "true",
                recommended_watering=entries["recommended_watering"].get(),
                price=float(entries["price"].get() or "0.0"),
                inventory=int(entries["inventory"].get() or "0"),
                category=entries["category"].get() or "General"
            )
            session.add(plant); session.commit()
            self.app.alert("New plant added."); win.destroy()
        ctk.CTkButton(win, text="Add Plant", command=submit, fg_color=PLANT_GREEN).pack(pady=12)

    def edit_plant(self):
        names = [p.name for p in session.query(Plant).all()]
        name = simpledialog.askstring("Edit Plant", f"Enter plant name to edit:\n\nOptions: {', '.join(names)}")
        if not name: return
        plant = session.query(Plant).filter_by(name=name).first()
        if not plant: self.app.alert("Plant not found."); return
        field = simpledialog.askstring("Edit Field", "Field to edit (name, profile, species, class, genus, nutrition, safe_to_consume, watering, price, inventory, category):")
        if not field: return
        val = simpledialog.askstring("New Value", "Enter new value:")
        if not val: return
        if field == "name": plant.name = val
        elif field == "profile": plant.profile = val
        elif field == "species": plant.species = val
        elif field == "class": plant.plant_class = val
        elif field == "genus": plant.genus = val
        elif field == "nutrition": plant.recommended_nutrition = val
        elif field == "safe_to_consume": plant.safe_to_consume = val.lower()=="true"
        elif field == "watering": plant.recommended_watering = val
        elif field == "price": plant.price = float(val)
        elif field == "inventory": plant.inventory = int(val)
        elif field == "category": plant.category = val
        else: self.app.alert("Unknown field."); return
        plant.updated_at = utcnow(); session.commit()
        self.app.alert(f"{name} updated.")

    def upload_img(self):
        names = [p.name for p in session.query(Plant).all()]
        name = simpledialog.askstring("Image Upload", f"Enter plant name for image:\n\nOptions: {', '.join(names)}")
        if not name: return
        plant = session.query(Plant).filter_by(name=name).first()
        if not plant: self.app.alert("Plant not found."); return
        file = filedialog.askopenfilename(filetypes=[("Image","*.jpg *.jpeg *.png *.bmp")])
        if not file: return
        if not os.path.exists("images"): os.makedirs("images")
        fname = os.path.basename(file); dest = os.path.join("images", f"{plant.name}_{fname}")
        with open(file,"rb") as fsrc, open(dest,"wb") as fdst: fdst.write(fsrc.read())
        session.add(PlantImage(plant_id=plant.id, image_path=dest)); session.commit()
        self.app.alert("Image added to plant.")

if __name__ == "__main__":
    try:
        app = PlantKioskApp()
        app.mainloop()
    finally:
        try:
            session.commit()
        except Exception:
            pass
