from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from pymongo import MongoClient, errors
from typing import List
from datetime import datetime
from bson import ObjectId

# MongoDB connection
client = MongoClient("mongodb+srv://reyjohnandraje2002:ReyJohn17@concentrix.txv3t.mongodb.net/?retryWrites=true&w=majority&appName=Concentrix")
db = client["Filipinovation"]
users_collection = db["users"]
appointments_collection = db["appointments"]
doctors_collection = db["doctors"]

app = FastAPI()

# Pydantic models for user input and responses
class UserRequest(BaseModel):
    user_id: str

class AppointmentRequest(BaseModel):
    doctor_field: str
    appointment_date: str  # This will accept any string format
    time_slot: str
    user_id: str

class AvailabilityResponse(BaseModel):
    doctor_name: str
    available_slots: List[str]

# Helper function to convert string date to "YYYY-MM-DD" format
def format_date(date_str: str) -> str:
    """
    Convert various date formats to the standard "YYYY-MM-DD".
    """
    try:
        # Try parsing the date string to "YYYY-MM-DD" format
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")  # Handle "2025-05-01"
    except ValueError:
        try:
            # If the first format fails, try another common format, e.g., "01-05-2025"
            date_obj = datetime.strptime(date_str, "%d-%m-%Y")
        except ValueError:
            try:
                # If the second format fails, try the format "May 7, 2025"
                date_obj = datetime.strptime(date_str, "%b %d, %Y")
            except ValueError:
                # If all formats fail, raise an error
                raise HTTPException(status_code=400, detail="Invalid date format. Please use 'YYYY-MM-DD', 'DD-MM-YYYY', or 'Month D, YYYY'.")
    
    return date_obj.strftime("%Y-%m-%d")


# Helper function to convert the time format to "HH:mm"
def format_time(time_str: str) -> str:
    """
    Convert various time formats to the standard "HH:mm" format.
    """
    try:
        # Try parsing the time string to "HH:mm" format
        time_obj = datetime.strptime(time_str, "%H:%M")  # Handle "08:00"
    except ValueError:
        try:
            # If the first format fails, try another format, e.g., "8:00 AM"
            time_obj = datetime.strptime(time_str, "%I:%M %p")
        except ValueError:
            # If both formats fail, raise an error
            raise HTTPException(status_code=400, detail="Invalid time format. Please use 'HH:mm' or 'h:mm AM/PM'.")
    
    return time_obj.strftime("%H:%M")

# Convert MongoDB document to JSON-safe dict, excluding '_id' field
def serialize_user(user):
    if user:
        user.pop('_id', None)  # Remove MongoDB internal ID
        return user
    return None

# Check if user exists
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
            serialized_user = serialize_user(user)
            # Log the user data for debugging
            print(f"User found: {serialized_user}")
            return {
                "status": "success",
                "message": f"User with ID {user_id} found.",
                "data": serialized_user  # Return the serialized user data
            }
        else:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found.")

    except errors.ServerSelectionTimeoutError:
        raise HTTPException(status_code=500, detail="Database connection error. Please try again later.")
    
    except errors.PyMongoError as e:
        raise HTTPException(status_code=500, detail=f"MongoDB error: {str(e)}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.get("/get_availability/{doctor_field}/{appointment_date}")
async def get_availability(doctor_field: str, appointment_date: str):
    """
    Fetch available time slots for a doctor on a specific date.
    """
    try:
        # Format the user-provided date to "YYYY-MM-DD"
        formatted_date = format_date(appointment_date)

        # Fetch the doctor availability by field and formatted date
        doctor = doctors_collection.find_one({"doctor_field": doctor_field, "date": formatted_date})

        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor or date not found.")

        available_slots = doctor.get('available_slots', [])
        if not available_slots:
            raise HTTPException(status_code=404, detail="No available slots on this date.")

        # Return the list of available slots
        return AvailabilityResponse(
            doctor_name=doctor['doctor_name'],
            available_slots=available_slots
        )
    
    except errors.ServerSelectionTimeoutError:
        raise HTTPException(status_code=500, detail="Database connection error. Please try again later.")
    
    except errors.PyMongoError as e:
        raise HTTPException(status_code=500, detail=f"MongoDB error: {str(e)}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.post("/book_appointment/")
async def book_appointment(appointment: AppointmentRequest):
    """
    Book an appointment based on the user selected time slot.
    """
    try:
        # Format the user-provided date and time to the correct format
        formatted_date = format_date(appointment.appointment_date)
        formatted_time = format_time(appointment.time_slot)

        # Fetch the doctor and availability
        doctor = doctors_collection.find_one({"doctor_field": appointment.doctor_field, "date": formatted_date})

        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor or date not found.")

        # Check if the selected time is available
        if formatted_time not in doctor['available_slots']:
            raise HTTPException(status_code=400, detail=f"Selected time {formatted_time} is not available.")

        # Save the appointment
        appointment_data = {
            "doctor_name": doctor['doctor_name'],
            "doctor_field": doctor['doctor_field'],
            "appointment_date": formatted_date,
            "time_slot": formatted_time,
            "user_id": appointment.user_id
        }

        # Insert appointment into the appointments collection
        result = appointments_collection.insert_one(appointment_data)

        # Remove the booked time slot from the available slots
        doctors_collection.update_one(
            {"_id": doctor['_id']},
            {"$pull": {"available_slots": formatted_time}}
        )

        return {"status": "success", "message": "Appointment successfully booked!"}
    
    except errors.ServerSelectionTimeoutError:
        raise HTTPException(status_code=500, detail="Database connection error. Please try again later.")
    
    except errors.PyMongoError as e:
        raise HTTPException(status_code=500, detail=f"MongoDB error: {str(e)}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

# Error handling for uncaught exceptions
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return {
        "status": "error",
        "message": f"An unexpected error occurred: {str(exc)}"
    }
