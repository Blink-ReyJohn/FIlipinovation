from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from pymongo import MongoClient, errors
from typing import Optional
from bson import ObjectId

# MongoDB connection
client = MongoClient("mongodb+srv://reyjohnandraje2002:ReyJohn17@concentrix.txv3t.mongodb.net/?retryWrites=true&w=majority&appName=Concentrix")
db = client["Filipinovation"]
users_collection = db["users"]

app = FastAPI()

# Pydantic model (not used in this GET endpoint, but useful for validation if POST/PUT later)
class UserRequest(BaseModel):
    user_id: str

# Convert MongoDB document to JSON-safe dict
def serialize_user(user):
    user.pop('_id', None)  # Remove MongoDB internal ID
    return user

@app.get("/check_user/{user_id}")
async def check_user(user_id: str):
    """
    Fetches a user by ID and returns user information if exists.
    Handles potential errors such as missing user or database issues.
    """
    try:
        # Search for user by user_id
        user = users_collection.find_one({"user_id": user_id})
        
        if user:
            return {
                "status": "success",
                "message": f"User with ID {user_id} found.",
                "user": serialize_user(user)
            }
        else:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found.")

    except errors.ServerSelectionTimeoutError:
        raise HTTPException(status_code=500, detail="Database connection error. Please try again later.")
    
    except errors.PyMongoError as e:
        raise HTTPException(status_code=500, detail=f"MongoDB error: {str(e)}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return {
        "status": "error",
        "message": f"An unexpected error occurred: {str(exc)}"
    }
