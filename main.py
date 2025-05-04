from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from pymongo import MongoClient, errors
from typing import Optional
from bson import ObjectId
from datetime import datetime

# MongoDB connection
client = MongoClient("mongodb+srv://reyjohnandraje2002:ReyJohn17@concentrix.txv3t.mongodb.net/?retryWrites=true&w=majority&appName=Concentrix")
db = client["Filipinovation"]
doctors_collection = db["doctors"]
users_collection = db["users"]
appointments_collection = db["appointments"]

app = FastAPI()

# Convert MongoDB document to JSON-safe dict, excluding '_id' field
def serialize_doctor(doctor):
    if doctor:
        doctor.pop('_id', None)  # Remove MongoDB internal ID
        return doctor
    return None

# Helper function to convert string date to "YYYY-MM-DD" format
def format_date(date_str: str) -> str:
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")  # Handle "2025-05-01"
    except ValueError:
        try:
            date_obj = datetime.strptime(date_str, "%d-%m-%Y")  # Handle "01-05-2025"
        except ValueError:
            try:
                date_obj = datetime.strptime(date_str, "%b %d, %Y")  # Handle "May 7, 2025"
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Please use 'YYYY-MM-DD', 'DD-MM-YYYY', or 'Month D, YYYY'.")
    return date_obj.strftime("%Y-%m-%d")


@app.get("/check_user/{user_id}")
async def check_user(user_id: str):
    """
    Fetches a user by ID and returns user information if exists.
    Handles potential errors such as missing user or database issues.
    """
    try:
        # Search for user by user_id in the MongoDB collection
        user = users_collection.find_one({"user_id": user_id})
        
        if user:
            user.pop('_id', None)  # Remove MongoDB internal ID
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
    """
    Fetches the available time slots for a doctor on a specific date.
    """
    try:
        # Normalize doctor specialization input to lowercase
        doctor_specialization = doctor_specialization.lower()

        # Fetch doctor details from the database (case-insensitive comparison)
        doctor = doctors_collection.find_one({"doctors_field": {"$regex": doctor_specialization, "$options": "i"}})
        
        if doctor:
            # Format the date to the correct format
            formatted_date = format_date(date)
            # Check if the doctor is available on that date
            if doctor.get("date") == formatted_date:
                available_slots = doctor.get("available_slots", [])
                return {"status": "success", "message": f"Available slots for {doctor_specialization} on {formatted_date}:", "data": available_slots}
            else:
                return {"status": "success", "message": f"No availability for {doctor_specialization} on {formatted_date}.", "data": []}
        else:
            raise HTTPException(status_code=404, detail=f"Doctor with specialization '{doctor_specialization}' not found.")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


class AppointmentRequest(BaseModel):
    user_id: str
    doctor_specialization: str
    date: str
    time: str

@app.post("/book_appointment")
async def book_appointment(appointment_request: AppointmentRequest):
    """
    Books an appointment for a user with the specified doctor and time.
    """
    try:
        # Normalize doctor specialization input to lowercase
        doctor_specialization = appointment_request.doctor_specialization.lower()

        # Check if the user exists
        user = users_collection.find_one({"user_id": appointment_request.user_id})
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {appointment_request.user_id} not found.")

        # Fetch doctor details (case-insensitive)
        doctor = doctors_collection.find_one({"doctors_field": {"$regex": doctor_specialization, "$options": "i"}})
        if not doctor:
            raise HTTPException(status_code=404, detail=f"Doctor with specialization '{doctor_specialization}' not found.")
        
        # Format date and check if the doctor is available
        formatted_date = format_date(appointment_request.date)
        if doctor.get("date") != formatted_date:
            raise HTTPException(status_code=400, detail=f"Doctor is not available on {formatted_date}.")

        # Check if the requested time is available
        if appointment_request.time not in doctor.get("available_slots", []):
            raise HTTPException(status_code=400, detail=f"Time '{appointment_request.time}' is not available for {doctor_specialization} on {formatted_date}.")
        
        # Create appointment
        appointment_data = {
            "user_id": appointment_request.user_id,
            "doctor_specialization": doctor_specialization,
            "date": formatted_date,
            "time": appointment_request.time,
        }

        # Insert the appointment into the collection
        result = appointments_collection.insert_one(appointment_data)

        # Return the appointment details
        return {"status": "success", "message": "Appointment successfully booked.", "data": appointment_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

# Generic error handler
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return {
        "status": "error",
        "message": f"An unexpected error occurred: {str(exc)}"
    }
