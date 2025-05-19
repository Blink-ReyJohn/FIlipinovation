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

app = FastAPI()

client = MongoClient("mongodb+srv://reyjohnandraje2002:ReyJohn17@concentrix.txv3t.mongodb.net/?retryWrites=true&w=majority&appName=Concentrix")
filipinovation_db = client["Filipinovation"]
hmo_db = client["hmo_system"]

doctors_collection = filipinovation_db["doctors"]
filipinovation_users = filipinovation_db["users"]
appointments_collection = filipinovation_db["appointments"]
services_collection = filipinovation_db["services"]
hmo_users = hmo_db["users"]

nlp = spacy.load("en_core_web_sm")

class AppointmentRequest(BaseModel):
    user_id: str
    doctor_specialization: str
    date: str
    time: str

def serialize_doctor(doctor):
    if doctor:
        doctor.pop('_id', None)
        return doctor
    return None

@app.get("/customer-info")
async def get_customer_info(member_id: str = Query(..., min_length=10, max_length=10, description="10-digit member ID")):
    user = hmo_users.find_one({"member_id": member_id})
    if not user:
        raise HTTPException(status_code=404, detail=f"User with member_id '{member_id}' not found.")
    user.pop('_id', None)
    return {"status": "success", "data": user}

from datetime import datetime
from fastapi import HTTPException

from datetime import datetime
from fastapi import HTTPException

@app.get("/doctor_availability_by_name")
async def check_doctor_availability_by_name(doctor_name: str = "", date: str = ""):
    try:
        missing = []
        if not doctor_name:
            missing.append("doctor_name")
        if not date:
            missing.append("date")

        if missing:
            received = {
                "doctor_name": doctor_name,
                "date": date
            }
            raise HTTPException(
                status_code=400,
                detail={
                    "error": f"Missing required parameter(s): {', '.join(missing)}.",
                    "received": received
                }
            )

        formatted_date = date.strip()  # e.g. "May 1"

        doctor = doctors_collection.find_one({
            "name": {"$regex": doctor_name, "$options": "i"}
        })

        if not doctor:
            raise HTTPException(status_code=404, detail=f"Doctor '{doctor_name}' not found.")

        schedule = doctor.get("schedule", [])
        # Filter schedule entries matching the full date string
        day_schedule = [entry for entry in schedule if entry.get("date") == formatted_date]

        if day_schedule:
            available_times = [entry["time"] for entry in day_schedule if entry.get("available") == "yes"]
            unavailable_times = [entry["time"] for entry in day_schedule if entry.get("available") != "yes"]

            if available_times:
                sorted_times = sorted(available_times, key=lambda t: datetime.strptime(t, "%I:%M %p"))
                start = datetime.strptime(sorted_times[0], "%I:%M %p").strftime("%-I %p")
                end = datetime.strptime(sorted_times[-1], "%I:%M %p").strftime("%-I %p")
                time_range = f"{start} to {end}"

                if unavailable_times:
                    unavailable_hours = [datetime.strptime(t, "%I:%M %p").strftime("%-I %p") for t in unavailable_times]
                    message = f"Dr. {doctor_name} is available on {formatted_date} from {time_range}, except {', '.join(unavailable_hours)}."
                else:
                    message = f"Dr. {doctor_name} is available on {formatted_date} from {time_range}."
            else:
                message = f"Dr. {doctor_name} is not available on {formatted_date}."
        else:
            message = f"Dr. {doctor_name} is not available on {formatted_date}."

        return {
            "status": "success",
            "message": message,
            "doctor": {"name": doctor.get("name"), "message": message}
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.get("/check_user/{user_id}")
async def check_user(user_id: str):
    try:
        user = filipinovation_users.find_one({"user_id": user_id})
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

def normalize_time_string(time_str: str) -> str:
    try:
        parsed_time = datetime.strptime(time_str.replace(" ", "").upper(), "%I:%M%p")
    except ValueError:
        try:
            parsed_time = datetime.strptime(time_str.replace(" ", "").upper(), "%I%p")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid time format. Use e.g., '9AM', '3:00PM'.")
    return parsed_time.strftime("%-I:%M %p")

@app.get("/book_appointment")
async def book_appointment(user_id: str, doctor_specialization: str, date: str, time: str):
    try:
        doctor_specialization_lower = doctor_specialization.lower()
        normalized_time = normalize_time_string(time)

        # Validate user
        user = filipinovation_users.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found.")
        user_email = user.get("email")
        if not user_email:
            raise HTTPException(status_code=400, detail="User email is missing.")

        # Validate doctor
        doctor = doctors_collection.find_one({
            "field": {"$regex": doctor_specialization_lower, "$options": "i"}
        })
        if not doctor:
            raise HTTPException(status_code=404, detail=f"No doctor with specialization '{doctor_specialization}' found.")

        # Validate schedule
        schedule = doctor.get("schedule", [])
        matching_slot = next(
            (s for s in schedule if s.get("date", "").lower() == date.lower()
             and normalize_time_string(s.get("time", "")) == normalized_time),
            None
        )
        if not matching_slot:
            raise HTTPException(status_code=400, detail=f"Doctor is not available on {date} at {normalized_time}.")
        if matching_slot.get("available") != "yes":
            raise HTTPException(status_code=400, detail=f"Slot on {date} at {normalized_time} is already booked.")

        # ✅ All checks passed — proceed to update and send confirmation
        doctors_collection.update_one(
            {"_id": doctor["_id"], "schedule.date": date, "schedule.time": matching_slot["time"]},
            {"$set": {"schedule.$.available": "no"}}
        )

        appointment_data = {
            "user_id": user_id,
            "doctor_specialization": doctor_specialization_lower,
            "date": date,
            "time": normalized_time
        }
        appointments_collection.insert_one(appointment_data)

        send_appointment_confirmation_email(user_email, doctor, date, normalized_time)

        return {
            "status": "success",
            "message": "Appointment successfully booked.",
            "data": appointment_data
        }

    except HTTPException as http_err:
        return {
            "status": "error",
            "data": {
                "detail": http_err.detail
            }
        }
    except Exception as e:
        print(f"[BOOK_APPOINTMENT_ERROR]: {str(e)}")
        return {
            "status": "error",
            "data": {
                "detail": "An unexpected error occurred."
            }
        }

def send_appointment_confirmation_email(user_email: str, doctor: dict, date: str, time: str):
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
            <strong>Date:</strong> {date}<br>
            <strong>Time:</strong> {time}<br><br>
            Please be sure to arrive on time for your appointment.<br>
            Thank you for choosing us! 
        </div>
        <div style="margin-top:10px;">
            Best Regards,<br>
            <strong>Medical Support Team</strong> 
        </div>
    </div>
    """
    msg = MIMEMultipart()
    msg['From'] = "reyjohnandraje2002@gmail.com"
    msg['To'] = user_email
    msg['Subject'] = "Appointment Confirmation"
    msg.attach(MIMEText(html_content, 'html'))

    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login("reyjohnandraje2002@gmail.com", "xwkb uxzu wwjk mzgq")
        server.sendmail(msg['From'], msg['To'], msg.as_string())

@app.get("/nearest_available_doctor/{user_id}/{doctor_specialization}")
async def get_nearest_available_doctor(user_id: str, doctor_specialization: str):
    try:
        user_id = str(user_id)
        doctor_specialization = str(doctor_specialization).lower()
        user = filipinovation_users.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        user_coords = (user.get("latitude"), user.get("longitude"))
        if None in user_coords:
            raise HTTPException(status_code=400, detail="User coordinates are missing.")
        doctors_cursor = doctors_collection.find({
            "field": {"$regex": doctor_specialization, "$options": "i"},
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
        nearest_doctor.pop("_id", None)
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
        user = hmo_users.find_one({"member_id": member_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        plan = user.get("plan", "Unknown")
        remaining_credits = user.get("remaining_credits", 0.0)
        service = services_collection.find_one({"service_type": service_type})
        if not service:
            return {
                "status": "denied",
                "reason": f"Service '{service_type}' not recognized.",
                "user_plan": plan,
                "remaining_credits": remaining_credits
            }
        service_cost = service.get("cost", 0)
        if service_cost > remaining_credits:
            return {
                "status": "denied",
                "reason": f"Insufficient credits. Required: ₱{service_cost}, Available: ₱{remaining_credits:.2f}.",
                "user_plan": plan,
                "remaining_credits": remaining_credits
            }
        new_balance = remaining_credits - service_cost
        new_request = {
            "date": datetime.now(timezone("Asia/Manila")).strftime("%Y-%m-%d %H:%M"),
            "service_type": service_type,
            "amount": service_cost,
            "status": "approved"
        }
        hmo_users.update_one(
            {"member_id": member_id},
            {
                "$push": {"requests": new_request},
                "$set": {"remaining_credits": new_balance}
            }
        )
        return {
            "status": "approved",
            "message": f"LOA approved for {service_type}. Deducted ₱{service_cost}.",
            "user_plan": plan,
            "previous_balance": remaining_credits,
            "new_balance": new_balance
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing LOA: {str(e)}")

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return {
        "status": "error",
        "message": f"An unexpected error occurred: {str(exc)}"
    }
