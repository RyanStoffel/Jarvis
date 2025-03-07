"""
Jarvis Settings Module

This module handles settings management for the Jarvis assistant, including:
- Theme management (light, dark, custom themes)
- User preferences
- Conversation history storage and retrieval
"""

import datetime
import glob
import json
import os

# Create data directory if it doesn't exist
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
CONVERSATIONS_DIR = os.path.join(DATA_DIR, "conversations")

# Ensure data directories exist
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
if not os.path.exists(CONVERSATIONS_DIR):
    os.makedirs(CONVERSATIONS_DIR)

# Default settings
DEFAULT_SETTINGS = {
    "theme": "default",
    "preferred_model": "gpt-3.5-turbo",
    "typing_speed": "medium",  # slow, medium, fast
    "save_conversations": True,
    "max_conversation_history": 50,
    "auto_save_interval": 5,  # minutes
    "voice_enabled": False,
    "ui_options": {
        "show_timestamps": True,
        "show_model_info": True,
        "compact_mode": False,
        "font_size": "medium",  # small, medium, large
    },
}

# Available themes
THEMES = {
    "default": {
        "primary_color": "#3a7bd5",
        "secondary_color": "#2c3e50",
        "bg_color": "#f8f9fa",
        "sidebar_color": "#1a202c",
        "user_bubble": "#3a7bd5",
        "assistant_bubble": "#f1f5f9",
    },
    "dark": {
        "primary_color": "#0ea5e9",
        "secondary_color": "#f1f5f9",
        "bg_color": "#111827",
        "sidebar_color": "#0f172a",
        "user_bubble": "#0ea5e9",
        "assistant_bubble": "#1e293b",
    },
    "forest": {
        "primary_color": "#22c55e",
        "secondary_color": "#f1f5f9",
        "bg_color": "#f8fafc",
        "sidebar_color": "#064e3b",
        "user_bubble": "#22c55e",
        "assistant_bubble": "#ecfdf5",
    },
    "sunset": {
        "primary_color": "#f97316",
        "secondary_color": "#431407",
        "bg_color": "#f8fafc",
        "sidebar_color": "#7c2d12",
        "user_bubble": "#f97316",
        "assistant_bubble": "#fff7ed",
    },
    "midnight": {
        "primary_color": "#8b5cf6",
        "secondary_color": "#f8fafc",
        "bg_color": "#020617",
        "sidebar_color": "#1e1b4b",
        "user_bubble": "#8b5cf6",
        "assistant_bubble": "#1e1b4b",
    },
}


def get_settings():
    """
    Load settings from the settings file, or create it with defaults if it doesn't exist.
    """
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=4)
        return DEFAULT_SETTINGS

    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
        return settings
    except Exception as e:
        print(f"Error loading settings: {e}")
        return DEFAULT_SETTINGS


def update_settings(new_settings):
    """
    Update settings in the settings file.
    """
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(new_settings, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False


def get_themes():
    """
    Return a list of available themes.
    """
    return list(THEMES.keys())


def apply_theme(html_template, theme_name="default"):
    """
    Apply a theme to the HTML template by replacing CSS variables.
    """
    if theme_name not in THEMES:
        theme_name = "default"

    theme = THEMES[theme_name]

    # Replace CSS variables in the template
    themed_html = html_template
    for key, value in theme.items():
        # Convert key from snake_case to kebab-case for CSS
        css_key = key.replace("_", "-")
        themed_html = themed_html.replace(f"var(--{css_key})", value)

    return themed_html


def save_conversation(conversation_id, user_message, assistant_response):
    """
    Save a message to the conversation history.
    """
    conversation_file = os.path.join(CONVERSATIONS_DIR, f"{conversation_id}.json")

    # Create or load existing conversation
    if os.path.exists(conversation_file):
        try:
            with open(conversation_file, "r") as f:
                conversation = json.load(f)
        except Exception as e:
            print(f"Error loading conversation: {e}")
            conversation = {"messages": []}
    else:
        conversation = {"messages": []}

    # Add timestamp
    timestamp = datetime.datetime.now().isoformat()

    # Add messages to conversation
    conversation["messages"].append(
        {"role": "user", "content": user_message, "timestamp": timestamp}
    )

    conversation["messages"].append(
        {"role": "assistant", "content": assistant_response, "timestamp": timestamp}
    )

    # Update conversation metadata
    conversation["id"] = conversation_id
    conversation["last_updated"] = timestamp
    conversation["title"] = conversation.get(
        "title", user_message[:50] + "..." if len(user_message) > 50 else user_message
    )

    # Save conversation
    try:
        with open(conversation_file, "w") as f:
            json.dump(conversation, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving conversation: {e}")
        return False


def get_conversation_history(conversation_id):
    """
    Get conversation history by ID.
    """
    conversation_file = os.path.join(CONVERSATIONS_DIR, f"{conversation_id}.json")

    if not os.path.exists(conversation_file):
        return {
            "id": conversation_id,
            "messages": [],
            "error": "Conversation not found",
        }

    try:
        with open(conversation_file, "r") as f:
            conversation = json.load(f)
        return conversation
    except Exception as e:
        print(f"Error loading conversation: {e}")
        return {"id": conversation_id, "messages": [], "error": str(e)}


def delete_conversation(conversation_id):
    """
    Delete a conversation by ID.
    """
    conversation_file = os.path.join(CONVERSATIONS_DIR, f"{conversation_id}.json")

    if not os.path.exists(conversation_file):
        return False

    try:
        os.remove(conversation_file)
        return True
    except Exception as e:
        print(f"Error deleting conversation: {e}")
        return False


def get_all_conversations():
    """
    Get a list of all conversations with metadata.
    """
    conversations = []

    conversation_files = glob.glob(os.path.join(CONVERSATIONS_DIR, "*.json"))
    for file in conversation_files:
        try:
            with open(file, "r") as f:
                conversation = json.load(f)

            # Extract metadata for the list view
            conversations.append(
                {
                    "id": conversation.get(
                        "id", os.path.basename(file).replace(".json", "")
                    ),
                    "title": conversation.get("title", "Untitled Conversation"),
                    "last_updated": conversation.get("last_updated", ""),
                    "message_count": len(conversation.get("messages", [])),
                    "preview": (
                        conversation.get("messages", [{}])[0].get("content", "")[:100]
                        if conversation.get("messages")
                        else ""
                    ),
                }
            )
        except Exception as e:
            print(f"Error loading conversation {file}: {e}")

    # Sort by last updated, newest first
    conversations.sort(key=lambda x: x.get("last_updated", ""), reverse=True)

    return conversations
