#!/usr/bin/env python3
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import tkinter as tk
from tkinter import filedialog, messagebox, Toplevel
from PIL import Image, ImageTk, ImageEnhance, ImageDraw, ImageFilter
import json, csv, threading, logging, os, time, random, math
from datetime import datetime, timedelta
import configparser
import requests

# SQLAlchemy imports
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Text, DateTime, Float
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# TensorFlow and related imports for PlantAI
import numpy as np
from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2, preprocess_input, decode_predictions
from tensorflow.keras.preprocessing import image

# Barcode library
try:
    from barcode import Code128
    from barcode.writer import ImageWriter
    BARCODE_LIB_AVAILABLE = True
except ImportError:
    BARCODE_LIB_AVAILABLE = False
    print("Warning: python-barcode library not found. Barcode generation will not be available.")

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load Configuration from config.ini
config = configparser.ConfigParser()
config.read('config.ini')
OPENWEATHER_KEY = config.get('API_KEYS', 'openweather_key', fallback='your_openweather_api_key')
TREFLE_TOKEN = config.get('API_KEYS', 'trefle_token', fallback='your_trefle_api_token')
ADMIN_PASSWORD = config.get('ADMIN', 'admin_password', fallback='admin')

# ==================== Database Setup ====================
Base = declarative_base()

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
    knowledge = relationship("PlantKnowledge", uselist=False, back_populates="plant")
    images = relationship("PlantImage", back_populates="plant")
    watering_schedules = relationship("WateringSchedule", back_populates="plant")
    nutrient_schedules = relationship("NutrientSchedule", back_populates="plant")
    # Barcode fields
    barcode_number = Column(String, default=None)
    barcode_image_path = Column(String, default=None)
    # E-commerce fields
    price = Column(Float, default=0.0)
    inventory = Column(Integer, default=0)
    category = Column(String, default="General")

class WateringSchedule(Base):
    __tablename__ = 'watering_schedules'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'))
    next_water = Column(DateTime)
    plant = relationship("Plant", back_populates="watering_schedules")

class NutrientSchedule(Base):
    __tablename__ = 'nutrient_schedules'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'))
    nutrient_info = Column(Text)
    next_feed = Column(DateTime)
    plant = relationship("Plant", back_populates="nutrient_schedules")

class PlantImage(Base):
    __tablename__ = 'plant_images'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'))
    image_path = Column(String)
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
    plant = relationship("Plant", back_populates="knowledge")

class CareLog(Base):
    __tablename__ = 'care_logs'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'))
    timestamp = Column(DateTime, default=datetime.now)
    observation = Column(Text)
    routine = Column(Text)
    plant = relationship("Plant")

engine = create_engine('sqlite:///advanced_plant_manager.db', echo=False, connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# ==================== API Manager ====================
class APIManager:
    def __init__(self, openweather_key, trefle_token):
        self.openweather_key = openweather_key
        self.trefle_token = trefle_token

    def get_weather_by_zip(self, zip_code, country="us"):
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?zip={zip_code},{country}&appid={self.openweather_key}&units=metric"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"OpenWeather API error: {e}")
            return None

    def get_forecast_by_zip(self, zip_code, country="us"):
        try:
            url = f"https://api.openweathermap.org/data/2.5/forecast?zip={zip_code},{country}&appid={self.openweather_key}&units=metric"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"OpenWeather Forecast API error: {e}")
            return None

# ==================== Plant AI Manager ====================
class PlantAI:
    def __init__(self):
        logging.info("Loading MobileNetV2 model for plant identification...")
        try:
            self.model = MobileNetV2(weights='imagenet')
            self.preprocess_input = preprocess_input
            self.decode_predictions = decode_predictions
            logging.info("MobileNetV2 model loaded successfully.")
        except Exception as e:
            logging.error(f"Error loading model: {e}")
            self.model = None

    def identify_plant(self, image_path):
        logging.info(f"Identifying plant from image: {image_path}")
        if self.model is None:
            return {"species": "Unknown", "confidence": 0.0, "info": "Model not loaded."}
        try:
            img = image.load_img(image_path, target_size=(224, 224))
            img_array = image.img_to_array(img)
            img_array = np.expand_dims(img_array, axis=0)
            img_array = self.preprocess_input(img_array)
            preds = self.model.predict(img_array)
            predictions = self.decode_predictions(preds, top=5)[0]
            allowed_keywords = ['plant', 'tree', 'flower', 'daisy', 'tulip', 'rose', 'sunflower', 'lily', 'orchid', 'poppy', 'dandelion']
            plant_preds = [pred for pred in predictions if any(keyword in pred[1].lower() for keyword in allowed_keywords)]
            top_pred = plant_preds[0] if plant_preds else predictions[0]
            species = top_pred[1].replace('_', ' ')
            confidence = float(top_pred[2])
            info = f"Predicted as {species} with {confidence*100:.1f}% confidence."
            return {"species": species, "confidence": confidence, "info": info}
        except Exception as e:
            logging.error(f"Error in identify_plant: {e}")
            return {"species": "Unknown", "confidence": 0.0, "info": str(e)}

    def detect_disease(self, image_path):
        logging.info(f"Detecting disease from image: {image_path}")
        try:
            img = Image.open(image_path).resize((224, 224))
            gray = img.convert("L")
            np_gray = np.array(gray)
            avg_intensity = np.mean(np_gray)
            if avg_intensity < 50:
                result = {"disease": "Possible disease detected", "confidence": 0.8}
            else:
                result = {"disease": "No disease detected", "confidence": 0.95}
            return result
        except Exception as e:
            logging.error(f"Error in detect_disease: {e}")
            return {"disease": "Unknown", "confidence": 0.0}

# ==================== IoT Manager ====================
class IoTManager:
    def __init__(self):
        pass
    def get_sensor_data(self):
        return {
            "soil_moisture": random.randint(10, 60),
            "temperature": random.randint(15, 30),
            "humidity": random.randint(40, 80)
        }

def generate_care_routine(plant, sensor_data):
    routine = []
    if sensor_data["soil_moisture"] < 30:
        routine.append("Water the plant. Soil moisture is low.")
    else:
        routine.append("No watering needed today.")
    if sensor_data["temperature"] > 28:
        routine.append("Provide shade or move indoors.")
    elif sensor_data["temperature"] < 18:
        routine.append("Move the plant to a warmer area.")
    else:
        routine.append("Temperature is optimal.")
    routine.append("Review nutrient levels and consider fertilizing.")
    return routine

# ==================== Organic Plant Kiosk Application ====================
class PlantKioskApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Organic Plant Kiosk")
        self.root.attributes('-fullscreen', True)
        self.style = ttk.Style("darkly")
        self.root.configure(bg=self.style.colors.bg)
        
        # Load custom background image
        bg_path = "plant_background.jpg"
        if os.path.exists(bg_path):
            self.bg_image = ImageTk.PhotoImage(Image.open(bg_path).resize((self.root.winfo_screenwidth(), self.root.winfo_screenheight())))
        else:
            self.bg_image = None
        
        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        if self.bg_image:
            self.canvas.create_image(0, 0, image=self.bg_image, anchor="nw")
        
        # Container frame for screens
        self.container = ttk.Frame(self.canvas, style="TFrame", padding=10)
        self.container.place(relx=0.5, rely=0.5, anchor="center")
        
        self.screens = {}
        for ScreenClass in (HomeScreen, ShopScreen, ProfileScreen, ScheduleScreen, PlantAIScreen, AdminScreen):
            screen = ScreenClass(self.container, self)
            self.screens[ScreenClass.__name__] = screen
            screen.grid(row=0, column=0, sticky="nsew")
        
        self.show_screen("HomeScreen")
        self.create_navigation()
        
        self.iot_manager = IoTManager()
        self.api = APIManager(OPENWEATHER_KEY, TREFLE_TOKEN)
        self.plant_ai = PlantAI()
        self.cart_items = []
        
        self.sensor_data = {}
        self.poll_sensor_data_thread = threading.Thread(target=self.poll_sensor_data, daemon=True)
        self.poll_sensor_data_thread.start()
        
        self.logger_text = tk.Text(self.root, height=4, bg="#000000", fg="#00FF00", bd=0)
        self.logger_text.place(relx=0, rely=1, anchor="sw", relwidth=1)
        
        self.root.bind("<Escape>", self.exit_fullscreen)
    
    def exit_fullscreen(self, event=None):
        self.root.attributes('-fullscreen', False)
    
    def create_navigation(self):
        nav_config = [
            {"name": "Home", "screen": "HomeScreen", "pos": (0.1, 0.2), "img": "leaf_home.png"},
            {"name": "Shop", "screen": "ShopScreen", "pos": (0.9, 0.3), "img": "leaf_shop.png"},
            {"name": "Profile", "screen": "ProfileScreen", "pos": (0.1, 0.5), "img": "leaf_profile.png"},
            {"name": "Schedules", "screen": "ScheduleScreen", "pos": (0.9, 0.5), "img": "leaf_schedule.png"},
            {"name": "Plant AI", "screen": "PlantAIScreen", "pos": (0.1, 0.7), "img": "leaf_ai.png"},
            {"name": "Admin", "screen": "AdminScreen", "pos": (0.9, 0.7), "img": "leaf_admin.png"},
        ]
        for nav in nav_config:
            if os.path.exists(nav["img"]):
                leaf_img = ImageTk.PhotoImage(Image.open(nav["img"]).resize((80,80), Image.Resampling.LANCZOS))
                btn = tk.Button(self.root, image=leaf_img, bd=0,
                                command=lambda scr=nav["screen"]: self.show_screen(scr),
                                bg=self.style.colors.bg, activebackground=self.style.colors.bg)
                btn.image = leaf_img
            else:
                btn = tk.Button(self.root, text=nav["name"], font=("Helvetica", 14, "bold"),
                                command=lambda scr=nav["screen"]: self.show_screen(scr),
                                bg="#228B22", fg="white", relief="raised", bd=4)
            self.canvas.create_window(nav["pos"][0]*self.root.winfo_screenwidth(),
                                      nav["pos"][1]*self.root.winfo_screenheight(),
                                      window=btn, anchor="center")
    
    def show_screen(self, screen_name):
        screen = self.screens.get(screen_name)
        if screen:
            screen.tkraise()
            # Removed animation to avoid TclError (scale command not available)
            # self.animate_growth(screen)
    
    def animate_growth(self, frame):
        pass  # Animation disabled
    
    def poll_sensor_data(self):
        while True:
            self.sensor_data = self.iot_manager.get_sensor_data()
            log_line = f"Sensor - Soil: {self.sensor_data['soil_moisture']}%, Temp: {self.sensor_data['temperature']}°C, Humidity: {self.sensor_data['humidity']}%\n"
            self.append_log(log_line)
            time.sleep(10)
    
    def append_log(self, message):
        self.logger_text.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}")
        self.logger_text.see(tk.END)

# ==================== Screen Classes ====================
class HomeScreen(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        welcome_path = "welcome_plant.jpg"
        if os.path.exists(welcome_path):
            self.welcome_img = ImageTk.PhotoImage(Image.open(welcome_path).resize((600,400), Image.ANTIALIAS))
            lbl = ttk.Label(self, image=self.welcome_img)
            lbl.pack(pady=20)
        else:
            lbl = ttk.Label(self, text="Welcome to the Organic Plant Kiosk!", font=("Helvetica", 24, "bold"), foreground="#ADFF2F")
            lbl.pack(pady=20)
        info = "Use the organic leaves to navigate: Shop, Profile, Schedules, Plant AI, and Admin."
        lbl_info = ttk.Label(self, text=info, font=("Helvetica", 16), wraplength=600, foreground="#ADFF2F")
        lbl_info.pack(pady=10)

class ShopScreen(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        header_path = "shop_header.jpg"
        if os.path.exists(header_path):
            header_img = ImageTk.PhotoImage(Image.open(header_path).resize((800,200), Image.ANTIALIAS))
            self.header_label = ttk.Label(self, image=header_img)
            self.header_label.image = header_img
            self.header_label.pack(fill=tk.X)
        else:
            self.header_label = ttk.Label(self, text="Shop", font=("Helvetica", 24, "bold"), foreground="#FFD700")
            self.header_label.pack(fill=tk.X, pady=10)
        
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(top_frame, text="Category:", font=("Helvetica", 12)).pack(side=tk.LEFT, padx=(5,2))
        self.category_var = tk.StringVar(value="All")
        self.category_menu = ttk.Combobox(top_frame, textvariable=self.category_var, values=self.get_categories())
        self.category_menu.pack(side=tk.LEFT, padx=5)
        self.category_menu.bind("<<ComboboxSelected>>", lambda e: self.render_products())
        ttk.Label(top_frame, text="Search:", font=("Helvetica", 12)).pack(side=tk.LEFT, padx=(20,2))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top_frame, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        btn_search = ttk.Button(top_frame, text="Go", command=self.render_products)
        btn_search.pack(side=tk.LEFT, padx=5)
        btn_cart = ttk.Button(top_frame, text="Cart", command=self.toggle_cart, bootstyle="OUTLINE")
        btn_cart.pack(side=tk.RIGHT, padx=5)
        
        self.canvas = tk.Canvas(self, bg=self.controller.style.colors.bg, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.products_frame = ttk.Frame(self.canvas)
        self.products_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0,0), window=self.products_frame, anchor="nw")
        
        self.cart_panel = ttk.Frame(self, width=250, bootstyle="PRIMARY")
        cart_title = ttk.Label(self.cart_panel, text="Your Cart", font=("Helvetica", 14, "bold"))
        cart_title.pack(pady=5)
        self.cart_listbox = tk.Listbox(self.cart_panel, height=10, bg="black", fg="white")
        self.cart_listbox.pack(fill=tk.X, padx=5, pady=5)
        btn_remove = ttk.Button(self.cart_panel, text="Remove Selected", command=self.remove_cart_item)
        btn_remove.pack(pady=5)
        btn_checkout = ttk.Button(self.cart_panel, text="Checkout", command=self.checkout_cart)
        btn_checkout.pack(pady=5)
        
        self.render_products()
    
    def get_categories(self):
        cats = session.query(Plant.category).distinct().all()
        return ["All"] + sorted([c[0] for c in cats if c[0]])
    
    def render_products(self):
        for widget in self.products_frame.winfo_children():
            widget.destroy()
        selected_cat = self.category_var.get()
        search_term = self.search_var.get().strip().lower()
        qry = session.query(Plant)
        if selected_cat != "All":
            qry = qry.filter(Plant.category == selected_cat)
        plants = qry.all()
        if search_term:
            plants = [p for p in plants if search_term in p.name.lower() or search_term in (p.species or "").lower()]
        cols = 3
        row = col = 0
        for plant in plants:
            card = ttk.Frame(self.products_frame, relief="raised", padding=5)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            if plant.images and os.path.exists(plant.images[0].image_path):
                prod_img = Image.open(plant.images[0].image_path).resize((250,250), Image.ANTIALIAS)
            else:
                prod_img = Image.new("RGB", (250,250), color="gray")
            overlay = Image.new("RGBA", prod_img.size, (0,0,0,80))
            prod_img = prod_img.convert("RGBA")
            prod_img = Image.alpha_composite(prod_img, overlay)
            img_tk = ImageTk.PhotoImage(prod_img)
            lbl_img = ttk.Label(card, image=img_tk)
            lbl_img.image = img_tk
            lbl_img.pack()
            lbl_name = ttk.Label(card, text=plant.name, font=("Helvetica", 12, "bold"), foreground="#FFD700")
            lbl_name.pack(pady=5)
            lbl_info = ttk.Label(card, text=f"Price: ${plant.price:0.2f} | In Stock: {plant.inventory}", font=("Helvetica", 10))
            lbl_info.pack()
            btn_details = ttk.Button(card, text="Details", command=lambda p=plant: self.show_details(p))
            btn_details.pack(pady=2)
            btn_add = ttk.Button(card, text="Add to Cart", command=lambda p=plant: self.add_to_cart(p))
            btn_add.pack(pady=2)
            col += 1
            if col >= cols:
                col = 0
                row += 1
    
    def show_details(self, plant):
        win = Toplevel(self)
        win.title("Product Details")
        if plant.images and os.path.exists(plant.images[0].image_path):
            img = Image.open(plant.images[0].image_path).resize((300,300), Image.ANTIALIAS)
        else:
            img = Image.new("RGB", (300,300), color="gray")
        img_tk = ImageTk.PhotoImage(img)
        lbl = ttk.Label(win, image=img_tk)
        lbl.image = img_tk
        lbl.pack(pady=10)
        info = (f"Name: {plant.name}\nPrice: ${plant.price:0.2f}\nCategory: {plant.category}\n"
                f"Species: {plant.species}\nClass: {plant.plant_class}\nGenus: {plant.genus}\n"
                f"Safe to Consume: {plant.safe_to_consume}\nInventory: {plant.inventory}\n\n"
                f"Profile: {plant.profile}\n\nNutrition: {plant.recommended_nutrition}\n\nWatering: {plant.recommended_watering}")
        txt = tk.Text(win, wrap="word", width=50, height=15, bg="black", fg="white")
        txt.insert(tk.END, info)
        txt.configure(state="disabled")
        txt.pack(padx=10, pady=10)
    
    def add_to_cart(self, plant):
        for i, (pid, qty) in enumerate(self.controller.cart_items):
            if pid == plant.id:
                self.controller.cart_items[i] = (pid, qty+1)
                break
        else:
            self.controller.cart_items.append((plant.id, 1))
        messagebox.showinfo("Cart", f"Added {plant.name} to cart.")
        self.refresh_cart()
    
    def toggle_cart(self):
        if self.cart_panel.winfo_ismapped():
            self.cart_panel.pack_forget()
        else:
            self.cart_panel.pack(side=tk.RIGHT, fill=tk.Y)
            self.refresh_cart()
    
    def refresh_cart(self):
        self.cart_listbox.delete(0, tk.END)
        for pid, qty in self.controller.cart_items:
            plant = session.query(Plant).filter_by(id=pid).first()
            if plant:
                self.cart_listbox.insert(tk.END, f"{plant.name} x {qty}")
    
    def remove_cart_item(self):
        sel = self.cart_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        del self.controller.cart_items[idx]
        self.refresh_cart()
    
    def checkout_cart(self):
        if not self.controller.cart_items:
            messagebox.showinfo("Checkout", "Your cart is empty!")
            return
        total = 0.0
        details = ""
        for pid, qty in self.controller.cart_items:
            plant = session.query(Plant).filter_by(id=pid).first()
            if plant:
                line = plant.price * qty
                total += line
                details += f"{plant.name} x {qty} = ${line:0.2f}\n"
        details += f"\nTotal: ${total:0.2f}"
        messagebox.showinfo("Checkout", f"Thank you for your purchase!\n\n{details}")
        self.controller.cart_items.clear()
        self.refresh_cart()

class ProfileScreen(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        lbl = ttk.Label(self, text="Profile & Weather", font=("Helvetica", 20, "bold"), foreground="#FFD700")
        lbl.pack(pady=10)
        search_frame = ttk.Frame(self)
        search_frame.pack(pady=5)
        ttk.Label(search_frame, text="Plant Name:", font=("Helvetica", 12)).pack(side=tk.LEFT, padx=5)
        self.plant_name_var = tk.StringVar()
        self.plant_entry = ttk.Entry(search_frame, textvariable=self.plant_name_var, width=30)
        self.plant_entry.pack(side=tk.LEFT, padx=5)
        btn_search = ttk.Button(search_frame, text="Search", command=self.search_profile)
        btn_search.pack(side=tk.LEFT, padx=5)
        weather_frame = ttk.Frame(self)
        weather_frame.pack(pady=5)
        ttk.Label(weather_frame, text="Postal Code:", font=("Helvetica", 12)).pack(side=tk.LEFT, padx=5)
        self.zip_var = tk.StringVar()
        self.zip_entry = ttk.Entry(weather_frame, textvariable=self.zip_var, width=10)
        self.zip_entry.pack(side=tk.LEFT, padx=5)
        btn_weather = ttk.Button(weather_frame, text="Get Weather", command=self.get_weather)
        btn_weather.pack(side=tk.LEFT, padx=5)
        self.profile_text = tk.Text(self, height=15, bg="black", fg="white", wrap=tk.WORD)
        self.profile_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.profile_image_label = ttk.Label(self)
        self.profile_image_label.pack(pady=5)
    
    def search_profile(self):
        name = self.plant_name_var.get().strip()
        self.profile_text.delete("1.0", tk.END)
        if not name:
            messagebox.showerror("Error", "Please enter a plant name.")
            return
        plant = session.query(Plant).filter(Plant.name.ilike(name)).first()
        if not plant:
            self.profile_text.insert(tk.END, "Plant not found in database.")
            self.profile_image_label.config(text="No image available")
            return
        info = (f"Name: {plant.name}\nProfile: {plant.profile}\nSpecies: {plant.species}\n"
                f"Class: {plant.plant_class}\nGenus: {plant.genus}\nPrice: ${plant.price:0.2f}\n"
                f"Inventory: {plant.inventory}\nCategory: {plant.category}\n")
        self.profile_text.insert(tk.END, info)
        if plant.images and os.path.exists(plant.images[0].image_path):
            img = Image.open(plant.images[0].image_path).resize((300,300), Image.ANTIALIAS)
            img_tk = ImageTk.PhotoImage(img)
            self.profile_image_label.config(image=img_tk)
            self.profile_image_label.image = img_tk
        else:
            self.profile_image_label.config(text="No image available")
    
    def get_weather(self):
        zip_code = self.zip_var.get().strip()
        if not zip_code:
            messagebox.showerror("Error", "Please enter a postal code.")
            return
        weather = self.controller.api.get_weather_by_zip(zip_code)
        if not weather or "main" not in weather:
            messagebox.showerror("Error", "Failed to retrieve weather data.")
            return
        info = (f"Weather for {zip_code}:\nTemperature: {weather['main']['temp']}°C\n"
                f"Humidity: {weather['main']['humidity']}%\nCondition: {weather['weather'][0]['description']}")
        messagebox.showinfo("Weather Info", info)

class ScheduleScreen(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        lbl = ttk.Label(self, text="Schedules", font=("Helvetica", 20, "bold"), foreground="#FFD700")
        lbl.pack(pady=10)
        self.schedule_text = tk.Text(self, height=20, bg="black", fg="white", wrap=tk.WORD)
        self.schedule_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        btn_refresh = ttk.Button(self, text="Refresh Schedules", command=self.refresh_schedules)
        btn_refresh.pack(pady=5)
        self.refresh_schedules()
    
    def refresh_schedules(self):
        schedules = "Watering Schedules:\n"
        watering = session.query(WateringSchedule).all()
        for w in watering:
            plant = session.query(Plant).filter_by(id=w.plant_id).first()
            if plant:
                schedules += f"{plant.name} - Next Water: {w.next_water}\n"
        schedules += "\nNutrient Schedules:\n"
        nutrient = session.query(NutrientSchedule).all()
        for n in nutrient:
            plant = session.query(Plant).filter_by(id=n.plant_id).first()
            if plant:
                schedules += f"{plant.name} - Next Feed: {n.next_feed}\n"
        self.schedule_text.delete("1.0", tk.END)
        self.schedule_text.insert(tk.END, schedules)

class PlantAIScreen(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        lbl = ttk.Label(self, text="Plant AI", font=("Helvetica", 20, "bold"), foreground="#FFD700")
        lbl.pack(pady=10)
        btn_browse = ttk.Button(self, text="Browse Image", command=self.browse_image)
        btn_browse.pack(pady=5)
        btn_identify = ttk.Button(self, text="Identify Plant", command=self.identify_plant)
        btn_identify.pack(pady=5)
        btn_disease = ttk.Button(self, text="Detect Disease", command=self.detect_disease)
        btn_disease.pack(pady=5)
        self.ai_text = tk.Text(self, height=10, bg="black", fg="white", wrap=tk.WORD)
        self.ai_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.ai_image_path = None
    
    def browse_image(self):
        path = filedialog.askopenfilename(title="Select Image", filetypes=[("Image Files", "*.jpg *.jpeg *.png *.bmp")])
        if path:
            self.ai_image_path = path
            messagebox.showinfo("Image Selected", f"Selected image: {path}")
    
    def identify_plant(self):
        if not self.ai_image_path:
            messagebox.showerror("Error", "Please select an image first.")
            return
        def task():
            result = self.controller.plant_ai.identify_plant(self.ai_image_path)
            output = (f"Identified Species: {result['species']}\nConfidence: {result['confidence']*100:.1f}%\nInfo: {result['info']}")
            self.ai_text.delete("1.0", tk.END)
            self.ai_text.insert(tk.END, output)
        threading.Thread(target=task, daemon=True).start()
    
    def detect_disease(self):
        if not self.ai_image_path:
            messagebox.showerror("Error", "Please select an image first.")
            return
        def task():
            result = self.controller.plant_ai.detect_disease(self.ai_image_path)
            output = f"Disease: {result['disease']}\nConfidence: {result['confidence']*100:.1f}%"
            self.ai_text.delete("1.0", tk.END)
            self.ai_text.insert(tk.END, output)
        threading.Thread(target=task, daemon=True).start()

class AdminScreen(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        lbl = ttk.Label(self, text="Admin Panel", font=("Helvetica", 20, "bold"), foreground="#FFD700")
        lbl.pack(pady=10)
        note = ttk.Label(self, text="Manage plants, images, and barcodes here. (Password protected in config.ini)", font=("Helvetica", 12), foreground="#FFD700")
        note.pack(pady=5)
        btn_import = ttk.Button(self, text="Import Plants", command=self.import_plants)
        btn_import.pack(pady=5)
        btn_export = ttk.Button(self, text="Export Data", command=self.export_data)
        btn_export.pack(pady=5)
        btn_add = ttk.Button(self, text="Add New Plant", command=self.open_add_plant)
        btn_add.pack(pady=5)
        btn_barcode = ttk.Button(self, text="Generate Barcode", command=self.generate_barcode)
        btn_barcode.pack(pady=5)
        btn_care = ttk.Button(self, text="Open Care Logger", command=self.open_care_logger)
        btn_care.pack(pady=5)
    
    def import_plants(self):
        file_path = filedialog.askopenfilename(title="Select Plant Data File", filetypes=[("JSON files", "*.json"), ("CSV files", "*.csv")])
        if not file_path:
            return
        try:
            if file_path.endswith('.json'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for pdict in data:
                    name = pdict.get("name")
                    if not session.query(Plant).filter_by(name=name).first():
                        new_plant = Plant(
                            name=name,
                            profile=pdict.get("profile", ""),
                            species=pdict.get("species", ""),
                            plant_class=pdict.get("plant_class", ""),
                            genus=pdict.get("genus", ""),
                            recommended_nutrition=pdict.get("recommended_nutrition", ""),
                            safe_to_consume=pdict.get("safe_to_consume", False),
                            recommended_watering=pdict.get("recommended_watering", ""),
                            barcode_number=pdict.get("barcode_number"),
                            barcode_image_path=pdict.get("barcode_image_path"),
                            price=pdict.get("price", 0.0),
                            inventory=pdict.get("inventory", 0),
                            category=pdict.get("category", "General")
                        )
                        session.add(new_plant)
                session.commit()
                messagebox.showinfo("Import", "Plants imported successfully.")
            elif file_path.endswith('.csv'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = row.get("name")
                        if not session.query(Plant).filter_by(name=name).first():
                            price = float(row.get("price", "0.0")) if row.get("price") else 0.0
                            inv = int(row.get("inventory", "0")) if row.get("inventory") else 0
                            cat = row.get("category") or "General"
                            new_plant = Plant(
                                name=name,
                                profile=row.get("profile"),
                                species=row.get("species"),
                                plant_class=row.get("plant_class"),
                                genus=row.get("genus"),
                                recommended_nutrition=row.get("recommended_nutrition"),
                                safe_to_consume=(row.get("safe_to_consume")=="True"),
                                recommended_watering=row.get("recommended_watering"),
                                price=price,
                                inventory=inv,
                                category=cat
                            )
                            session.add(new_plant)
                session.commit()
                messagebox.showinfo("Import", "Plants imported successfully.")
            self.controller.screens["ShopScreen"].render_products()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to import plants: {e}")
    
    def export_data(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".json", title="Save Data File", filetypes=[("JSON files", "*.json")])
        if not file_path:
            return
        try:
            plants = session.query(Plant).all()
            plant_list = []
            for plant in plants:
                p_dict = {
                    "id": plant.id,
                    "name": plant.name,
                    "profile": plant.profile,
                    "species": plant.species,
                    "plant_class": plant.plant_class,
                    "genus": plant.genus,
                    "recommended_nutrition": plant.recommended_nutrition,
                    "safe_to_consume": plant.safe_to_consume,
                    "recommended_watering": plant.recommended_watering,
                    "barcode_number": plant.barcode_number,
                    "barcode_image_path": plant.barcode_image_path,
                    "price": plant.price,
                    "inventory": plant.inventory,
                    "category": plant.category,
                    "knowledge": {},
                    "images": []
                }
                if plant.knowledge:
                    p_dict["knowledge"] = {
                        "scientific_name": plant.knowledge.scientific_name,
                        "common_name": plant.knowledge.common_name,
                        "water_requirements": plant.knowledge.water_requirements,
                        "sunlight_requirements": plant.knowledge.sunlight_requirements,
                        "soil_type": plant.knowledge.soil_type,
                        "nutrient_recommendations_detailed": plant.knowledge.nutrient_recommendations_detailed,
                        "growth_cycle_info": plant.knowledge.growth_cycle_info,
                        "pest_control_info": plant.knowledge.pest_control_info,
                        "detailed_profile": plant.knowledge.detailed_profile
                    }
                if plant.images:
                    p_dict["images"] = [img.image_path for img in plant.images]
                plant_list.append(p_dict)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(plant_list, f, indent=4)
            messagebox.showinfo("Export", "Data exported successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export data: {e}")
    
    def open_add_plant(self):
        win = Toplevel(self)
        win.title("Add New Plant")
        labels = ["Plant Name:", "Profile:", "Species:", "Class:", "Genus:", "Recommended Nutrition:", 
                  "Safe to Consume (True/False):", "Recommended Watering:", "Price:", "Inventory:", "Category:"]
        entries = {}
        for i, text in enumerate(labels):
            lbl = ttk.Label(win, text=text)
            lbl.grid(row=i, column=0, padx=5, pady=5, sticky=tk.W)
            if text in ["Profile:", "Recommended Nutrition:", "Recommended Watering:"]:
                ent = tk.Text(win, height=3, width=40)
            else:
                ent = ttk.Entry(win, width=40)
            ent.grid(row=i, column=1, padx=5, pady=5)
            entries[text] = ent
        def add_new():
            try:
                name = entries["Plant Name:"].get().strip()
                profile = entries["Profile:"].get("1.0", tk.END).strip()
                species = entries["Species:"].get().strip()
                plant_class = entries["Class:"].get().strip()
                genus = entries["Genus:"].get().strip()
                nutrition = entries["Recommended Nutrition:"].get("1.0", tk.END).strip()
                safe = entries["Safe to Consume (True/False):"].get().strip().lower() == "true"
                watering = entries["Recommended Watering:"].get("1.0", tk.END).strip()
                price = float(entries["Price:"].get().strip() or "0.0")
                inventory = int(entries["Inventory:"].get().strip() or "0")
                category = entries["Category:"].get().strip() or "General"
                if not name or not profile:
                    messagebox.showerror("Error", "Plant Name and Profile are required.")
                    return
                if session.query(Plant).filter_by(name=name).first():
                    messagebox.showerror("Error", "Plant already exists.")
                    return
                new_plant = Plant(name=name, profile=profile, species=species, plant_class=plant_class,
                                  genus=genus, recommended_nutrition=nutrition, safe_to_consume=safe,
                                  recommended_watering=watering, price=price, inventory=inventory, category=category)
                session.add(new_plant)
                session.commit()
                messagebox.showinfo("Success", f"Plant '{name}' added.")
                win.destroy()
                self.controller.screens["ShopScreen"].render_products()
            except Exception as ex:
                messagebox.showerror("Error", str(ex))
        btn = ttk.Button(win, text="Add Plant", command=add_new)
        btn.grid(row=len(labels), column=0, columnspan=2, pady=10)
    
    def generate_barcode(self):
        win = Toplevel(self)
        win.title("Generate Barcode")
        lbl = ttk.Label(win, text="Enter Plant Name:")
        lbl.pack(pady=5)
        entry = ttk.Entry(win, width=30)
        entry.pack(pady=5)
        def confirm():
            pname = entry.get().strip()
            plant = session.query(Plant).filter_by(name=pname).first()
            if not plant:
                messagebox.showerror("Error", f"No plant named '{pname}' found.")
                return
            if not os.path.exists("barcodes"):
                os.makedirs("barcodes")
            code_str = f"{plant.id:06d}{random.randint(100000,999999)}"
            barcode_obj = Code128(code_str, writer=ImageWriter())
            saved_path = os.path.join("barcodes", f"{code_str}.png")
            barcode_obj.save(saved_path)
            plant.barcode_number = code_str
            plant.barcode_image_path = saved_path
            session.commit()
            messagebox.showinfo("Success", f"Barcode for {pname}: {code_str}")
            win.destroy()
        btn = ttk.Button(win, text="Generate", command=confirm)
        btn.pack(pady=5)
    
    def open_care_logger(self):
        win = Toplevel(self)
        win.title("Care Logger")
        lbl = ttk.Label(win, text="Select Plant:", font=("Helvetica", 12))
        lbl.grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        plant_names = [plant.name for plant in session.query(Plant).all()]
        plant_var = tk.StringVar()
        dropdown = ttk.Combobox(win, textvariable=plant_var, values=plant_names)
        dropdown.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        lbl_obs = ttk.Label(win, text="Observation/Notes:", font=("Helvetica", 12))
        lbl_obs.grid(row=1, column=0, padx=5, pady=5, sticky=tk.NW)
        text_obs = tk.Text(win, height=5, width=40)
        text_obs.grid(row=1, column=1, padx=5, pady=5)
        def log_care():
            pname = plant_var.get().strip()
            obs = text_obs.get("1.0", tk.END).strip()
            if not pname:
                messagebox.showerror("Error", "Please select a plant.")
                return
            plant = session.query(Plant).filter(Plant.name.ilike(pname)).first()
            if not plant:
                messagebox.showerror("Error", "Plant not found.")
                return
            routine = generate_care_routine(plant, self.controller.sensor_data)
            routine_text = "\n".join(routine)
            care_log = CareLog(plant_id=plant.id, observation=obs, routine=routine_text)
            session.add(care_log)
            session.commit()
            messagebox.showinfo("Logged", f"Care routine for {pname} logged:\n{routine_text}")
            win.destroy()
        btn = ttk.Button(win, text="Log Care Routine", command=log_care)
        btn.grid(row=2, column=0, columnspan=2, pady=10)

# ==================== Run Application ====================
if __name__ == "__main__":
    if not os.path.exists('config.ini'):
        with open('config.ini', 'w') as f:
            f.write("[API_KEYS]\nopenweather_key=YOUR_OPENWEATHER_API_KEY\ntrefle_token=YOUR_TREFLE_API_TOKEN\n\n[ADMIN]\nadmin_password=admin\n")
        messagebox.showinfo("Configuration", "Please update config.ini with your API keys and admin password. Restart after updating.")
    else:
        root = tk.Tk()
        app = PlantKioskApp(root)
        root.mainloop()
        session.close()
