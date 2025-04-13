import random
import re
import os
import string
from collections.abc import AsyncIterator
from typing import Callable, Dict, Optional, List, Any
from agents import Agent, Runner, TResponseInputItem, function_tool
from agents.extensions.handoff_prompt import prompt_with_handoff_instructions
from agents.voice import VoiceWorkflowBase, VoiceWorkflowHelper
import firebase_admin
from firebase_admin import credentials, firestore

# Import our Firebase user functions
from User_Firebase import get_user_from_firestore, add_user_to_firestore

# Helper function for logging
def log_debug(message: str) -> None:
    """Helper function to print debug messages"""
    print(f"[DEBUG] {message}")

# Initialize Firebase
try:
    # Try to get the app if it's already initialized
    firebase_admin.get_app()
except ValueError:
    # Initialize it if not already done
    cred_path = os.environ.get("FIREBASE_CREDENTIALS", "./bern-8dbc2-firebase-adminsdk-fbsvc-f2d05b268c.json")
    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        log_debug(f"Error initializing Firebase: {e}. Some functionality may be limited.")

# Get Firestore client
try:
    db = firestore.client()
except Exception as e:
    log_debug(f"Error getting Firestore client: {e}. Using fallback options.")
    db = None

# User context will be populated from the database
# This is just a default empty template
DEFAULT_USER_TEMPLATE = {
    'id': None,
    'name': None,
    'age': None,
    'language': None,
    'proficiency': None
}

# Define placeholder functions for when we can't access the instance methods
def placeholder_save_user_info(name: str, age: int) -> str:
    """Placeholder for save_user_info when instance method is not available"""
    return f"User info for {name} (age {age}) would be saved"

def placeholder_get_child_name() -> str:
    """Placeholder for get_child_name when instance method is not available"""
    # Return None to indicate we need to collect this information
    return None

def placeholder_get_child_age() -> int:
    """Placeholder for get_child_age when instance method is not available"""
    # Return None to indicate we need to collect this information
    return None

# Define a vocabulary tracking tool
@function_tool
def track_vocabulary(word: str, translation: str, context: str) -> str:
    """Track a Spanish vocabulary word that was taught to the child.
    
    Args:
        word: The Spanish vocabulary word being tracked
        translation: The English translation of the word
        context: Additional context about how the word was taught (can be empty string)
    """
    log_debug(f"Tracking vocabulary: {word} = {translation} ({context})")
    return f"Added '{word}' ({translation}) to the child's vocabulary list."

# Function to retrieve all prompts from Firebase
def get_all_prompts() -> Dict[str, str]:
    """
    Retrieve all prompt documents from the Prompts collection.
    
    Returns:
        Dictionary with prompt names as keys and their content as values.
    """
    log_debug("Retrieving prompts from Firebase...")
    prompts = {}
    
    if db is None:
        log_debug("Firebase not available. Workflow cannot function without prompts.")
        return {}
    
    try:
        # Get all documents from the Prompts collection
        prompt_docs = db.collection("Prompts").stream()
        
        for doc in prompt_docs:
            prompt_name = doc.id
            prompt_content = doc.to_dict().get("content", "")
            prompts[prompt_name] = prompt_content
            log_debug(f"Retrieved prompt: {prompt_name} ({len(prompt_content)} chars)")
        
        # If no prompts were found, log an error
        if not prompts:
            log_debug("No prompts found in Firebase. The workflow cannot function without prompts.")
            return {}
        
    except Exception as e:
        log_debug(f"Error retrieving prompts: {e}. The workflow cannot function without prompts.")
        return {}
    
    return prompts

# Template replacement function
def replace_user_templates(text: str, user_data: Dict[str, Any]) -> str:
    """
    Replace user template variables (${user.field}) with actual values.
    
    Args:
        text: The text containing templates
        user_data: Dictionary with user data
        
    Returns:
        Text with templates replaced by user values
    """
    if not text:
        return text
        
    # Define a regex pattern for ${user.field} templates
    pattern = r'\${user\.([a-zA-Z]+)}'
    
    def replace_match(match):
        field = match.group(1)
        value = user_data.get(field)
        return str(value) if value is not None else f"[unknown {field}]"
    
    # Replace all matches
    return re.sub(pattern, replace_match, text)

# Function to detect game prompts and extract metadata
def detect_game_prompts(prompts: Dict[str, str], user_data: Dict[str, Any]) -> Dict[str, Dict]:
    """
    Detect game prompts from the full set of prompts and extract metadata.
    
    Args:
        prompts: Dictionary of all prompts
        user_data: Dictionary with user data for template replacement
        
    Returns:
        Dictionary mapping prompt_id to metadata about that game
    """
    game_prompts = {}
    
    # Pattern for detecting game prompt IDs (looking for *_GAME_PROMPT pattern)
    game_pattern = re.compile(r'(.+)_GAME_PROMPT$')
    
    # Look for standard game prompts
    for prompt_id, content in prompts.items():
        match = game_pattern.match(prompt_id)
        
        if match:
            game_id = match.group(1)  # Extract the game name part
            
            # Extract game name from prompt content (first line often has it)
            name = game_id.replace("_", " ")  # Default name
            description = f"Learn Spanish through a fun {game_id.lower()} adventure!"  # Default description
            
            # Try to extract better name/description from the prompt content
            if "game is called" in content.lower():
                # Look for a line like "This game is called 'Spanish Road Trip.'"
                for line in content.split('\n'):
                    if "game is called" in line.lower():
                        # Extract the name within quotes if present
                        name_match = re.search(r'"([^"]+)"', line)
                        if name_match:
                            name = name_match.group(1)
                        else:
                            # Try extracting text after "called" without quotes
                            name_match = re.search(r'called\s+(.+?)[\.\s]', line)
                            if name_match:
                                name = name_match.group(1).strip('" ')
            
            # Store the metadata
            game_prompts[prompt_id] = {
                "game_id": game_id,
                "name": name,
                "description": description,
                "content": replace_user_templates(content, user_data)  # Replace templates with user_data
            }
    
    # Manually handle special cases for backward compatibility
    if "CAR_GAME_PROMPT" in prompts and "CAR_GAME_PROMPT" not in game_prompts:
        game_prompts["CAR_GAME_PROMPT"] = {
            "game_id": "CarGame",
            "name": "Spanish Road Trip",
            "description": "Take a magical car journey and learn Spanish words for colors, animals, and objects!",
            "content": replace_user_templates(prompts["CAR_GAME_PROMPT"], user_data)  # Replace templates with user_data
        }
    
    if "ISLAND_GAME_PROMPT" in prompts and "ISLAND_GAME_PROMPT" not in game_prompts:
        game_prompts["ISLAND_GAME_PROMPT"] = {
            "game_id": "IslandGame",
            "name": "Pirate Island Adventure",
            "description": "Sail between islands as a pirate and discover Spanish treasure words!",
            "content": replace_user_templates(prompts["ISLAND_GAME_PROMPT"], user_data)  # Replace templates with user_data
        }
    
    return game_prompts

# Initialize agents and functions
def initialize_agents(user_context):
    """
    Initialize all agents with the provided user context.
    This allows reinitialization when user data changes.
    
    Args:
        user_context: Dictionary containing user data (id, name, age, etc.)
    
    Returns:
        Tuple of (user_info_agent, choice_layer_agent, available_agents)
    """
    log_debug(f"Initializing agents with user context: {user_context}")
    
    # Load all prompts from Firebase
    all_prompts = get_all_prompts()
    
    # Apply template substitutions to all prompts
    for prompt_id in all_prompts:
        all_prompts[prompt_id] = replace_user_templates(all_prompts[prompt_id], user_context)
    
    # Try to get the save_user_info tool from the MyWorkflow instance if available
    try:
        # Check if we're being called from a MyWorkflow instance
        from inspect import currentframe
        frame = currentframe()
        while frame:
            if 'self' in frame.f_locals and isinstance(frame.f_locals['self'], MyWorkflow):
                # Use the instance methods if available
                save_user_info_tool = frame.f_locals['self']._save_user_info
                child_name_tool = frame.f_locals['self']._get_child_name
                child_age_tool = frame.f_locals['self']._get_child_age
                break
            frame = frame.f_back
        else:
            # Fallback to placeholder functions if not available
            save_user_info_tool = function_tool(placeholder_save_user_info)
            child_name_tool = function_tool(placeholder_get_child_name)
            child_age_tool = function_tool(placeholder_get_child_age)
    except Exception as e:
        log_debug(f"Error accessing instance methods: {e}. Using placeholder functions.")
        # Safety fallback
        save_user_info_tool = function_tool(placeholder_save_user_info)
        child_name_tool = function_tool(placeholder_get_child_name)
        child_age_tool = function_tool(placeholder_get_child_age)
    
    # Get the user info prompt from Firebase
    user_info_prompt = all_prompts.get("USER_INFO_PROMPT", "")
    if not user_info_prompt:
        log_debug("USER_INFO_PROMPT not found in Firebase. Cannot initialize user info agent.")
        return None, None, {}  # Return empty values if required prompt is missing

    # Create the user info agent
    user_info_agent = Agent(
        name="UserInfoCollector",
        handoff_description="An assistant that collects the child's name and age.",
        instructions=prompt_with_handoff_instructions(user_info_prompt),
        model="gpt-4o",
        tools=[save_user_info_tool, child_name_tool, child_age_tool]
    )
    
    # Detect game prompts and extract metadata
    game_prompts = detect_game_prompts(all_prompts, user_context)
    
    # Create agents for each detected game
    available_agents = {}
    
    for prompt_id, game_info in game_prompts.items():
        game_id = game_info["game_id"]
        name = game_info["name"]
        description = game_info["description"]
        content = game_info["content"]
        
        # Create the agent
        game_agent = Agent(
            name=game_id,
            handoff_description=f"A {name} Spanish learning adventure for children.",
            instructions=prompt_with_handoff_instructions(content),
            model="gpt-4o",
            tools=[track_vocabulary, child_name_tool, child_age_tool]
        )
        
        # Add to available agents
        available_agents[game_id] = {
            "name": name,
            "description": description,
            "agent": game_agent,
            "prompt_id": prompt_id
        }
        
        log_debug(f"Created agent for game: {game_id} ({name})")
    
    # Access the choice layer prompt
    choice_layer_prompt = all_prompts.get("CHOICE_LAYER_PROMPT", "")
    if not choice_layer_prompt:
        log_debug("CHOICE_LAYER_PROMPT not found in Firebase. Cannot initialize choice layer agent.")
        return None, None, {}  # Return empty values if required prompt is missing
    
    # Create the choice layer agent with info about available agents
    choice_layer_agent = Agent(
        name="ChoiceLayer",
        handoff_description="A Spanish language tutor that helps children choose learning activities.",
        instructions=prompt_with_handoff_instructions(
            choice_layer_prompt + "\n\nAVAILABLE_AGENTS: " + 
            ", ".join([f"{key}: {value['name']} - {value['description']}" for key, value in available_agents.items()])
        ),
        model="gpt-4o",
        handoffs=[agent_info["agent"] for agent_info in available_agents.values()],
        tools=[child_name_tool, child_age_tool, track_vocabulary]
    )
    
    # Add handoffs between agents
    user_info_agent.handoffs.append(choice_layer_agent)
    
    # Add handoff back to the choice layer for all game agents
    for agent_info in available_agents.values():
        agent_info["agent"].handoffs.append(choice_layer_agent)
    
    return user_info_agent, choice_layer_agent, available_agents

class LanguageTutorContext:
    """Context for tracking state in the language tutor workflow."""
    def __init__(self):
        self.child_age: Optional[int] = None
        self.child_name: Optional[str] = None
        self.learned_words: Dict[str, str] = {}  # Spanish word -> English translation
        self.current_game: Optional[str] = None
        self.engagement_score: int = 3  # Start with neutral engagement

class MyWorkflow(VoiceWorkflowBase):
    def __init__(self, on_start: Callable[[str], None], user_id: str = 'ID1'):
        """
        Initialize the Spanish language tutor workflow.
        
        Args:
            on_start: A callback function that is called when the workflow starts processing a transcription.
            user_id: The ID of the user to load from Firebase (default is 'ID1' for testing)
        """
        self._input_history: list[TResponseInputItem] = []
        self._on_start = on_start
        self._context = LanguageTutorContext()
        
        # Create user context dictionary
        self.current_user = DEFAULT_USER_TEMPLATE.copy()
        self.current_user['id'] = user_id
        
        # Load user data from Firebase first
        try:
            user_data = get_user_from_firestore(user_id)
            
            # Update current user context with any data we have
            if user_data:
                log_debug(f"Loaded user data from Firebase for {user_id}: {user_data}")
                for key, value in user_data.items():
                    if value is not None:
                        self.current_user[key] = value
        except Exception as e:
            log_debug(f"Error loading user data: {e}. Using default values.")
        
        # Define function tools that need access to the instance
        # These need to be defined here to access self.current_user
        @function_tool
        def save_user_info(name: str, age: int) -> str:
            """
            Save the user's basic information to Firebase.
            
            Args:
                name: The user's name
                age: The user's age (as an integer)
            """
            log_debug(f"Saving user info: name={name}, age={age}")
            
            # Update current user context
            self.current_user['name'] = name
            self.current_user['age'] = age
            
            # Update the context as well
            self._context.child_name = name
            self._context.child_age = age
            
            # Save to Firebase
            try:
                success = add_user_to_firestore(
                    user_id=self.current_user['id'],
                    name=name,
                    age=age,
                    language=self.current_user['language'] or "Spanish",  # Default to Spanish
                    proficiency=self.current_user['proficiency'] or "Beginner"  # Default to Beginner
                )
                
                if success:
                    return f"Successfully saved {name}'s information!"
                else:
                    return "There was an issue saving your information. I'll continue without saving."
            except Exception as e:
                log_debug(f"Error saving user info: {e}")
                return "I'll remember your information for now, but I couldn't save it permanently."
        
        @function_tool
        def get_child_age() -> Optional[int]:
            """Get the child's age from the system."""
            # Return from current user context if available, otherwise None
            return self.current_user['age']
        
        @function_tool
        def get_child_name() -> Optional[str]:
            """Get the child's name from the system."""
            # Return from current user context if available, otherwise None
            return self.current_user['name']
        
        # Store these function tools for later use
        self._save_user_info = save_user_info
        self._get_child_age = get_child_age
        self._get_child_name = get_child_name
        
        # Initialize all agents with the current user context
        log_debug("Initializing agents...")
        self._user_info_agent, self._choice_layer_agent, self._available_agents = initialize_agents(
            self.current_user)
        
        # Check if initialization was successful
        if self._user_info_agent is None or self._choice_layer_agent is None:
            log_debug("Failed to initialize agents due to missing prompts.")
            raise ValueError("Required prompts not found in Firebase. Cannot initialize workflow.")
        
        # Determine which agent to start with based on available user info
        if self.current_user['name'] is None or self.current_user['age'] is None:
            log_debug("Missing user info, starting with UserInfoCollector")
            self._current_agent = self._user_info_agent
            greeting = "¡Hola! I'm Amigo, your Spanish language friend! Before we start, could you tell me your name and how old you are?"
        else:
            log_debug(f"User info complete, starting with ChoiceLayer")
            self._current_agent = self._choice_layer_agent
            name = self.current_user['name']
            greeting = f"¡Hola {name}! I'm Amigo, your Spanish language friend! I'm here to help you learn some fun Spanish words. What would you like to play today?"
        
        # Initialize with a welcome message in the history
        self._input_history.append({
            "role": "assistant",
            "content": greeting
        })
    
    def _trim_conversation_history(self, max_items=10):
        """Trim conversation history to prevent it from growing too large"""
        if len(self._input_history) > max_items * 2:
            # Keep first assistant message and last max_items*2-1 messages
            self._input_history = [self._input_history[0]] + self._input_history[-(max_items*2-1):]
            log_debug(f"Trimmed conversation history to {len(self._input_history)} items")

    async def run(self, transcription: str) -> AsyncIterator[str]:
        """
        Process a transcription from the child and generate a response.
        
        Args:
            transcription: The child's spoken input as text.
            
        Yields:
            Chunks of the assistant's response as they are generated.
        """
        # Call the on_start callback
        self._on_start(transcription)
        
        # Log the transcription for debugging
        log_debug(f"Received transcription: {transcription}")
        
        # Add the transcription to the input history
        self._input_history.append({
            "role": "user",
            "content": transcription,
        })
        
        # Trim history if it's getting too long
        self._trim_conversation_history()
        
        # Initialize game_switch_detected to False by default
        game_switch_detected = False
        
        # First check if we need to enforce user info collection
        if self.current_user['name'] is None or self.current_user['age'] is None:
            log_debug("Missing user info detected. Ensuring UserInfoCollector is active.")
            
            # Ensure we're using the UserInfoCollector agent
            if self._current_agent != self._user_info_agent:
                self._current_agent = self._user_info_agent
                
                # Append a message explaining why we need this information
                missing_info_message = "Before we can play a game, I need to know a bit more about you. "
                if self.current_user['name'] is None and self.current_user['age'] is None:
                    missing_info_message += "Could you tell me your name and how old you are?"
                elif self.current_user['name'] is None:
                    missing_info_message += "Could you tell me your name?"
                else:
                    missing_info_message += "Could you tell me how old you are?"
                
                yield missing_info_message
                
                self._input_history.append({
                    "role": "assistant",
                    "content": missing_info_message
                })
                
                # Set flag to skip game switching
                game_switch_detected = True
        else:
            # Handle simple game switching keywords for easier testing
            lowercase_input = transcription.lower()
            
            # Check for direct game selection commands (for testing/debugging)
            # Dynamically check all available games
            
            for game_id, game_info in self._available_agents.items():
                game_name = game_info["name"].lower()
                
                # Check for common patterns to switch to this game
                if (f"play {game_id.lower()}" in lowercase_input or 
                    f"play {game_name}" in lowercase_input or
                    game_name in lowercase_input):
                    
                    log_debug(f"Detected direct request for {game_id}")
                    self._current_agent = game_info["agent"]
                    self._context.current_game = game_id
                    
                    switch_message = f"Switching to {game_info['name']}! Get ready for a fun adventure!"
                    yield switch_message
                    
                    self._input_history.append({
                        "role": "assistant", 
                        "content": switch_message
                    })
                    
                    game_switch_detected = True
                    break
        
        # Only proceed with normal processing if no game switch was detected
        if not game_switch_detected:
            try:
                # Run the current agent with the input history
                log_debug(f"Running agent: {self._current_agent.name}")
                result = Runner.run_streamed(self._current_agent, self._input_history)
                
                # Stream the response chunks back
                async for chunk in VoiceWorkflowHelper.stream_text_from(result):
                    yield chunk
                    
                # Update the conversation history with the result
                self._input_history = result.to_input_list()
                
                # Check if there was a handoff to a different agent
                if result.last_agent != self._current_agent:
                    log_debug(f"Agent handoff: {self._current_agent.name} -> {result.last_agent.name}")
                    
                    # Check if we need to force a handoff to UserInfoCollector due to missing information
                    if (self.current_user['name'] is None or self.current_user['age'] is None) and \
                       result.last_agent != self._user_info_agent:
                        log_debug("Missing user info detected. Forcing handoff to UserInfoCollector.")
                        self._current_agent = self._user_info_agent
                        
                        # Append a message explaining the handoff to the user
                        missing_info_message = "I need to know a bit more about you before we continue. "
                        if self.current_user['name'] is None and self.current_user['age'] is None:
                            missing_info_message += "Could you tell me your name and how old you are?"
                        elif self.current_user['name'] is None:
                            missing_info_message += "Could you tell me your name?"
                        else:
                            missing_info_message += "Could you tell me how old you are?"
                        
                        self._input_history.append({
                            "role": "assistant",
                            "content": missing_info_message
                        })
                        
                        # Yield the message so the user sees it
                        yield missing_info_message
                    else:
                        # Update the current agent with the handoff target
                        self._current_agent = result.last_agent
                    
                    # If we've switched from UserInfoCollector to ChoiceLayer,
                    # potentially reinitialize agents with updated user info
                    if self._current_agent == self._choice_layer_agent and self.current_user['name'] is not None:
                        log_debug("Reinitializing agents with updated user info")
                        old_choice_layer = self._choice_layer_agent
                        
                        # Reinitialize agents
                        self._user_info_agent, self._choice_layer_agent, self._available_agents = initialize_agents(
                            self.current_user)
                        
                        # Update current_agent reference if it was pointing to the choice layer
                        if self._current_agent == old_choice_layer:
                            self._current_agent = self._choice_layer_agent
                            # Also update result.last_agent if needed
                            if hasattr(result, 'last_agent') and result.last_agent == old_choice_layer:
                                result.last_agent = self._choice_layer_agent
                    
                    # Update the current game in the context
                    for game_id, game_info in self._available_agents.items():
                        if game_info["agent"] == self._current_agent:
                            self._context.current_game = game_id
                            log_debug(f"Updated current game to {game_id}")
                            break
                            
                    # If we've returned to the choice layer
                    if self._current_agent == self._choice_layer_agent:
                        self._context.current_game = None
                        log_debug("Returned to choice layer")
                
            except Exception as e:
                log_debug(f"Error in agent execution: {e}")
                error_message = "I'm sorry, I had a problem understanding. Could you try again?"
                yield error_message
                
                self._input_history.append({
                    "role": "assistant",
                    "content": error_message
                })

if __name__ == "__main__":
    # Import modules needed for direct execution
    try:
        from PromptUpload import add_prompt, list_prompts, get_prompt
        
        # Example: Add or update the essential prompts
        print("\nChecking for required prompts in Firebase...")
        all_prompts = list_prompts()
        
        # Check if USER_INFO_PROMPT exists
        if "USER_INFO_PROMPT" not in all_prompts:
            print("USER_INFO_PROMPT not found. Please add a prompt with this ID to Firebase.")
            
        # Check if ZOO_GAME_PROMPT exists  
        if "ZOO_GAME_PROMPT" not in all_prompts:
            print("ZOO_GAME_PROMPT not found. Please add a prompt with this ID to Firebase.")
        
        # Check if CHOICE_LAYER_PROMPT exists
        if "CHOICE_LAYER_PROMPT" not in all_prompts:
            print("CHOICE_LAYER_PROMPT not found. Please add a prompt with this ID to Firebase.")
        
        print("\nAll available prompts:")
        for prompt in all_prompts:
            print(f"- {prompt}")
    except ImportError:
        print("PromptUpload module not available when running as imported module.")