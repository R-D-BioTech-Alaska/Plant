#!/usr/bin/env python3
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import json, csv, threading, logging, os, time, random
from datetime import datetime, timedelta
import configparser
import requests

# SQLAlchemy imports
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# TensorFlow and related imports for PlantAI
import numpy as np
from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2, preprocess_input, decode_predictions
from tensorflow.keras.preprocessing import image

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load Configuration from config.ini
config = configparser.ConfigParser()
config.read('config.ini')
OPENWEATHER_KEY = config.get('API_KEYS', 'openweather_key', fallback='your_openweather_api_key')
TREFLE_TOKEN = config.get('API_KEYS', 'trefle_token', fallback='your_trefle_api_token')

# Database Setup with SQLAlchemy
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

# New table to log care routines
class CareLog(Base):
    __tablename__ = 'care_logs'
    id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey('plants.id'))
    timestamp = Column(DateTime, default=datetime.now)
    observation = Column(Text)
    routine = Column(Text)
    plant = relationship("Plant")

# Initialize Database
engine = create_engine('sqlite:///advanced_plant_manager.db', echo=False, connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# Manager for API interactions (e.g., weather)
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

# AI Manager for Plant Identification and Disease Detection using TensorFlow
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
            # Retrieve top 5 predictions for better filtering
            predictions = self.decode_predictions(preds, top=5)[0]
            # Define allowed keywords for plant-related classes (add common flower names)
            allowed_keywords = ['plant', 'tree', 'flower', 'daisy', 'tulip', 'rose', 'sunflower', 'lily', 'orchid', 'poppy', 'dandelion']
            plant_preds = [pred for pred in predictions if any(keyword in pred[1].lower() for keyword in allowed_keywords)]
            if plant_preds:
                top_pred = plant_preds[0]
            else:
                # Fallback to the top prediction if none match the allowed keywords
                top_pred = predictions[0]
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
            # Simple heuristic: if the image is unusually dark, flag potential disease
            if avg_intensity < 50:
                result = {"disease": "Possible disease detected", "confidence": 0.8}
            else:
                result = {"disease": "No disease detected", "confidence": 0.95}
            return result
        except Exception as e:
            logging.error(f"Error in detect_disease: {e}")
            return {"disease": "Unknown", "confidence": 0.0}

# IoT Manager to simulate sensor readings (soil moisture, temperature, humidity)
class IoTManager:
    def __init__(self):
        pass

    def get_sensor_data(self):
        # Simulate sensor data
        return {
            "soil_moisture": random.randint(10, 60),  # percentage
            "temperature": random.randint(15, 30),      # Celsius
            "humidity": random.randint(40, 80)          # percentage
        }

# Function to generate care routines based on plant data and sensor readings
def generate_care_routine(plant, sensor_data):
    routine = []
    if sensor_data["soil_moisture"] < 30:
        routine.append("Water the plant. Soil moisture is low.")
    else:
        routine.append("No watering needed today. Soil moisture is adequate.")
    if sensor_data["temperature"] > 28:
        routine.append("Provide shade or move indoors to prevent overheating.")
    elif sensor_data["temperature"] < 18:
        routine.append("Consider moving the plant to a warmer area.")
    else:
        routine.append("Temperature is optimal.")
    routine.append("Review nutrient levels and consider fertilizing if due.")
    return routine

# Main Application Class
class AdvancedPlantManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced AI-Integrated Plant Manager")
        self.root.geometry("1400x900")
        self.style = ttk.Style("flatly")  # Using ttkbootstrap theme
        self.root.configure(bg=self.style.colors.bg)
        
        # Initialize managers
        self.api = APIManager(OPENWEATHER_KEY, TREFLE_TOKEN)
        self.plant_ai = PlantAI()
        self.iot_manager = IoTManager()
        self.sensor_data = {}
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=BOTH, expand=YES)
        
        self.setup_profile_tab()
        self.setup_schedule_tab()
        self.setup_add_plant_tab()
        self.setup_care_logger_tab()
        self.setup_plant_ai_tab()
        
        self.setup_menu()
        
        # Logger text area for internal logs
        self.logger_text = tk.Text(self.root, height=5, bg="white")
        self.logger_text.pack(fill=X, side=BOTTOM)
        
        # Start sensor polling in a separate thread
        self.poll_sensor_data_thread = threading.Thread(target=self.poll_sensor_data, daemon=True)
        self.poll_sensor_data_thread.start()

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Import Plants", command=self.import_plants_from_file)
        file_menu.add_command(label="Export Data", command=self.export_data_to_file)
        file_menu.add_command(label="Sync Cloud", command=self.sync_with_cloud)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)
        
    def setup_profile_tab(self):
        self.profile_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.profile_frame, text="Profile & Schedule")
        # Layout elements
        lbl = ttk.Label(self.profile_frame, text="Enter Plant Name:")
        lbl.grid(row=0, column=0, padx=5, pady=5, sticky=W)
        self.entry_profile = ttk.Entry(self.profile_frame, width=30)
        self.entry_profile.grid(row=0, column=1, padx=5, pady=5, sticky=W)
        btn_search = ttk.Button(self.profile_frame, text="Search", command=self.search_profile)
        btn_search.grid(row=0, column=2, padx=5, pady=5)
        # Weather lookup
        lbl_zip = ttk.Label(self.profile_frame, text="Postal Code:")
        lbl_zip.grid(row=0, column=3, padx=5, pady=5, sticky=W)
        self.entry_zip = ttk.Entry(self.profile_frame, width=10)
        self.entry_zip.grid(row=0, column=4, padx=5, pady=5, sticky=W)
        # Display profile info
        self.text_profile = tk.Text(self.profile_frame, height=15, bg="white", wrap=WORD)
        self.text_profile.grid(row=1, column=0, columnspan=5, padx=5, pady=5, sticky=NSEW)
        # Image display
        self.image_label = ttk.Label(self.profile_frame, text="No image available")
        self.image_label.grid(row=1, column=5, padx=5, pady=5, sticky=NSEW)
        self.profile_frame.rowconfigure(1, weight=1)
        self.profile_frame.columnconfigure(1, weight=1)
        
    def setup_schedule_tab(self):
        self.schedule_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.schedule_frame, text="Schedule Maker")
        # Watering schedule
        lbl_water = ttk.Label(self.schedule_frame, text="Plant Name:")
        lbl_water.grid(row=0, column=0, padx=5, pady=5, sticky=W)
        self.entry_water_plant = ttk.Entry(self.schedule_frame, width=30)
        self.entry_water_plant.grid(row=0, column=1, padx=5, pady=5, sticky=W)
        lbl_time = ttk.Label(self.schedule_frame, text="Next Water (YYYY-MM-DD HH:MM):")
        lbl_time.grid(row=1, column=0, padx=5, pady=5, sticky=W)
        self.entry_water_time = ttk.Entry(self.schedule_frame, width=30)
        self.entry_water_time.grid(row=1, column=1, padx=5, pady=5, sticky=W)
        btn_add_water = ttk.Button(self.schedule_frame, text="Add Watering Schedule", command=self.add_watering_schedule)
        btn_add_water.grid(row=2, column=0, columnspan=2, padx=5, pady=5)
        # Nutrient schedule
        lbl_nutrient = ttk.Label(self.schedule_frame, text="Plant Name:")
        lbl_nutrient.grid(row=3, column=0, padx=5, pady=5, sticky=W)
        self.entry_nutrient_plant = ttk.Entry(self.schedule_frame, width=30)
        self.entry_nutrient_plant.grid(row=3, column=1, padx=5, pady=5, sticky=W)
        lbl_feed = ttk.Label(self.schedule_frame, text="Next Feed (YYYY-MM-DD HH:MM):")
        lbl_feed.grid(row=4, column=0, padx=5, pady=5, sticky=W)
        self.entry_feed_time = ttk.Entry(self.schedule_frame, width=30)
        self.entry_feed_time.grid(row=4, column=1, padx=5, pady=5, sticky=W)
        btn_add_feed = ttk.Button(self.schedule_frame, text="Add Nutrient Schedule", command=self.add_nutrient_schedule)
        btn_add_feed.grid(row=5, column=0, columnspan=2, padx=5, pady=5)
        # Display schedules
        self.text_schedules = tk.Text(self.schedule_frame, height=10, bg="white", wrap=WORD)
        self.text_schedules.grid(row=6, column=0, columnspan=2, padx=5, pady=5, sticky=NSEW)
        self.schedule_frame.rowconfigure(6, weight=1)
        self.schedule_frame.columnconfigure(1, weight=1)
        
    def setup_add_plant_tab(self):
        self.add_plant_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.add_plant_frame, text="Add New Plant")
        lbl_name = ttk.Label(self.add_plant_frame, text="Plant Name:")
        lbl_name.grid(row=0, column=0, padx=5, pady=5, sticky=W)
        self.entry_new_plant = ttk.Entry(self.add_plant_frame, width=30)
        self.entry_new_plant.grid(row=0, column=1, padx=5, pady=5, sticky=W)
        lbl_profile = ttk.Label(self.add_plant_frame, text="Profile:")
        lbl_profile.grid(row=1, column=0, padx=5, pady=5, sticky=W)
        self.text_new_profile = tk.Text(self.add_plant_frame, height=5, bg="white", wrap=WORD)
        self.text_new_profile.grid(row=1, column=1, padx=5, pady=5, sticky=NSEW)
        lbl_species = ttk.Label(self.add_plant_frame, text="Species:")
        lbl_species.grid(row=2, column=0, padx=5, pady=5, sticky=W)
        self.entry_species = ttk.Entry(self.add_plant_frame, width=30)
        self.entry_species.grid(row=2, column=1, padx=5, pady=5, sticky=W)
        lbl_class = ttk.Label(self.add_plant_frame, text="Class:")
        lbl_class.grid(row=3, column=0, padx=5, pady=5, sticky=W)
        self.entry_class = ttk.Entry(self.add_plant_frame, width=30)
        self.entry_class.grid(row=3, column=1, padx=5, pady=5, sticky=W)
        lbl_genus = ttk.Label(self.add_plant_frame, text="Genus:")
        lbl_genus.grid(row=4, column=0, padx=5, pady=5, sticky=W)
        self.entry_genus = ttk.Entry(self.add_plant_frame, width=30)
        self.entry_genus.grid(row=4, column=1, padx=5, pady=5, sticky=W)
        lbl_nutrition = ttk.Label(self.add_plant_frame, text="Recommended Nutrition:")
        lbl_nutrition.grid(row=5, column=0, padx=5, pady=5, sticky=W)
        self.text_nutrition = tk.Text(self.add_plant_frame, height=3, bg="white", wrap=WORD)
        self.text_nutrition.grid(row=5, column=1, padx=5, pady=5, sticky=NSEW)
        lbl_safe = ttk.Label(self.add_plant_frame, text="Safe to Consume:")
        lbl_safe.grid(row=6, column=0, padx=5, pady=5, sticky=W)
        self.safe_var = tk.BooleanVar()
        chk_safe = ttk.Checkbutton(self.add_plant_frame, variable=self.safe_var)
        chk_safe.grid(row=6, column=1, padx=5, pady=5, sticky=W)
        lbl_watering = ttk.Label(self.add_plant_frame, text="Recommended Watering:")
        lbl_watering.grid(row=7, column=0, padx=5, pady=5, sticky=W)
        self.text_watering = tk.Text(self.add_plant_frame, height=3, bg="white", wrap=WORD)
        self.text_watering.grid(row=7, column=1, padx=5, pady=5, sticky=NSEW)
        btn_add_plant = ttk.Button(self.add_plant_frame, text="Add Plant", command=self.add_new_plant)
        btn_add_plant.grid(row=8, column=0, columnspan=2, padx=5, pady=5)
        self.add_plant_frame.rowconfigure(1, weight=1)
        self.add_plant_frame.columnconfigure(1, weight=1)
        
    def setup_care_logger_tab(self):
        self.care_logger_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.care_logger_frame, text="Care Logger")
        lbl_select = ttk.Label(self.care_logger_frame, text="Select Plant:")
        lbl_select.grid(row=0, column=0, padx=5, pady=5, sticky=W)
        # Dropdown with plant names from database
        self.plant_names = [plant.name for plant in session.query(Plant).all()]
        self.selected_plant = tk.StringVar()
        self.dropdown_plants = ttk.Combobox(self.care_logger_frame, textvariable=self.selected_plant, values=self.plant_names)
        self.dropdown_plants.grid(row=0, column=1, padx=5, pady=5, sticky=W)
        lbl_observation = ttk.Label(self.care_logger_frame, text="Observation/Notes:")
        lbl_observation.grid(row=1, column=0, padx=5, pady=5, sticky=NW)
        self.text_observation = tk.Text(self.care_logger_frame, height=5, bg="white", wrap=WORD)
        self.text_observation.grid(row=1, column=1, padx=5, pady=5, sticky=NSEW)
        btn_generate = ttk.Button(self.care_logger_frame, text="Generate Care Routine", command=self.generate_care_routine_for_plant)
        btn_generate.grid(row=2, column=0, columnspan=2, padx=5, pady=5)
        lbl_routine = ttk.Label(self.care_logger_frame, text="Suggested Routine:")
        lbl_routine.grid(row=3, column=0, padx=5, pady=5, sticky=NW)
        self.text_routine = tk.Text(self.care_logger_frame, height=7, bg="white", wrap=WORD)
        self.text_routine.grid(row=3, column=1, padx=5, pady=5, sticky=NSEW)
        self.care_logger_frame.rowconfigure(3, weight=1)
        self.care_logger_frame.columnconfigure(1, weight=1)
        
    def setup_plant_ai_tab(self):
        self.plant_ai_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.plant_ai_frame, text="Plant AI")
        lbl_upload = ttk.Label(self.plant_ai_frame, text="Upload Plant Image:")
        lbl_upload.grid(row=0, column=0, padx=5, pady=5, sticky=W)
        btn_upload = ttk.Button(self.plant_ai_frame, text="Browse", command=self.browse_image)
        btn_upload.grid(row=0, column=1, padx=5, pady=5, sticky=W)
        btn_identify = ttk.Button(self.plant_ai_frame, text="Identify Plant", command=self.run_plant_identification)
        btn_identify.grid(row=1, column=0, padx=5, pady=5, sticky=W)
        btn_disease = ttk.Button(self.plant_ai_frame, text="Detect Disease", command=self.run_disease_detection)
        btn_disease.grid(row=1, column=1, padx=5, pady=5, sticky=W)
        self.text_ai_result = tk.Text(self.plant_ai_frame, height=10, bg="white", wrap=WORD)
        self.text_ai_result.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky=NSEW)
        self.plant_ai_frame.rowconfigure(2, weight=1)
        self.plant_ai_frame.columnconfigure(1, weight=1)
        self.ai_image_path = None

    # Function to poll sensor data periodically
    def poll_sensor_data(self):
        while True:
            self.sensor_data = self.iot_manager.get_sensor_data()
            sensor_log = f"Sensor Data - Soil: {self.sensor_data['soil_moisture']}%, Temp: {self.sensor_data['temperature']}°C, Humidity: {self.sensor_data['humidity']}%\n"
            self.append_log(sensor_log)
            time.sleep(10)  # Poll every 10 seconds

    def append_log(self, message):
        self.logger_text.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}")
        self.logger_text.see(tk.END)

    def search_profile(self):
        plant_name = self.entry_profile.get().strip()
        if not plant_name:
            messagebox.showerror("Error", "Please enter a plant name.")
            return
        plant = session.query(Plant).filter(Plant.name.ilike(plant_name)).first()
        if plant:
            profile_info = f"Name: {plant.name}\nProfile: {plant.profile}\nSpecies: {plant.species}\nClass: {plant.plant_class}\nGenus: {plant.genus}\n"
            self.text_profile.delete(1.0, tk.END)
            self.text_profile.insert(tk.END, profile_info)
            if plant.images:
                img_path = plant.images[0].image_path
                if os.path.exists(img_path):
                    pil_image = Image.open(img_path)
                    pil_image = pil_image.resize((300,300))
                    self.photo_image = ImageTk.PhotoImage(pil_image)
                    self.image_label.config(image=self.photo_image)
                else:
                    self.image_label.config(text="Image not found")
            else:
                self.image_label.config(text="No image available")
        else:
            self.text_profile.delete(1.0, tk.END)
            self.text_profile.insert(tk.END, "Plant not found in database.")

    def add_watering_schedule(self):
        plant_name = self.entry_water_plant.get().strip()
        time_str = self.entry_water_time.get().strip()
        if not plant_name or not time_str:
            messagebox.showerror("Error", "Please enter plant name and time.")
            return
        try:
            next_water = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        except ValueError:
            messagebox.showerror("Error", "Invalid date/time format.")
            return
        plant = session.query(Plant).filter(Plant.name.ilike(plant_name)).first()
        if plant:
            schedule = WateringSchedule(plant_id=plant.id, next_water=next_water)
            session.add(schedule)
            session.commit()
            messagebox.showinfo("Success", "Watering schedule added.")
            self.refresh_schedules()
        else:
            messagebox.showerror("Error", "Plant not found.")

    def add_nutrient_schedule(self):
        plant_name = self.entry_nutrient_plant.get().strip()
        time_str = self.entry_feed_time.get().strip()
        if not plant_name or not time_str:
            messagebox.showerror("Error", "Please enter plant name and time.")
            return
        try:
            next_feed = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        except ValueError:
            messagebox.showerror("Error", "Invalid date/time format.")
            return
        plant = session.query(Plant).filter(Plant.name.ilike(plant_name)).first()
        if plant:
            schedule = NutrientSchedule(plant_id=plant.id, next_feed=next_feed, nutrient_info="Standard nutrients")
            session.add(schedule)
            session.commit()
            messagebox.showinfo("Success", "Nutrient schedule added.")
            self.refresh_schedules()
        else:
            messagebox.showerror("Error", "Plant not found.")

    def refresh_schedules(self):
        schedules_text = ""
        watering = session.query(WateringSchedule).all()
        nutrient = session.query(NutrientSchedule).all()
        schedules_text += "Watering Schedules:\n"
        for w in watering:
            plant = session.query(Plant).filter_by(id=w.plant_id).first()
            schedules_text += f"{plant.name} - Next Water: {w.next_water}\n"
        schedules_text += "\nNutrient Schedules:\n"
        for n in nutrient:
            plant = session.query(Plant).filter_by(id=n.plant_id).first()
            schedules_text += f"{plant.name} - Next Feed: {n.next_feed}\n"
        self.text_schedules.delete(1.0, tk.END)
        self.text_schedules.insert(tk.END, schedules_text)

    def import_plants_from_file(self):
        file_path = filedialog.askopenfilename(title="Select Plant Data File", filetypes=[("JSON files", "*.json"), ("CSV files", "*.csv")])
        if not file_path:
            return
        try:
            if file_path.endswith('.json'):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                for plant_data in data:
                    if not session.query(Plant).filter_by(name=plant_data.get("name")).first():
                        new_plant = Plant(
                            name=plant_data.get("name"),
                            profile=plant_data.get("profile"),
                            species=plant_data.get("species"),
                            plant_class=plant_data.get("plant_class"),
                            genus=plant_data.get("genus"),
                            recommended_nutrition=plant_data.get("recommended_nutrition"),
                            safe_to_consume=plant_data.get("safe_to_consume"),
                            recommended_watering=plant_data.get("recommended_watering")
                        )
                        session.add(new_plant)
                session.commit()
                messagebox.showinfo("Import", "Plants imported successfully.")
            elif file_path.endswith('.csv'):
                with open(file_path, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if not session.query(Plant).filter_by(name=row.get("name")).first():
                            new_plant = Plant(
                                name=row.get("name"),
                                profile=row.get("profile"),
                                species=row.get("species"),
                                plant_class=row.get("plant_class"),
                                genus=row.get("genus"),
                                recommended_nutrition=row.get("recommended_nutrition"),
                                safe_to_consume=(row.get("safe_to_consume")=="True"),
                                recommended_watering=row.get("recommended_watering")
                            )
                            session.add(new_plant)
                session.commit()
                messagebox.showinfo("Import", "Plants imported successfully.")
            self.plant_names = [plant.name for plant in session.query(Plant).all()]
            self.dropdown_plants['values'] = self.plant_names
        except Exception as e:
            logging.error(f"Import error: {e}")
            messagebox.showerror("Error", f"Failed to import plants: {e}")

    def export_data_to_file(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".json", title="Save Data File", filetypes=[("JSON files", "*.json")])
        if not file_path:
            return
        try:
            plants = session.query(Plant).all()
            plant_list = []
            for plant in plants:
                plant_dict = {
                    "id": plant.id,
                    "name": plant.name,
                    "profile": plant.profile,
                    "species": plant.species,
                    "plant_class": plant.plant_class,
                    "genus": plant.genus,
                    "recommended_nutrition": plant.recommended_nutrition,
                    "safe_to_consume": plant.safe_to_consume,
                    "recommended_watering": plant.recommended_watering,
                    "knowledge": {
                        "scientific_name": plant.knowledge.scientific_name if plant.knowledge else "",
                        "common_name": plant.knowledge.common_name if plant.knowledge else "",
                        "water_requirements": plant.knowledge.water_requirements if plant.knowledge else "",
                        "sunlight_requirements": plant.knowledge.sunlight_requirements if plant.knowledge else "",
                        "soil_type": plant.knowledge.soil_type if plant.knowledge else "",
                        "nutrient_recommendations_detailed": plant.knowledge.nutrient_recommendations_detailed if plant.knowledge else "",
                        "growth_cycle_info": plant.knowledge.growth_cycle_info if plant.knowledge else "",
                        "pest_control_info": plant.knowledge.pest_control_info if plant.knowledge else "",
                        "detailed_profile": plant.knowledge.detailed_profile if plant.knowledge else ""
                    },
                    "images": [image.image_path for image in plant.images]
                }
                plant_list.append(plant_dict)
            with open(file_path, 'w') as f:
                json.dump(plant_list, f, indent=4)
            messagebox.showinfo("Export", "Data exported successfully.")
        except Exception as e:
            logging.error(f"Export error: {e}")
            messagebox.showerror("Error", f"Failed to export data: {e}")

    def sync_with_cloud(self):
        messagebox.showinfo("Cloud Sync", "Data synchronized with cloud successfully (stub).")

    def add_new_plant(self):
        name = self.entry_new_plant.get().strip()
        profile = self.text_new_profile.get(1.0, tk.END).strip()
        species = self.entry_species.get().strip()
        plant_class = self.entry_class.get().strip()
        genus = self.entry_genus.get().strip()
        recommended_nutrition = self.text_nutrition.get(1.0, tk.END).strip()
        safe = self.safe_var.get()
        recommended_watering = self.text_watering.get(1.0, tk.END).strip()
        if not name or not profile:
            messagebox.showerror("Error", "Please enter both plant name and profile.")
            return
        if session.query(Plant).filter_by(name=name).first():
            messagebox.showerror("Error", "Plant already exists in the database.")
            return
        new_plant = Plant(
            name=name,
            profile=profile,
            species=species,
            plant_class=plant_class,
            genus=genus,
            recommended_nutrition=recommended_nutrition,
            safe_to_consume=safe,
            recommended_watering=recommended_watering
        )
        session.add(new_plant)
        session.commit()
        messagebox.showinfo("Success", f"Plant '{name}' added to database.")
        self.entry_new_plant.delete(0, tk.END)
        self.text_new_profile.delete(1.0, tk.END)
        self.entry_species.delete(0, tk.END)
        self.entry_class.delete(0, tk.END)
        self.entry_genus.delete(0, tk.END)
        self.text_nutrition.delete(1.0, tk.END)
        self.safe_var.set(False)
        self.text_watering.delete(1.0, tk.END)
        self.plant_names = [plant.name for plant in session.query(Plant).all()]
        self.dropdown_plants['values'] = self.plant_names

    def generate_care_routine_for_plant(self):
        plant_name = self.selected_plant.get().strip()
        observation = self.text_observation.get(1.0, tk.END).strip()
        if not plant_name:
            messagebox.showerror("Error", "Please select a plant.")
            return
        plant = session.query(Plant).filter(Plant.name.ilike(plant_name)).first()
        if not plant:
            messagebox.showerror("Error", "Selected plant not found in database.")
            return
        routine_list = generate_care_routine(plant, self.sensor_data)
        routine_text = "\n".join(routine_list)
        self.text_routine.delete(1.0, tk.END)
        self.text_routine.insert(tk.END, routine_text)
        care_log = CareLog(plant_id=plant.id, observation=observation, routine=routine_text)
        session.add(care_log)
        session.commit()
        messagebox.showinfo("Care Routine", "Care routine generated and logged.")
        self.append_log(f"Generated care routine for {plant.name}: {routine_text}\n")

    def browse_image(self):
        file_path = filedialog.askopenfilename(title="Select Image", filetypes=[("Image Files", "*.jpg *.png *.jpeg")])
        if file_path:
            self.ai_image_path = file_path
            messagebox.showinfo("Image Selected", f"Selected image: {file_path}")

    def run_plant_identification(self):
        if not self.ai_image_path:
            messagebox.showerror("Error", "Please select an image first.")
            return
        def task():
            result = self.plant_ai.identify_plant(self.ai_image_path)
            result_text = f"Identified Species: {result['species']}\nConfidence: {result['confidence']*100:.1f}%\nInfo: {result['info']}"
            self.text_ai_result.delete(1.0, tk.END)
            self.text_ai_result.insert(tk.END, result_text)
            self.append_log(f"Plant AI Identification: {result_text}\n")
        threading.Thread(target=task, daemon=True).start()

    def run_disease_detection(self):
        if not self.ai_image_path:
            messagebox.showerror("Error", "Please select an image first.")
            return
        def task():
            result = self.plant_ai.detect_disease(self.ai_image_path)
            result_text = f"Disease: {result['disease']}\nConfidence: {result['confidence']*100:.1f}%"
            self.text_ai_result.delete(1.0, tk.END)
            self.text_ai_result.insert(tk.END, result_text)
            self.append_log(f"Plant AI Disease Detection: {result_text}\n")
        threading.Thread(target=task, daemon=True).start()

    def run(self):
        self.root.mainloop()
        session.close()

if __name__ == "__main__":
    if not os.path.exists('config.ini'):
        with open('config.ini', 'w') as f:
            f.write("[API_KEYS]\nopenweather_key=YOUR_OPENWEATHER_API_KEY\ntrefle_token=YOUR_TREFLE_API_TOKEN\n")
        messagebox.showinfo("Configuration", "Please configure your API keys in 'config.ini' and restart the application.")
    else:
        root = tk.Tk()
        app = AdvancedPlantManagerApp(root)
        app.run()
