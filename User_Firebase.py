import firebase_admin
from firebase_admin import credentials, firestore
from typing import Dict, Any

# Get Firestore client
def get_firestore_client():
    """Get or initialize Firestore client"""
    try:
        # Try to get the app if it's already initialized
        firebase_admin.get_app()
    except ValueError:
        # Initialize it if not already done
        cred = credentials.Certificate("./bern-8dbc2-firebase-adminsdk-fbsvc-f2d05b268c.json")
        firebase_admin.initialize_app(cred)
    
    return firestore.client()

def get_user_from_firestore(user_id: str) -> Dict[str, Any]:
    """
    Retrieve user details from Firestore using the user ID.
    
    Args:
        user_id: Unique identifier for the user document
    
    Returns:
        Dict with user data or empty values if user doesn't exist
    """
    try:
        db = get_firestore_client()
        user_doc = db.collection('Users').document(user_id).get()
        
        # Define the default empty return structure
        default_user = {
            'name': None,
            'age': None,
            'language': None,
            'proficiency': None
        }
        
        if user_doc.exists:
            return user_doc.to_dict()
        else:
            return default_user
    except Exception as e:
        print(f"Error retrieving user: {e}")
        return {
            'name': None,
            'age': None,
            'language': None,
            'proficiency': None
        }

def add_user_to_firestore(user_id: str, name: str, age: int, language: str, proficiency: str) -> bool:
    """
    Add a user to the Users collection in Firestore.
    
    Args:
        user_id: Unique identifier for the user document
        name: User's name
        age: User's age
        language: Language the user knows
        proficiency: User's proficiency level in the language
    
    Returns:
        bool: True if operation was successful, False otherwise
    """
    try:
        db = get_firestore_client()
        users_ref = db.collection('Users')
        
        # Create a new document with the provided ID
        user_data = {
            'name': name,
            'age': age,
            'language': language,
            'proficiency': proficiency
        }
        
        users_ref.document(user_id).set(user_data)
        return True
    except Exception as e:
        print(f"Error adding user: {e}")
        return False