import datetime
import json
import os
import re

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request, send_from_directory
from openai import OpenAI

from jarvis_settings import (
    apply_theme,
    delete_conversation,
    get_all_conversations,
    get_conversation_history,
    get_settings,
    get_themes,
    save_conversation,
    update_settings,
)

load_dotenv()

# Import the settings module


# ---- CONFIGURATION ----
OPENAI_API_KEY = os.getenv("API_KEY")  # Replace with your OpenAI API key
client = OpenAI(api_key=OPENAI_API_KEY)

# Set the path to your Obsidian vault
VAULT_PATH = "/Users/ryanstoffel/2ndBrain/"
print(f"Using Obsidian vault at: {VAULT_PATH}")

# Create data directory if it doesn't exist
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# Create conversation history directory
CONVERSATIONS_DIR = os.path.join(DATA_DIR, "conversations")
if not os.path.exists(CONVERSATIONS_DIR):
    os.makedirs(CONVERSATIONS_DIR)

# Initialize Flask app
app = Flask(__name__)

# Load settings on startup
global app_settings
app_settings = get_settings()

# --- HTML Templates ---
try:
    with open("templates/jarvis_ui.html", "r") as f:
        HTML_TEMPLATE = f.read()
except FileNotFoundError:
    print("Warning: templates/jarvis_ui.html not found. Using fallback template.")
    # Create templates directory if it doesn't exist
    templates_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "templates"
    )
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    # Create a minimal HTML template
    HTML_TEMPLATE = """<!DOCTYPE html>
    <html>
    <head>
        <title>Jarvis Assistant</title>
        <style>
            body { font-family: Arial, sans-serif; }
            .chat { height: 400px; overflow-y: auto; border: 1px solid #ccc; padding: 10px; margin-bottom: 10px; }
            .input-area { display: flex; }
            textarea { flex: 1; height: 50px; }
            button { margin-left: 10px; }
        </style>
    </head>
    <body>
        <h1>Jarvis Assistant</h1>
        <div id="chat"></div>
        <div class="input-area">
            <textarea id="input"></textarea>
            <button id="send">Send</button>
        </div>
        <script>
            const chatDiv = document.getElementById('chat');
            const inputField = document.getElementById('input');
            const sendButton = document.getElementById('send');
            
            function addMessage(role, text) {
                const div = document.createElement('div');
                div.innerHTML = `<strong>${role}:</strong> ${text}`;
                chatDiv.appendChild(div);
                chatDiv.scrollTop = chatDiv.scrollHeight;
            }
            
            function sendMessage() {
                const text = inputField.value.trim();
                if (!text) return;
                
                addMessage("You", text);
                inputField.value = "";
                
                fetch('/message', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text })
                })
                .then(response => response.json())
                .then(data => {
                    addMessage("Jarvis", data.response);
                })
                .catch(error => addMessage("Jarvis", "Error: " + error));
            }
            
            sendButton.addEventListener('click', sendMessage);
            inputField.addEventListener("keydown", function(event) {
                if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    sendMessage();
                }
            });
        </script>
    </body>
    </html>
    """
    # Save this template
    with open(os.path.join(templates_dir, "jarvis_ui.html"), "w") as f:
        f.write(HTML_TEMPLATE)


# --- Helper Functions for Folder Resolution ---
def find_folder(vault_path, folder_name):
    """
    Search the entire vault for a folder whose name contains the provided folder_name (case-insensitive).
    Returns the full path if found; otherwise, None.
    """
    folder_name_lower = folder_name.lower()
    for root, dirs, files in os.walk(vault_path):
        for d in dirs:
            if folder_name_lower in d.lower():
                return os.path.join(root, d)
    return None


def resolve_directory(vault_path, folder_path):
    """
    Given a folder path (which may include subfolders), first check the expected location.
    If not found, search the vault for a folder matching the last component (case-insensitive, partial match).
    """
    candidate = os.path.join(vault_path, folder_path)
    if os.path.isdir(candidate):
        return candidate
    folder_name = os.path.basename(folder_path)
    return find_folder(vault_path, folder_name)


def resolve_file_path(filename):
    """
    Resolves the absolute file path. If a folder is specified but not found at the expected location,
    attempts to locate the folder in the vault using partial, case-insensitive matching.
    Returns the full file path or None if the folder cannot be resolved.
    """
    folder_part = os.path.dirname(filename)
    base_name = os.path.basename(filename)
    if folder_part:
        resolved_folder = os.path.join(VAULT_PATH, folder_part)
        if not os.path.isdir(resolved_folder):
            resolved_folder = resolve_directory(VAULT_PATH, folder_part)
        if resolved_folder is None:
            return None
        return os.path.join(resolved_folder, base_name)
    else:
        return os.path.join(VAULT_PATH, filename)


def get_unique_filename(folder, base_name):
    """
    Returns a unique filename in the specified folder by appending a number if needed.
    """
    file_path = os.path.join(folder, base_name)
    if not os.path.exists(file_path):
        return file_path
    i = 1
    name, ext = os.path.splitext(base_name)
    while True:
        new_name = f"{name}_{i}{ext}"
        new_path = os.path.join(folder, new_name)
        if not os.path.exists(new_path):
            return new_path
        i += 1


def get_vault_structure():
    """
    Returns a JSON structure representing the Obsidian vault.
    """
    structure = []

    # Check if the vault path exists
    if not os.path.exists(VAULT_PATH):
        print(f"Warning: Vault path {VAULT_PATH} does not exist")
        return [{"error": f"Vault path {VAULT_PATH} not found"}]

    try:
        for root, dirs, files in os.walk(VAULT_PATH):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            path = os.path.relpath(root, VAULT_PATH)
            if path == ".":
                path = ""

            folder = {
                "path": path,
                "name": os.path.basename(root) or "Root",
                "files": [],
                "folders": [],
            }

            # Add markdown files
            for file in files:
                if file.endswith(".md"):
                    folder["files"].append(
                        {
                            "name": file,
                            "path": os.path.join(path, file) if path else file,
                        }
                    )

            # Add this folder to the structure
            parent_path = os.path.dirname(path)
            if parent_path:
                # Find parent folder in structure
                parent = None
                for f in structure:
                    if f["path"] == parent_path:
                        parent = f
                        break

                if parent:
                    parent["folders"].append(folder)
                else:
                    structure.append(folder)
            else:
                structure.append(folder)

        return structure
    except Exception as e:
        print(f"Error getting vault structure: {e}")
        return [{"error": str(e)}]


# --- Function for Generating Markdown Notes ---
def generate_note(source, followup=""):
    """
    Generates a detailed markdown note based on the provided source content.
    The note includes explanations, examples, and structured sections.
    If a followup is provided, it is appended as a continuation link at the end.
    """
    # Use the model from settings
    model = app_settings.get("preferred_model", "gpt-3.5-turbo")

    prompt = (
        "Generate a detailed markdown note based on the following content. "
        "Include clear explanations, examples, and structured sections (e.g., Overview, Characteristics, "
        "Implementation Example, and Code Explanation). "
        "Return the note in valid markdown format. "
        "If a followup is provided, append it as a continuation link at the end.\n\n"
        f"Content:\n{source}\n\n"
        f"Followup (if any): {followup}"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


# --- Command Parsing ---
def parse_command(user_input):
    """
    Parse natural language input into structured commands.
    """
    # Use the model from settings
    model = app_settings.get("preferred_model", "gpt-3.5-turbo")

    # The prompt supports a wide range of natural language variations for note generation.
    prompt = (
        "You are a command parser for a personal AI assistant named Jarvis integrated with an Obsidian vault. "
        "Interpret natural language commands to perform actions. The allowed actions are:\n"
        '- "search": search for files containing a keyword. Parameter: "keyword".\n'
        '- "read": read the contents of a file. Parameter: "filename".\n'
        '- "write": overwrite a file\'s content. Parameters: "filename" and "content".\n'
        '- "append": add content to the end of a file. Parameters: "filename" and "content".\n'
        '- "create": create a new file. Parameters: "filename" and "content".\n'
        '- "assignment": add an assignment to the todo list (append to "todo.md"). Parameter: "assignment".\n'
        '- "generate_note": generate detailed markdown notes based on provided content. Parameters: "source", "note_title", '
        'optionally "location", and optionally "followup".\n'
        '- "settings": user wants to adjust Jarvis settings. Parameter: "action" (e.g., "show", "theme").\n'
        '- "vault": explore or manage the vault structure. Parameter: "action" (e.g., "show", "browse").\n'
        '- "chat": for any other conversation. Parameter: "message".\n'
        'For note generation, trigger if the input includes phrases like "create markdown notes", "take notes", or "create a note". '
        'Extract the source content, desired note title (indicated by words like "called" or "titled"), the location (indicated by "save it in"), '
        'and an optional continuation (indicated by "continue on to").\n'
        "Examples:\n"
        'Input: "Show me my to do list"\n'
        'Output: {"action": "read", "filename": "todo.md"}\n'
        'Input: "Add test to my to do list"\n'
        'Output: {"action": "assignment", "assignment": "test"}\n'
        'Input: "Change theme to dark mode"\n'
        'Output: {"action": "settings", "setting": "theme", "value": "dark"}\n'
        'Input: "Show me my vault structure"\n'
        'Output: {"action": "vault", "action": "show"}\n'
        'Input: "Create markdown notes for this <pasted content> called 8.2 Selection Sort, save it in data structures, continue on to 8.4 Shell Sort"\n'
        'Output: {"action": "generate_note", "source": "<pasted content>", "note_title": "8.2 Selection Sort.md", "location": "data structures", "followup": "8.4 Shell Sort"}\n'
        'Input: "Hello, how are you?"\n'
        'Output: {"action": "chat", "message": "Hello, how are you?"}\n'
        "Now parse the following input:\n"
        f'"{user_input}"'
    )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


# --- Flask Routes ---
@app.route("/")
def index():
    """
    Render the main Jarvis UI.
    """
    # Apply the current theme from settings
    themed_template = apply_theme(HTML_TEMPLATE, app_settings.get("theme", "default"))
    return render_template_string(themed_template)


@app.route("/static/<path:path>")
def send_static(path):
    """
    Serve static files (JS, CSS, images).
    """
    return send_from_directory("static", path)


@app.route("/message", methods=["POST"])
def message():
    """
    Process incoming messages from the UI and return appropriate responses.
    """
    user_input = request.json.get("message", "").strip()
    conversation_id = request.json.get("conversation_id", None)

    # Convert natural language to a JSON command
    try:
        command_json = parse_command(user_input)
        command = json.loads(command_json)
    except Exception as e:
        print(f"Error parsing command: {str(e)}")
        command = {"action": "chat", "message": user_input}

    # Execute the command
    if command.get("action") == "search":
        result = search_files(VAULT_PATH, command.get("keyword", ""))

    elif command.get("action") == "read":
        result = read_file(command.get("filename", ""))

    elif command.get("action") == "write":
        result = write_file(command.get("filename", ""), command.get("content", ""))

    elif command.get("action") == "append":
        result = append_file(command.get("filename", ""), command.get("content", ""))

    elif command.get("action") == "create":
        result = create_file(command.get("filename", ""), command.get("content", ""))

    elif command.get("action") == "assignment":
        result = add_assignment(command.get("assignment", ""))

    elif command.get("action") == "generate_note":
        source = command.get("source", "")
        followup = command.get("followup", "")
        note_title = command.get("note_title", "generated_note.md")
        location = command.get("location", "")

        result = handle_note_generation(source, followup, note_title, location)

    elif command.get("action") == "settings":
        global app_settings
        setting = command.get("setting", "show")
        value = command.get("value", None)

        if setting == "show":
            result = f"Current Settings:\n\n" + json.dumps(app_settings, indent=2)
        elif setting == "theme":
            # Update theme
            app_settings["theme"] = value
            update_settings(app_settings)
            result = f"Theme updated to {value}. Refresh the page to see changes."
        elif setting == "model":
            # Update preferred model
            app_settings["preferred_model"] = value
            update_settings(app_settings)
            result = f"Preferred model updated to {value}."
        elif setting == "themes":
            # List available themes
            themes = get_themes()
            result = "Available themes:\n" + "\n".join(
                [f"- {theme}" for theme in themes]
            )
        else:
            result = "Unknown settings command."

    elif command.get("action") == "vault":
        action = command.get("action", "show")

        if action == "show":
            structure = get_vault_structure()
            result = "Vault Structure:\n" + json.dumps(structure, indent=2)
        else:
            result = "Unknown vault command."

    elif command.get("action") == "chat":
        try:
            # Use the model from settings
            model = app_settings.get("preferred_model", "gpt-3.5-turbo")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are Jarvis, an advanced AI assistant integrated with "
                        "an Obsidian vault. You help users manage their knowledge base, "
                        "create notes, and find information. Respond in a helpful, friendly manner.",
                    },
                    {"role": "user", "content": command.get("message", user_input)},
                ],
            )
            result = response.choices[0].message.content.strip()
        except Exception as e:
            result = f"Error calling OpenAI API: {str(e)}"

    else:
        result = "Invalid command."

    # Save the message to conversation history if a conversation ID is provided
    if conversation_id:
        save_conversation(conversation_id, user_input, result)

    return jsonify(
        {
            "response": result,
            "conversation_id": conversation_id
            or f"conv_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        }
    )


@app.route("/settings", methods=["GET", "POST"])
def settings_route():
    """
    Handle settings requests.
    """
    global app_settings

    if request.method == "GET":
        return jsonify(app_settings)

    elif request.method == "POST":
        new_settings = request.json
        app_settings.update(new_settings)
        update_settings(app_settings)
        return jsonify({"status": "success", "settings": app_settings})


@app.route("/conversations", methods=["GET", "POST", "DELETE"])
def conversations_route():
    """
    Handle conversation history requests.
    """
    if request.method == "GET":
        conversation_id = request.args.get("id", None)

        if conversation_id:
            # Get a specific conversation
            conversation = get_conversation_history(conversation_id)
            return jsonify(conversation)
        else:
            # Get all conversations
            conversations = get_all_conversations()
            return jsonify(conversations)

    elif request.method == "DELETE":
        conversation_id = request.json.get("id", None)

        if conversation_id:
            # Delete a specific conversation
            delete_conversation(conversation_id)
            return jsonify(
                {
                    "status": "success",
                    "message": f"Conversation {conversation_id} deleted",
                }
            )

        return jsonify({"status": "error", "message": "No conversation ID provided"})


def handle_note_generation(source, followup, note_title, location):
    """
    Handle the generation and saving of notes.
    """
    note_content = generate_note(source, followup)

    if not note_title.lower().endswith(".md"):
        note_title += ".md"

    if location:
        folder = resolve_directory(VAULT_PATH, location)
        if folder is None:
            return f"Folder '{location}' not found in vault."

        unique_file_path = get_unique_filename(folder, note_title)
        try:
            with open(unique_file_path, "w", encoding="utf-8") as f:
                f.write(note_content)

            rel_path = os.path.relpath(unique_file_path, VAULT_PATH)
            result = f"Note saved as {rel_path}."

            # Handle numbering and linking if the note title has a numeric format (e.g., 8.2)
            match = re.match(r"(\d+)\.(\d+)", note_title)
            if match:
                result += handle_note_linking(folder, note_title, match)

            # Handle followup note creation if specified
            if followup:
                result += handle_followup_note(
                    folder, note_title, followup, unique_file_path
                )

            return result

        except Exception as e:
            return f"Error saving note: {e}"
    else:
        return note_content


def handle_note_linking(folder, note_title, match):
    """
    Handle linking from previous notes to the current note.
    """
    try:
        major, minor = match.group(1), match.group(2)
        prev_minor = int(minor) - 1

        if prev_minor >= 0:
            prev_prefix = f"{major}.{prev_minor}"
            found_prev = False

            for file in os.listdir(folder):
                if file.lower().startswith(
                    prev_prefix.lower()
                ) and file.lower().endswith(".md"):
                    prev_file_path = os.path.join(folder, file)
                    link_text = f"\n\n[[{note_title.rstrip('.md').strip()}]]"

                    with open(prev_file_path, "a", encoding="utf-8") as pf:
                        pf.write(link_text)

                    found_prev = True
                    return f" Link added in {file} to {note_title}."

            if not found_prev:
                return " No previous note found to link from."
        else:
            return " Invalid note numbering for linking."

    except Exception as e:
        return f" Error linking note: {e}"


def handle_followup_note(folder, note_title, followup, current_file_path):
    """
    Create a followup note and link to it from the current note.
    """
    try:
        followup_title = followup.strip()

        # Remove any surrounding [[ ]] if present
        if followup_title.startswith("[[") and followup_title.endswith("]]"):
            followup_title = followup_title[2:-2].strip()

        if not followup_title.lower().endswith(".md"):
            followup_title += ".md"

        followup_file_path = get_unique_filename(folder, followup_title)

        # Create the followup note with a title
        with open(followup_file_path, "w", encoding="utf-8") as ff:
            ff.write(f"# {followup_title[:-3]}\n\n")

        # Add a link to the followup note in the current note
        with open(current_file_path, "a", encoding="utf-8") as mf:
            mf.write(f"\n\n[[{followup_title[:-3].strip()}]]")

        rel_followup = os.path.relpath(followup_file_path, VAULT_PATH)
        return f" Followup note created as {rel_followup}."

    except Exception as e:
        return f" Error creating followup note: {e}"


# --- File Operation Functions ---
def search_files(vault_path, keyword):
    """
    Search for files containing a specific keyword.
    """
    if not os.path.exists(vault_path):
        return f"Error: Vault path {vault_path} does not exist"

    matches = []
    for root, dirs, files in os.walk(vault_path):
        for file in files:
            if file.endswith(".md"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if keyword.lower() in content.lower():
                        matches.append(os.path.relpath(file_path, vault_path))
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")

    if matches:
        return "I found matches in these files:\n- " + "\n- ".join(matches)
    else:
        return "No matches found for your search."


def add_assignment(assignment):
    """
    Add an assignment to the todo list.
    """
    todo_file = os.path.join(VAULT_PATH, "todo.md")

    # Check if the vault path exists
    if not os.path.exists(VAULT_PATH):
        return f"Error: Vault path {VAULT_PATH} does not exist"

    try:
        # Create todo.md if it doesn't exist
        if not os.path.exists(todo_file):
            with open(todo_file, "w", encoding="utf-8") as f:
                f.write("# To-Do List\n\n")

        with open(todo_file, "a", encoding="utf-8") as f:
            f.write(f"\n- [ ] {assignment}")
        return f'I\'ve added "{assignment}" to your to-do list.'
    except Exception as e:
        print(f"Error writing to {todo_file}: {e}")
        return f"I encountered an error adding your assignment: {e}"


def read_file(filename):
    """
    Read and return the contents of a file.
    """
    # Check if the vault path exists
    if not os.path.exists(VAULT_PATH):
        return f"Error: Vault path {VAULT_PATH} does not exist"

    file_path = resolve_file_path(filename)
    if file_path is None or not os.path.isfile(file_path):
        return f"I couldn't find {filename} in your vault. Available files: " + str(
            list_files()
        )

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return f"Here's the content of {filename}:\n\n{content}"
    except Exception as e:
        return f"Error reading {filename}: {e}"


def list_files(max_files=10):
    """
    List some files in the vault for troubleshooting.
    """
    files = []
    try:
        for root, _, filenames in os.walk(VAULT_PATH):
            for filename in filenames:
                if filename.endswith(".md"):
                    rel_path = os.path.relpath(os.path.join(root, filename), VAULT_PATH)
                    files.append(rel_path)
                    if len(files) >= max_files:
                        break
            if len(files) >= max_files:
                break
        return files
    except Exception as e:
        return [f"Error listing files: {e}"]


def write_file(filename, content):
    """
    Write content to a file.
    """
    # Check if the vault path exists
    if not os.path.exists(VAULT_PATH):
        return f"Error: Vault path {VAULT_PATH} does not exist"

    file_path = resolve_file_path(filename)
    if file_path is None:
        # Try to create the file in the root of the vault
        file_path = os.path.join(VAULT_PATH, filename)

    try:
        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"I've updated {filename} with your new content."
    except Exception as e:
        return f"Error writing to {filename}: {e}"


def append_file(filename, content):
    """
    Append content to the end of a file.
    """
    # Check if the vault path exists
    if not os.path.exists(VAULT_PATH):
        return f"Error: Vault path {VAULT_PATH} does not exist"

    file_path = resolve_file_path(filename)
    if file_path is None:
        # Try to create the file in the root of the vault
        file_path = os.path.join(VAULT_PATH, filename)

        # Create it first if it doesn't exist
        if not os.path.exists(file_path):
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("")
            except Exception as e:
                return f"Error creating file {filename}: {e}"

    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write("\n" + content)
        return f"I've appended your content to {filename}."
    except Exception as e:
        return f"Error appending to {filename}: {e}"


def create_file(filename, content):
    """
    Create a new file with the specified content.
    """
    # Check if the vault path exists
    if not os.path.exists(VAULT_PATH):
        return f"Error: Vault path {VAULT_PATH} does not exist"

    file_path = resolve_file_path(filename)
    if file_path is None:
        # Try to create the file in the root of the vault
        file_path = os.path.join(VAULT_PATH, filename)

    if os.path.exists(file_path):
        return f"The file {filename} already exists. Use 'write' to update it instead."

    try:
        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"I've created {filename} with your content."
    except Exception as e:
        return f"Error creating file {filename}: {e}"


@app.route("/test-vault", methods=["GET"])
def test_vault():
    """
    Test access to the Obsidian vault.
    """
    if not os.path.exists(VAULT_PATH):
        return jsonify(
            {
                "status": "error",
                "message": f"Vault path '{VAULT_PATH}' does not exist. Please check the configuration.",
            }
        )

    # List some files in the vault
    files = list_files(max_files=10)

    return jsonify(
        {
            "status": "success",
            "message": f"Successfully accessed vault at {VAULT_PATH}",
            "vault_path": VAULT_PATH,
            "sample_files": files,
        }
    )


if __name__ == "__main__":
    print(f"Starting Jarvis with Obsidian vault at: {VAULT_PATH}")

    # Verify vault access on startup
    if not os.path.exists(VAULT_PATH):
        print(
            f"Warning: Vault path '{VAULT_PATH}' does not exist or is not accessible."
        )
        print("Please check the VAULT_PATH configuration in app.py")
    else:
        print(f"Vault access OK. Found {len(list_files(100))} markdown files.")

    app.run(debug=True)
