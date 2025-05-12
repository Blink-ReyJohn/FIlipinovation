import re
import spacy
import calendar
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

from datetime import datetime, timedelta
import calendar

# Helper function to convert string date to "MM-DD" format
def format_date(date_str: str) -> str:
    today = datetime.now().date()

    # Handle keyword "tomorrow"
    if date_str.strip().lower() == "tomorrow":
        return (today + timedelta(days=1)).strftime("%m-%d")

    # Handle month-day format like "May 15"
    try:
        # The strptime format for month-day ("May 15")
        date_obj = datetime.strptime(date_str, "%b %d")
        # Ensure the date is in the current year first
        date_obj = date_obj.replace(year=today.year)
        
        # If the date has already passed this year, move to next year
        if date_obj.date() < today:
            date_obj = date_obj.replace(year=today.year + 1)
        
        return date_obj.strftime("%m-%d")
    
    except ValueError as e:
        print(f"Error parsing date: {date_str}, {e}")
        pass  # Continue to other formats

    # Try different formats
    date_formats = ["%m-%d", "%d-%m", "%b %d", "%A", "tomorrow"]
    for fmt in date_formats:
        try:
            date_obj = datetime.strptime(date_str, fmt).date()
            if date_obj < today:
                raise HTTPException(status_code=400, detail="The selected date has already passed.")
            return date_obj.strftime("%m-%d")
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


@app.get("/doctor_availability_by_name/{doctor_name}/{date}")
async def check_doctor_availability_by_name(doctor_name: str, date: str):
    try:
        # Format the date
        formatted_date = format_date(date)

        # Fetch doctor based on their name (case-insensitive)
        doctor = doctors_collection.find_one({"name": {"$regex": doctor_name, "$options": "i"}})

        if not doctor:
            raise HTTPException(status_code=404, detail=f"Doctor with name '{doctor_name}' not found.")
        
        # Fetch the doctor's schedule for the specific date
        schedule = doctor.get("schedule", {}).get("May", {}).get(formatted_date)
        
        # Check if schedule exists for that day
        if not schedule:
            raise HTTPException(status_code=400, detail=f"Doctor '{doctor_name}' does not have a schedule for {formatted_date}.")

        # Identify unavailable timeslots
        unavailable_slots = [time for time, slot in schedule.items() if slot.get("available") != "yes"]
        
        if unavailable_slots:
            message = f"Doctor '{doctor_name}' is available on {formatted_date}, except {', '.join(unavailable_slots)}."
        else:
            message = f"Doctor '{doctor_name}' is available on {formatted_date}."

        return {
            "status": "success",
            "message": f"Availability for {doctor_name} on {formatted_date}:",
            "data": {
                "name": doctor.get("name"),
                "hospital": doctor.get("hospital"),
                "location": doctor.get("location"),
                "message": message
            }
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
