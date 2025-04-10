import random
import re
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

# Function to detect game prompts and extract metadata
def detect_game_prompts(prompts: Dict[str, str]) -> Dict[str, Dict]:
    """
    Detect game prompts from the full set of prompts and extract metadata.
    
    Args:
        prompts: Dictionary of all prompts
        
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
                "content": content
            }
    
    # Manually handle special cases for backward compatibility
    if "CAR_GAME_PROMPT" in prompts and "CAR_GAME_PROMPT" not in game_prompts:
        game_prompts["CAR_GAME_PROMPT"] = {
            "game_id": "CarGame",
            "name": "Spanish Road Trip",
            "description": "Take a magical car journey and learn Spanish words for colors, animals, and objects!",
            "content": prompts["CAR_GAME_PROMPT"]
        }
    
    if "ISLAND_GAME_PROMPT" in prompts and "ISLAND_GAME_PROMPT" not in game_prompts:
        game_prompts["ISLAND_GAME_PROMPT"] = {
            "game_id": "IslandGame",
            "name": "Pirate Island Adventure",
            "description": "Sail between islands as a pirate and discover Spanish treasure words!",
            "content": prompts["ISLAND_GAME_PROMPT"]
        }
    
    return game_prompts

# Function to create game agents from detected game prompts
def create_game_agents(game_prompts: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Create game agents dynamically based on detected game prompts.
    
    Args:
        game_prompts: Dictionary of game prompts with metadata
        
    Returns:
        Dictionary of available agents with their info.
    """
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
            tools=[track_vocabulary]
        )
        
        # Add to available agents
        available_agents[game_id] = {
            "name": name,
            "description": description,
            "agent": game_agent,
            "prompt_id": prompt_id
        }
        
        log_debug(f"Created agent for game: {game_id} ({name})")
    
    return available_agents

# Detect game prompts and extract metadata
game_prompts = detect_game_prompts(all_prompts)

# Create agents for each detected game
AVAILABLE_AGENTS = create_game_agents(game_prompts)

# Access the choice layer prompt
CHOICE_LAYER_PROMPT = all_prompts.get("CHOICE_LAYER_PROMPT", "")

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

# Set up Firebase listener to detect new prompts
def setup_prompt_listener():
    """
    Set up a listener for changes to the Prompts collection.
    When a new prompt is added, update the available agents.
    """
    def on_snapshot(doc_snapshots, changes, read_time):
        for change in changes:
            if change.type.name == 'ADDED':
                prompt_id = change.document.id
                prompt_content = change.document.to_dict().get("content", "")
                
                log_debug(f"New prompt detected: {prompt_id}")
                
                # Check if it's a game prompt
                if "_GAME_PROMPT" in prompt_id:
                    # Update all_prompts
                    all_prompts[prompt_id] = prompt_content
                    
                    # Re-detect game prompts
                    new_game_prompts = detect_game_prompts({prompt_id: prompt_content})
                    
                    if new_game_prompts:
                        # Create new agent(s)
                        new_agents = create_game_agents(new_game_prompts)
                        
                        # Add to available agents
                        for game_id, agent_info in new_agents.items():
                            AVAILABLE_AGENTS[game_id] = agent_info
                            
                            # Add handoff to choice layer
                            agent_info["agent"].handoffs.append(choice_layer_agent)
                            
                            # Add handoff from choice layer to new agent
                            choice_layer_agent.handoffs.append(agent_info["agent"])
                        
                        # Update choice layer instructions with new available agents
                        choice_layer_agent.instructions = prompt_with_handoff_instructions(
                            CHOICE_LAYER_PROMPT + "\n\nAVAILABLE_AGENTS: " + 
                            ", ".join([f"{key}: {value['name']} - {value['description']}" 
                                      for key, value in AVAILABLE_AGENTS.items()])
                        )
                        
                        log_debug(f"Updated choice layer with new game: {game_id}")
    
    # Set up the listener
    prompts_ref = db.collection("Prompts")
    prompts_watch = prompts_ref.on_snapshot(on_snapshot)
    
    return prompts_watch  # Return the watch so it can be stopped if needed

# Start the prompt listener
prompt_watch = setup_prompt_listener()

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
        # Dynamically check all available games
        game_switch_detected = False
        
        for game_id, game_info in AVAILABLE_AGENTS.items():
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