import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
import json
import csv
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

config = configparser.ConfigParser()
config.read('config.ini')

OPENWEATHER_KEY = config.get('API_KEYS', 'openweather_key', fallback='your_openweather_api_key') # Using api to pull local weather for creating a watering schedule... will probably switch to ai for this.
TREFLE_TOKEN = config.get('API_KEYS', 'trefle_token', fallback='your_trefle_api_token')

Base = declarative_base()

class Plant(Base): # Base for template 
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
