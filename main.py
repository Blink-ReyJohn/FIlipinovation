import re
import spacy
import calendar
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pytz import timezone
from fastapi import FastAPI, HTTPException, Request, Body, Query
from pydantic import BaseModel
from pymongo import MongoClient, errors
from typing import Optional
from bson import ObjectId
from urllib.parse import quote, unquote
from datetime import datetime, timedelta
from geopy.distance import geodesic

# MongoDB connection
client = MongoClient("mongodb+srv://reyjohnandraje2002:ReyJohn17@concentrix.txv3t.mongodb.net/?retryWrites=true&w=majority&appName=Concentrix")
db = client["Filipinovation"]
doctors_collection = db["doctors"]
users_collection = db["users"]
appointments_collection = db["appointments"]
hmo_db = client["hmo_system"]
filipinovation_db = client["Filipinovation"]
users_collection = hmo_db["users"]  # User info here
services_collection = filipinovation_db["services"]  # Service costs here

app = FastAPI()

nlp = spacy.load("en_core_web_sm")

class AppointmentRequest(BaseModel):
    user_id: str  # Assuming user ID is a string
    doctor_specialization: str
    date: str  # Date in string format (you can validate and format it)
    time: str  # Time as a string (e.g., "09:00 AM")

# Convert MongoDB document to JSON-safe dict, excluding '_id' field
def serialize_doctor(doctor):
    if doctor:
        doctor.pop('_id', None)  # Remove MongoDB internal ID
        return doctor
    return None
    
# Helper function to convert string date to "Month D" format (e.g., "May 13")
def format_date(date_str: str) -> str:
    today = datetime.now(timezone('Asia/Manila')).date()  # Use Philippine Time

    # Handle keyword "tomorrow"
    if date_str.strip().lower() == "tomorrow":
        return (today + timedelta(days=1)).strftime("%b %d")  # "May 14" format

    # Handle month-day format like "May 15"
    try:
        # The strptime format for month-day ("May 15")
        date_obj = datetime.strptime(date_str.strip(), "%b %d")
        # Ensure the date is in the current year first
        date_obj = date_obj.replace(year=today.year)
        
        # If the date has already passed this year, move to next year
        if date_obj.date() < today:
            date_obj = date_obj.replace(year=today.year + 1)
        
        return date_obj.strftime("%b %d")  # Return as "May 13"
    
    except ValueError as e:
        print(f"Error parsing date: {date_str}, {e}")
        pass  # Continue to other formats

    # Try different formats
    date_formats = ["%m-%d", "%d-%m", "%b %d", "%A", "tomorrow"]
    for fmt in date_formats:
        try:
            date_obj = datetime.strptime(date_str.strip(), fmt).date()
            if date_obj < today:
                raise HTTPException(status_code=400, detail="The selected date has already passed.")
            return date_obj.strftime("%b %d")  # Return as "May 13"
        except ValueError:
            continue

    raise HTTPException(
        status_code=400,
        detail="Invalid date format. Use 'MM-DD', 'DD-MM', 'Month D', weekday names, or 'tomorrow'."
    )

# Endpoint to check doctor availability by name
@app.get("/doctor_availability_by_name/{doctor_name}/{date}") 
async def check_doctor_availability_by_name(doctor_name: str, date: str):
    try:
        # Decode the doctor name and date (handle spaces and special characters)
        doctor_name = unquote(doctor_name)  # Decode the doctor name
        formatted_date = format_date(date)  # Get the formatted date
        
        # Fetch the doctor by name (case-insensitive match)
        doctor = doctors_collection.find_one({
            "name": {"$regex": doctor_name, "$options": "i"}  # Case-insensitive search
        })

        if not doctor:
            raise HTTPException(status_code=404, detail=f"Doctor '{doctor_name}' not found.")
        
        # Check the availability on the specified date (e.g., May 13)
        schedule = doctor.get("schedule", {}).get("May", {}).get(formatted_date)

        # If there's a schedule, check for available slots
        if schedule:
            unavailable_slots = [time for time, slot in schedule.items() if slot.get("available") != "yes"]
            if unavailable_slots:
                message = f"Dr. {doctor_name} is available on {formatted_date}, except {', '.join(unavailable_slots)}."
            else:
                message = f"Dr. {doctor_name} is available on {formatted_date}."
            
            # Return only the availability message and doctor's name (reduce the data)
            return {
                "status": "success",
                "message": message,
                "doctor": {"name": doctor.get("name"), "message": message}
            }
        else:
            # If no schedule exists for that date, inform the user
            return {
                "status": "success",
                "message": f"Dr. {doctor_name} is not available on {formatted_date}.",
                "doctor": {"name": doctor.get("name"), "message": f"Dr. {doctor_name} is not available on {formatted_date}."}
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

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

@app.post("/book_appointment")
async def book_appointment(appointment_request: AppointmentRequest):
    try:
        doctor_specialization = appointment_request.doctor_specialization.lower()
        user = users_collection.find_one({"user_id": appointment_request.user_id})
        
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {appointment_request.user_id} not found.")
        
        doctor = doctors_collection.find_one({"field": {"$regex": doctor_specialization, "$options": "i"}})
        if not doctor:
            raise HTTPException(status_code=404, detail=f"Doctor with specialization '{doctor_specialization}' not found.")
        
        formatted_date = format_date(appointment_request.date)
        schedule = doctor.get("schedule", {}).get("May", {}).get(formatted_date)

        if not schedule:
            raise HTTPException(status_code=400, detail=f"Doctor is not available on {formatted_date}.")

        # Check availability for the selected time
        if appointment_request.time not in schedule:
            raise HTTPException(status_code=400, detail=f"Time '{appointment_request.time}' is not available for {doctor_specialization} on {formatted_date}.")

        # Update doctor's availability
        schedule[appointment_request.time]["available"] = "no"
        doctors_collection.update_one(
            {"_id": doctor["_id"]},
            {"$set": {"schedule.May." + formatted_date: schedule}}
        )

        # Save the appointment data in the appointments collection
        appointment_data = {
            "user_id": appointment_request.user_id,
            "doctor_specialization": doctor_specialization,
            "date": formatted_date,
            "time": appointment_request.time,
        }
        appointments_collection.insert_one(appointment_data)

        # Get user email for confirmation
        user_email = user.get("email")
        if not user_email:
            raise HTTPException(status_code=404, detail="User email not found.")

        # Send email to user confirming the appointment
        send_appointment_confirmation_email(user_email, doctor, appointment_request)

        return {"status": "success", "message": "Appointment successfully booked.", "data": appointment_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


# Function to send email to the user
def send_appointment_confirmation_email(user_email: str, doctor: dict, appointment_request: AppointmentRequest):
    try:
        # Email content
        html_content = f"""
        <div style="max-width:600px;margin:0 auto;background-color:#ffffff;padding:20px;border:1px solid #ddd;border-radius:8px;font-family:Arial,sans-serif;color:#333;">
            <div style="text-align:center;">
                <img src="https://static.vecteezy.com/system/resources/thumbnails/017/177/954/small_2x/round-medical-cross-symbol-on-transparent-background-free-png.png" alt="Medical Logo" style="max-height:85px;"> 
            </div>

            <div style="margin:10px 0;font-size:16px;">
                Dear {user_email},<br>
                Your appointment has been successfully booked.<br><br>
                <strong>Appointment Details:</strong><br>
                <strong>Doctor:</strong> Dr. {doctor['name']}<br>
                <strong>Specialization:</strong> {doctor['field']}<br>
                <strong>Hospital:</strong> {doctor['hospital']}<br>
                <strong>Date:</strong> {appointment_request.date}<br>
                <strong>Time:</strong> {appointment_request.time}<br><br>
                Please be sure to arrive on time for your appointment.<br>
                Thank you for choosing us! 
            </div>
            <div style="margin-top:10px;">
                Best Regards,<br>
                <strong>Medical Support Team</strong> 
            </div>
        </div>
        """

        # Setting up the email details
        msg = MIMEMultipart()
        msg['From'] = "reyjohnandraje2002@gmail.com"
        msg['To'] = user_email
        msg['Subject'] = "Appointment Confirmation"

        msg.attach(MIMEText(html_content, 'html'))

        # Setting up the SMTP server (using Gmail as an example)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login("reyjohnandraje2002@gmail.com", "xwkb uxzu wwjk mzgq")
            server.sendmail(msg['From'], msg['To'], msg.as_string())

    except Exception as e:
        print(f"Failed to send email: {str(e)}")

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

@app.get("/request-loa")
async def request_loa(
    member_id: str = Query(..., description="10-digit member ID"),
    service_type: str = Query(..., description="Type of service requested")
):
    try:
        # Fetch user info
        user = users_collection.find_one({"member_id": member_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        # Fetch service cost
        service = services_collection.find_one({"service_type": service_type})
        if not service:
            return {"status": "denied", "reason": f"Service '{service_type}' not recognized."}

        service_cost = service.get("cost", 0)
        remaining_credits = user.get("remaining_credits", 0.0)

        # Check credits vs service cost
        if service_cost > remaining_credits:
            return {
                "status": "denied",
                "reason": f"Insufficient credits. Required: ₱{service_cost}, Available: ₱{remaining_credits:.2f}."
            }

        # Approve: Deduct credits and add request record
        new_balance = remaining_credits - service_cost
        new_request = {
            "date": datetime.now(timezone("Asia/Manila")).strftime("%Y-%m-%d %H:%M"),
            "service_type": service_type,
            "amount": service_cost,
            "status": "approved"
        }

        users_collection.update_one(
            {"member_id": member_id},
            {
                "$push": {"requests": new_request},
                "$set": {"remaining_credits": new_balance}
            }
        )

        return {
            "status": "approved",
            "message": f"LOA approved for {service_type}. Deducted ₱{service_cost}. Remaining balance: ₱{new_balance:.2f}.",
            "new_balance": new_balance
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing LOA: {str(e)}")

# Generic error handler
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return {
        "status": "error",
        "message": f"An unexpected error occurred: {str(exc)}"
    }
