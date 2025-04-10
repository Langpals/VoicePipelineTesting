import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os
import json

# Initialize Firebase
try:
    # Try to get the app if it's already initialized
    firebase_admin.get_app()
except ValueError:
    # Initialize it if not already done
    cred = credentials.Certificate("./bern-8dbc2-firebase-adminsdk-fbsvc-f2d05b268c.json")
    firebase_admin.initialize_app(cred)

# Get a reference to the Firestore database
db = firestore.client()

# Function to upload prompts from a dictionary
def upload_prompts(prompts_dict):
    """
    Upload multiple prompts to Firestore.
    
    Args:
        prompts_dict: Dictionary with prompt names as keys and prompt content as values
    """
    # Create a batch write
    batch = db.batch()
    
    for prompt_name, prompt_text in prompts_dict.items():
        doc_ref = db.collection("Prompts").document(prompt_name)
        batch.set(doc_ref, {"content": prompt_text})
    
    # Commit the batch
    batch.commit()
    print(f"Successfully uploaded {len(prompts_dict)} prompts to Firestore")

# Function to add a single new prompt
def add_prompt(prompt_name, prompt_content):
    """
    Add a single new prompt to Firestore.
    
    Args:
        prompt_name: The name/ID for the prompt document
        prompt_content: The content of the prompt
    """
    doc_ref = db.collection("Prompts").document(prompt_name)
    doc_ref.set({"content": prompt_content})
    print(f"Successfully added prompt: {prompt_name}")

# Function to retrieve a specific prompt
def get_prompt(prompt_name):
    """
    Retrieve a specific prompt from Firestore.
    
    Args:
        prompt_name: The name of the prompt to retrieve
        
    Returns:
        The prompt content or None if not found
    """
    doc_ref = db.collection("Prompts").document(prompt_name)
    doc = doc_ref.get()
    
    if doc.exists:
        return doc.to_dict().get("content")
    else:
        return None

# Function to update a specific prompt
def update_prompt(prompt_name, new_content):
    """
    Update an existing prompt in Firestore.
    
    Args:
        prompt_name: The name of the prompt to update
        new_content: The new content for the prompt
    """
    doc_ref = db.collection("Prompts").document(prompt_name)
    doc_ref.update({"content": new_content})
    print(f"Updated {prompt_name} successfully")

# Function to delete a prompt
def delete_prompt(prompt_name):
    """
    Delete a prompt from Firestore.
    
    Args:
        prompt_name: The name of the prompt to delete
    """
    doc_ref = db.collection("Prompts").document(prompt_name)
    doc_ref.delete()
    print(f"Deleted {prompt_name} successfully")

# Function to list all prompts
def list_prompts():
    """
    List all prompts in the Prompts collection.
    
    Returns:
        A list of prompt names
    """
    prompts = []
    docs = db.collection("Prompts").stream()
    
    for doc in docs:
        prompts.append(doc.id)
    
    return prompts

# Function to save prompts to a local JSON file
def export_prompts_to_file(filename="prompts_backup.json"):
    
    prompts = {}
    docs = db.collection("Prompts").stream()
    
    for doc in docs:
        prompts[doc.id] = doc.to_dict().get("content")
    
    with open(filename, "w") as f:
        json.dump(prompts, f, indent=2)
    
    print(f"Exported {len(prompts)} prompts to {filename}")

# Function to load prompts from a local JSON file
def import_prompts_from_file(filename="prompts_backup.json"):
    """
    Import prompts from a local JSON file and upload them to Firestore.
    
    Args:
        filename: The name of the file to load the prompts from
    """
    if not os.path.exists(filename):
        print(f"File {filename} not found!")
        return
    
    with open(filename, "r") as f:
        prompts = json.load(f)
    
    upload_prompts(prompts)
    print(f"Imported {len(prompts)} prompts from {filename}")

# Example use: Upload the standard prompts
if __name__ == "__main__":
    # Example: Add a new prompt
    new_zoo_prompt = """You are a child-friendly AI Spanish tutor named Amigo, and you are now switching into a special zoo-themed learning activity for children. The child is an English speaker learning Spanish. 

This game is called "Spanish Zoo Adventure." You will take the child on a pretend trip to a magical zoo where the animals can talk and teach Spanish words! At each animal enclosure, you'll introduce one or two new Spanish words related to animals, colors, or actions.

Keep the energy high, use lots of praise, and speak in short, simple sentences. Focus on very basic vocabulary like animal names, colors, and simple actions. Introduce only one Spanish word at a time with fun associations.

Always ask a question at the end of every message. Be extremely encouraging and enthusiastic. If the child gives an unexpected answer, gently redirect and provide the Spanish word again.

Start the adventure with:

'¡Hola! Welcome to our magical Spanish Zoo Adventure! I'm Amigo, your guide today. Look over there - can you see the big elephant? Do you know how to say elephant in Spanish?'"""
    
    add_prompt("ZOO_GAME_PROMPT", new_zoo_prompt)
    
    # Example: List all prompts
    all_prompts = list_prompts()
    print("\nAll available prompts:")
    for prompt in all_prompts:
        print(f"- {prompt}")
    
    # Example: Retrieve a prompt
    print("\nRetrieving ZOO_GAME_PROMPT...")
    zoo_prompt = get_prompt("ZOO_GAME_PROMPT")
    if zoo_prompt:
        print(f"Successfully retrieved prompt with length: {len(zoo_prompt)} characters")
    
    # Example: Export all prompts to a file
    export_prompts_to_file()