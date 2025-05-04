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

# Pydantic model for user input (not used directly here, but kept for future use)
class UserRequest(BaseModel):
    user_id: str

# Convert MongoDB document to JSON-safe dict, excluding '_id' field
def serialize_user(user):
    if user:
        user.pop('_id', None)  # Remove MongoDB internal ID
        return user
    return None

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

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return {
        "status": "error",
        "message": f"An unexpected error occurred: {str(exc)}"
    }
