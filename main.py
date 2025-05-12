import re
import spacy
from fastapi import FastAPI, HTTPException, Request, Body, Query
from pydantic import BaseModel
from pymongo import MongoClient, errors
from typing import Optional
from bson import ObjectId
from urllib.parse import quote
from datetime import datetime, timedelta
from geopy.distance import geodesic

# MongoDB connection
client = MongoClient("mongodb+srv://reyjohnandraje2002:ReyJohn17@concentrix.txv3t.mongodb.net/?retryWrites=true&w=majority&appName=Concentrix")
db = client["Filipinovation"]
doctors_collection = db["doctors"]
users_collection = db["users"]
appointments_collection = db["appointments"]

app = FastAPI()

nlp = spacy.load("en_core_web_sm")

# Convert MongoDB document to JSON-safe dict, excluding '_id' field
def serialize_doctor(doctor):
    if doctor:
        doctor.pop('_id', None)  # Remove MongoDB internal ID
        return doctor
    return None

def format_date(date_str: str) -> str:
    today = datetime.now().date()
    current_year = today.year
    date_str = date_str.strip().lower()

    # Handle "tomorrow"
    if date_str == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # Handle weekday names and "next <weekday>"
    weekdays = list(calendar.day_name)
    if "next" in date_str:
        parts = date_str.split()
        if len(parts) == 2 and parts[1].capitalize() in weekdays:
            target_day = weekdays.index(parts[1].capitalize())
            days_ahead = (target_day - today.weekday() + 7) % 7
            days_ahead = days_ahead + 7 if days_ahead == 0 else days_ahead
            target_date = today + timedelta(days=days_ahead)
            return target_date.strftime("%Y-%m-%d")
    elif date_str.capitalize() in weekdays:
        target_day = weekdays.index(date_str.capitalize())
        days_ahead = (target_day - today.weekday() + 7) % 7
        days_ahead = 7 if days_ahead == 0 else days_ahead
        target_date = today + timedelta(days=days_ahead)
        return target_date.strftime("%Y-%m-%d")

    # Handle other formats (add current year)
    formats_with_default_year = [
        ("%d-%m", lambda s: f"{s}-{current_year}"),
        ("%m-%d", lambda s: f"{current_year}-{s}"),
        ("%b %d", lambda s: f"{s}, {current_year}"),
        ("%B %d", lambda s: f"{s}, {current_year}"),
    ]

    for fmt, transformer in formats_with_default_year:
        try:
            transformed = transformer(date_str.title())
            parse_fmt = f"{fmt}, %Y" if ',' in transformed else "%d-%m-%Y" if '-' in fmt and fmt.startswith("%d") else "%Y-%m-%d"
            date_obj = datetime.strptime(transformed, parse_fmt).date()
            if date_obj < today:
                raise HTTPException(status_code=400, detail="The selected date has already passed.")
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise HTTPException(
        status_code=400,
        detail="Invalid date format. Use 'MM-DD', 'DD-MM', 'Month D', weekday names, or 'tomorrow'."
    )

@app.get("/check_user/{user_id}")
async def check_user(user_id: str):
    try:
        user = users_collection.find_one({"user_id": user_id})
        
        if user:
            user.pop('_id', None)
            return {"status": "success", "message": f"User with ID {user_id} found.", "data": user}
        else:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found.")

    except errors.ServerSelectionTimeoutError:
        raise HTTPException(status_code=500, detail="Database connection error. Please try again later.")
    
    except errors.PyMongoError as e:
        raise HTTPException(status_code=500, detail=f"MongoDB error: {str(e)}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


@app.get("/doctor_availability/{doctor_specialization}/{date}")
async def check_doctor_availability(doctor_specialization: str, date: str):
    try:
        doctor_specialization = doctor_specialization.lower()
        formatted_date = format_date(date)

        # Fetch all doctors with this specialization
        doctors = doctors_collection.find({
            "field": {"$regex": doctor_specialization, "$options": "i"}
        })

        available_doctors = []

        for doctor in doctors:
            schedule = doctor.get("schedule", {}).get("May", {}).get(formatted_date)
            if schedule:
                unavailable_slots = [time for time, slot in schedule.items() if slot.get("available") != "yes"]
                if unavailable_slots:
                    message = f"Doctor is available on {formatted_date}, except {', '.join(unavailable_slots)}."
                else:
                    message = f"Doctor is available on {formatted_date}."
                available_doctors.append({
                    "name": doctor.get("name"),
                    "hospital": doctor.get("hospital"),
                    "location": doctor.get("location"),
                    "message": message
                })

        if not available_doctors:
            return {
                "status": "success",
                "message": f"No available doctors found for {doctor_specialization} on {formatted_date}.",
                "data": []
            }

        return {
            "status": "success",
            "message": f"Availability for doctors specializing in {doctor_specialization} on {formatted_date}:",
            "data": available_doctors
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


class AppointmentRequest(BaseModel):
    user_id: str
    doctor_specialization: str
    date: str
    time: str

@app.post("/book_appointment")
async def book_appointment(appointment_request: AppointmentRequest):
    try:
        doctor_specialization = appointment_request.doctor_specialization.lower()
        user = users_collection.find_one({"user_id": appointment_request.user_id})
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {appointment_request.user_id} not found.")

        doctor = doctors_collection.find_one({"doctors_field": {"$regex": doctor_specialization, "$options": "i"}})
        if not doctor:
            raise HTTPException(status_code=404, detail=f"Doctor with specialization '{doctor_specialization}' not found.")
        
        formatted_date = format_date(appointment_request.date)
        if doctor.get("date") != formatted_date:
            raise HTTPException(status_code=400, detail=f"Doctor is not available on {formatted_date}.")

        if appointment_request.time not in doctor.get("available_slots", []):
            raise HTTPException(status_code=400, detail=f"Time '{appointment_request.time}' is not available for {doctor_specialization} on {formatted_date}.")
        
        appointment_data = {
            "user_id": appointment_request.user_id,
            "doctor_specialization": doctor_specialization,
            "date": formatted_date,
            "time": appointment_request.time,
        }

        result = appointments_collection.insert_one(appointment_data)

        return {"status": "success", "message": "Appointment successfully booked.", "data": appointment_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.get("/nearest_available_doctor/{user_id}/{doctor_specialization}")
async def get_nearest_available_doctor(user_id: str, doctor_specialization: str):
    try:
        # Ensure user_id and doctor_specialization are strings
        user_id = str(user_id)
        doctor_specialization = str(doctor_specialization).lower()

        # Fetch user data
        user = users_collection.find_one({"user_id": user_id})
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        
        # Ensure user has coordinates (latitude and longitude)
        user_coords = (user.get("latitude"), user.get("longitude"))
        if None in user_coords:
            raise HTTPException(status_code=400, detail="User coordinates are missing.")
        
        # Find doctors in the given specialization (case-insensitive match)
        doctors_cursor = doctors_collection.find({
            "field": {"$regex": doctor_specialization, "$options": "i"},  # Case-insensitive search for field
            "latitude": {"$exists": True},
            "longitude": {"$exists": True},
        })

        nearest_doctor = None
        min_distance = float('inf')

        for doctor in doctors_cursor:
            doc_coords = (doctor["latitude"], doctor["longitude"])
            distance_km = geodesic(user_coords, doc_coords).kilometers

            if distance_km < min_distance:
                min_distance = distance_km
                nearest_doctor = doctor
        
        if not nearest_doctor:
            raise HTTPException(status_code=404, detail="No available doctor found.")

        # Clean the response by removing MongoDB's internal '_id'
        nearest_doctor.pop("_id", None)

        # Return basic doctor information with distance
        return {
            "status": "success",
            "message": f"Nearest available doctor: {nearest_doctor['name']} located at {nearest_doctor['hospital']}, {min_distance:.2f} km away.",
            "distance": f"{min_distance:.2f} km",
            "data": nearest_doctor
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

# Generic error handler
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return {
        "status": "error",
        "message": f"An unexpected error occurred: {str(exc)}"
    }
