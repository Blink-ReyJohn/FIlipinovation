from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo import MongoClient, errors
from typing import Optional

# MongoDB connection
client = MongoClient("mongodb+srv://reyjohnandraje2002:ReyJohn17@concentrix.txv3t.mongodb.net/?retryWrites=true&w=majority&appName=Concentrix")
db = client["Filipinovation"]
users_collection = db["users"]

app = FastAPI()

# Pydantic model for user input (fetching by ID)
class UserRequest(BaseModel):
    user_id: str

@app.get("/check_user/{user_id}")
async def check_user(user_id: str):
    """
    Fetches a user by ID and checks if the user exists in the MongoDB collection.
    Handles potential errors such as missing user or database issues.
    """
    try:
        # Search for user by user_id in the MongoDB collection
        user = users_collection.find_one({"user_id": user_id})
        
        if user:
            # If user exists, return a success response
            return {"status": "success", "message": f"User with ID {user_id} found."}
        else:
            # If user doesn't exist, raise a 404 HTTP exception
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found.")

    except errors.ServerSelectionTimeoutError:
        # Handle connection issues or timeout error
        raise HTTPException(status_code=500, detail="Database connection error. Please try again later.")
    
    except errors.PyMongoError as e:
        # Catch any other MongoDB errors
        raise HTTPException(status_code=500, detail=f"MongoDB error: {str(e)}")

    except Exception as e:
        # Handle unexpected errors
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

# Error handling for the entire application in case of uncaught exceptions
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return {"status": "error", "message": f"An unexpected error occurred: {str(exc)}"}
