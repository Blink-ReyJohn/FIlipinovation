import re
from fastapi import FastAPI, HTTPException, Request, Body, Query
from pydantic import BaseModel
from pymongo import MongoClient, errors
from typing import Optional
from bson import ObjectId
from urllib.parse import quote
from datetime import datetime, timedelta

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
    today = datetime.now().date()

    # Handle keyword "tomorrow"
    if date_str.strip().lower() == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # Try different formats
    date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y"]
    for fmt in date_formats:
        try:
            date_obj = datetime.strptime(date_str, fmt).date()
            if date_obj < today:
                raise HTTPException(status_code=400, detail="The selected date has already passed.")
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise HTTPException(
        status_code=400,
        detail="Invalid date format. Use 'YYYY-MM-DD', 'DD-MM-YYYY', 'Month D, YYYY', or 'tomorrow'."
    )

# Regex-based name extraction function
def extract_names(text: str):
    pattern = r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b"
    return re.findall(pattern, text)

class RequestBody(BaseModel):
    ugptResponse: str

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
        doctor = doctors_collection.find_one({"doctors_field": {"$regex": doctor_specialization, "$options": "i"}})
        
        if doctor:
            formatted_date = format_date(date)
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

@app.post("/extract_name_from_response")
async def extract_name_from_response(body: RequestBody):
    try:
        # Get the 'ugptResponse' from the body
        ugptResponse = body.ugptResponse

        # Ensure it's a string
        if not isinstance(ugptResponse, str):
            ugptResponse = str(ugptResponse)

        ugptResponse = ugptResponse.strip()

        if not ugptResponse:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "The 'ugptResponse' parameter cannot be empty or whitespace.",
                    "content": ugptResponse
                }
            )

        # Extract names using regex
        names = extract_names(ugptResponse)
        extracted_name = names[0] if names else None

        if not extracted_name:
            return {
                "status": "warning",
                "message": "No names were found in the response.",
                "data": {
                    "String": ugptResponse,
                    "Doctor": None
                },
                "content": ugptResponse
            }

        return {
            "status": "success",
            "message": f"Extracted name: {extracted_name}",
            "data": {
                "String": ugptResponse,
                "Doctor": extracted_name
            }
        }

    except HTTPException as he:
        raise he  # Already structured
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"Error extracting names: {str(e)}",
                "content": ugptResponse
            }
        )

# Generic error handler
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return {
        "status": "error",
        "message": f"An unexpected error occurred: {str(exc)}"
    }
