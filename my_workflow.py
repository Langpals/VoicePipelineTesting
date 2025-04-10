import random
from collections.abc import AsyncIterator
from typing import Callable, Dict, Optional, List
from agents import Agent, Runner, TResponseInputItem, function_tool
from agents.extensions.handoff_prompt import prompt_with_handoff_instructions
from agents.voice import VoiceWorkflowBase, VoiceWorkflowHelper
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
try:
    # Try to get the app if it's already initialized
    firebase_admin.get_app()
except ValueError:
    # Initialize it if not already done
    cred = credentials.Certificate("./bern-8dbc2-firebase-adminsdk-fbsvc-f2d05b268c.json")
    firebase_admin.initialize_app(cred)

# Get Firestore client
db = firestore.client()

# Helper function for logging
def log_debug(message: str) -> None:
    """Helper function to print debug messages"""
    print(f"[DEBUG] {message}")

# Function to retrieve all prompts from Firebase
def get_all_prompts() -> Dict[str, str]:
    """
    Retrieve all prompt documents from the Prompts collection.
    
    Returns:
        Dictionary with prompt names as keys and their content as values.
    """
    log_debug("Retrieving prompts from Firebase...")
    prompts = {}
    
    # Get all documents from the Prompts collection
    prompt_docs = db.collection("Prompts").stream()
    
    for doc in prompt_docs:
        prompt_name = doc.id
        prompt_content = doc.to_dict().get("content", "")
        prompts[prompt_name] = prompt_content
        log_debug(f"Retrieved prompt: {prompt_name} ({len(prompt_content)} chars)")
    
    return prompts

# Load all prompts from Firebase
all_prompts = get_all_prompts()

# Access prompts by their document IDs
CHOICE_LAYER_PROMPT = all_prompts.get("CHOICE_LAYER_PROMPT", "")
CAR_GAME_PROMPT = all_prompts.get("CAR_GAME_PROMPT", "")
ISLAND_GAME_PROMPT = all_prompts.get("ISLAND_GAME_PROMPT", "")

# Function to retrieve a specific prompt
def get_prompt(prompt_name: str) -> str:
    """
    Retrieve a specific prompt from Firebase.
    
    Args:
        prompt_name: The document ID of the prompt to retrieve.
        
    Returns:
        The prompt content or empty string if not found.
    """
    doc_ref = db.collection("Prompts").document(prompt_name)
    doc = doc_ref.get()
    
    if doc.exists:
        return doc.to_dict().get("content", "")
    else:
        log_debug(f"Warning: Prompt '{prompt_name}' not found!")
        return ""

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

@function_tool
def get_child_age() -> int:
    """Get the child's age from the system."""
    # This would normally fetch from a database or user profile
    # For demo purposes, we return a fixed age
    return 5

# Function to create game agents from available prompts
def create_game_agents() -> Dict[str, Dict]:
    """
    Create game agents dynamically based on available prompts in Firebase.
    
    Returns:
        Dictionary of available agents with their info.
    """
    available_agents = {}
    
    # Define fixed agents (could be made dynamic too if needed)
    if "CAR_GAME_PROMPT" in all_prompts:
        car_game_agent = Agent(
            name="CarGame",
            handoff_description="A car-themed Spanish learning adventure for children.",
            instructions=prompt_with_handoff_instructions(CAR_GAME_PROMPT),
            model="gpt-4o",
            tools=[track_vocabulary]
        )
        
        available_agents["CarGame"] = {
            "name": "Spanish Road Trip",
            "description": "Take a magical car journey and learn Spanish words for colors, animals, and objects!",
            "agent": car_game_agent
        }
    
    if "ISLAND_GAME_PROMPT" in all_prompts:
        island_game_agent = Agent(
            name="IslandGame",
            handoff_description="A pirate-themed island adventure for learning Spanish.",
            instructions=prompt_with_handoff_instructions(ISLAND_GAME_PROMPT),
            model="gpt-4o",
            tools=[track_vocabulary]
        )
        
        available_agents["IslandGame"] = {
            "name": "Pirate Island Adventure",
            "description": "Sail between islands as a pirate and discover Spanish treasure words!",
            "agent": island_game_agent
        }
    
    # You could scan for other game prompts here and create agents for them
    # For example, looking for prompts with a specific naming pattern like "GAME_*_PROMPT"
    
    return available_agents

# Create our available agents
AVAILABLE_AGENTS = create_game_agents()

# Create the choice layer agent with info about available agents
choice_layer_agent = Agent(
    name="ChoiceLayer",
    handoff_description="A Spanish language tutor that helps children choose learning activities.",
    instructions=prompt_with_handoff_instructions(
        CHOICE_LAYER_PROMPT + "\n\nAVAILABLE_AGENTS: " + 
        ", ".join([f"{key}: {value['name']} - {value['description']}" for key, value in AVAILABLE_AGENTS.items()])
    ),
    model="gpt-4o",
    handoffs=[agent_info["agent"] for agent_info in AVAILABLE_AGENTS.values()],
    tools=[get_child_age, track_vocabulary]
)

# Add handoff back to the choice layer for all game agents
for agent_info in AVAILABLE_AGENTS.values():
    agent_info["agent"].handoffs.append(choice_layer_agent)

class LanguageTutorContext:
    """Context for tracking state in the language tutor workflow."""
    def __init__(self):
        self.child_age: Optional[int] = None
        self.learned_words: Dict[str, str] = {}  # Spanish word -> English translation
        self.current_game: Optional[str] = None
        self.engagement_score: int = 3  # Start with neutral engagement

class MyWorkflow(VoiceWorkflowBase):
    def __init__(self, on_start: Callable[[str], None]):
        """
        Initialize the Spanish language tutor workflow.
        
        Args:
            on_start: A callback function that is called when the workflow starts processing a transcription.
        """
        self._input_history: list[TResponseInputItem] = []
        self._current_agent = choice_layer_agent  # Start with the choice layer
        self._on_start = on_start
        self._context = LanguageTutorContext()
        
        # Initialize with a welcome message in the history
        self._input_history.append({
            "role": "assistant",
            "content": "¡Hola! I'm Amigo, your Spanish language friend! I'm here to help you learn some fun Spanish words. Can you tell me how old you are?"
        })

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
        
        # Handle simple game switching keywords for easier testing
        lowercase_input = transcription.lower()
        
        # Check for direct game selection commands (for testing/debugging)
        if "play car game" in lowercase_input or "car ride" in lowercase_input:
            log_debug("Detected direct request for Car Game")
            self._current_agent = AVAILABLE_AGENTS["CarGame"]["agent"]
            self._context.current_game = "CarGame"
            yield "Switching to Spanish Road Trip! Get ready for a fun car adventure!"
            self._input_history.append({
                "role": "assistant", 
                "content": "Switching to Spanish Road Trip! Get ready for a fun car adventure!"
            })
            
        elif "play island game" in lowercase_input or "pirate adventure" in lowercase_input:
            log_debug("Detected direct request for Island Game")
            self._current_agent = AVAILABLE_AGENTS["IslandGame"]["agent"]
            self._context.current_game = "IslandGame"
            yield "Switching to Pirate Island Adventure! Get ready to sail the seas!"
            self._input_history.append({
                "role": "assistant",
                "content": "Switching to Pirate Island Adventure! Get ready to sail the seas!"
            })
            
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
            
            # Update the current agent and game context
            self._current_agent = result.last_agent
            
            # Update the current game in the context
            for game_id, game_info in AVAILABLE_AGENTS.items():
                if game_info["agent"] == self._current_agent:
                    self._context.current_game = game_id
                    log_debug(f"Updated current game to {game_id}")
                    break
                    
            # If we've returned to the choice layer
            if self._current_agent == choice_layer_agent:
                self._context.current_game = None
                log_debug("Returned to choice layer")