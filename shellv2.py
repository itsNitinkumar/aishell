import os
import threading
import subprocess
import time
import json
import glob
import re
from pathlib import Path
from typing import Dict, List, Optional
from openai import OpenAI, APIConnectionError
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from dotenv import load_dotenv
import platform

load_dotenv()
COMMAND_HISTORY_LIMIT = 10 
print("Using OpenRouter API key:", os.getenv("deepseek_api")[:8] + "..." if os.getenv("deepseek_api") else "Not found")

FALLBACK_MODEL = "openai/gpt-3.5-turbo:free"

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("deepseek_api"),
    timeout=5.0,
    default_headers={
        "HTTP-Referer": "https://openrouter.ai/",  # Required for OpenRouter
    }
)

# Test the API connection
def test_api_connection():
    try:
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'API connection successful'"}
            ],
            max_tokens=10
        )
        print("API Test Response:", completion.choices[0].message.content if completion.choices else "No response")
        return True
    except Exception as e:
        print("API Test Error:", str(e))
        return False

# Call this at startup
if test_api_connection():
    print("OpenRouter API connection successful")
else:
    print("OpenRouter API connection failed")

#something 


# Global state management
command_history = []
current_suggestion = ""
suggestion_lock = threading.Lock()
last_request_time = 0
command_context = []  # Store command outputs and context

def get_ai_suggestion(user_input):
    """Get command completion suggestions from the AI model."""
    try:
        if len(user_input.strip()) < 3:
            return ""

        # print(f"Requesting suggestion for: {user_input}")  # Debug print
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {
                    "role": "system", 
                    "content": "You are a command-line expert. Complete the given command. Respond ONLY with the completed command, no explanations. Focus on common commands like git, docker, npm, pip, cat, touch, sudo, ls, cd, mkdir, rm, cp, mv, pwd, echo, grep, chmod, chown, ps, kill, top, man, whoami, ifconfig, ping, curl, wget, tar, unzip, zip, ssh, scp, find, history, clear, alias, df, du, nano, vi, apt, yum, dnf, pacman, service, systemctl, hostname, env, export, date, time, python, node, java, javac, gcc, make, htop, tmux, screen, netstat, traceroute, dig, npm, npx, pip3, virtualenv, conda, which, whereis, uname, lsb_release  etc . look out for other commands too",
                },
                {
                    "role": "user", 
                    "content": f"Complete this command: {user_input}"
                }
            ],
            max_tokens=50,
            temperature=0.1
        )
        
        if not completion or not completion.choices:
            return ""
            
        suggestion = completion.choices[0].message.content.strip()
        suggestion = suggestion.split("\n")[0].split("#")[0].strip().strip('"').strip("'")
        
        # Ensure suggestion starts with user input
        if suggestion and not suggestion.startswith(user_input):
            suggestion = user_input + suggestion
        elif suggestion == user_input:
            suggestion += " "
        
        # print(f"Got suggestion: {suggestion}")  # Debug print
        return suggestion
        
    except Exception as e:
        print(f"[Error] AI suggestion failed: {str(e)}")
        return ""

def get_shell_command(query):
    """Convert natural language query to shell command with context awareness"""
    try:
        # Build context from recent commands
        context_str = ""
        if command_context:
            context_str = "\n".join([
                f"Previous command: {ctx['command']}\nOutput: {ctx['output']}\n"
                for ctx in command_context[-COMMAND_HISTORY_LIMIT:]
            ])
        else:
            context_str = "No previous commands"
            
        completion = client.chat.completions.create(
            model="openai/gpt-3.5-turbo:free",
            messages=[
                {
                    "role": "system", 
                    "content": f"""You are a command-line expert. Convert natural language queries into appropriate shell commands.
                    Consider the context of previous commands when suggesting new ones.
                    For file operations, prefer simple commands like touch, echo, mkdir, etc.
                    You have access to the last {COMMAND_HISTORY_LIMIT} commands and their outputs for context.
                    Respond ONLY with the command, no explanations or additional text."""
                },
                {
                    "role": "user", 
                    "content": f"Recent command history:\n{context_str}\n\nConvert this to a shell command: {query}"
                }
            ],
            max_tokens=50,
            temperature=0.1
        )
        
        if not completion or not completion.choices:
            print(f"API Response: {completion}")  # Debug print
            return None
            
        command = completion.choices[0].message.content.strip()
        command = command.split("\n")[0].split("#")[0].strip().strip('"').strip("'")
        
        print(f"Generated command: {command}")  # Debug print
        return command
        
    except Exception as e:
        print(f"Error in get_shell_command: {type(e).__name__}: {str(e)}")
        return None
def fetch_suggestion_async(text, session):
    """Fetch suggestions asynchronously to avoid blocking the UI."""
    global current_suggestion
    
    if len(text.strip()) < 2:
        with suggestion_lock:
            current_suggestion = ""
        return
        
    suggestion = get_ai_suggestion(text)
    
    with suggestion_lock:
        current_suggestion = suggestion
    
    # Force a refresh of the UI
    if session.app:
        session.app.invalidate()

class AIAutoSuggest(AutoSuggest):
    """Custom AutoSuggest class for AI-powered command completion."""
    def get_suggestion(self, _buffer, document):
        typed_text = document.text
        if not typed_text.strip():
            return None
            
        with suggestion_lock:
            suggestion = current_suggestion
            
        if suggestion and suggestion.startswith(typed_text) and suggestion != typed_text:
            return Suggestion(suggestion[len(typed_text):])
        return None

def is_destructive_command(command: str) -> tuple[bool, str, list]:
    """
    Analyze if a command is potentially destructive using both predefined patterns and AI analysis
    Returns: (is_destructive, reason, affected_files)
    """
    # First check hardcoded patterns
    destructive_patterns = {
        r'\brm\s+-[rf]*\b': {'reason': 'File/directory deletion', 'severity': 'high', 'type': 'filesystem'},
        r'\bsystemctl\s+(stop|restart|disable)\b': {'reason': 'Service interruption', 'severity': 'high', 'type': 'service'},
        r'\bservice\s+\w+\s+(stop|restart)\b': {'reason': 'Service interruption', 'severity': 'high', 'type': 'service'},
        r'\bgit\s+reset\s+--hard\b': {'reason': 'Hard reset of git changes', 'severity': 'high', 'type': 'git'},
        r'\bgit\s+clean\s+-[fd]+\b': {'reason': 'Removal of untracked files', 'severity': 'medium', 'type': 'git'},
        r'\bgit\s+push\s+(-f|--force)\b': {'reason': 'Force push to repository', 'severity': 'high', 'type': 'git'},
        r'\bgit\s+revert\b': {'reason': 'Reverting commits', 'severity': 'medium', 'type': 'git'},
        r'\bdd\b': {'reason': 'Direct disk operations', 'severity': 'critical', 'type': 'system'},
        r'\bformat\b': {'reason': 'Formatting operations', 'severity': 'critical', 'type': 'system'},
        r'[>|2]>\s*/dev': {'reason': 'Device file operations', 'severity': 'high', 'type': 'system'},
        r'\bchmod\s+-[R]*\b': {'reason': 'Recursive permission changes', 'severity': 'medium', 'type': 'filesystem'},
        r'\bsudo\s+': {'reason': 'Administrative privileges required', 'severity': 'medium', 'type': 'system'}
    }
    
    affected_files = []
    
    # Check predefined patterns first
    for pattern, info in destructive_patterns.items():
        if re.search(pattern, command, re.IGNORECASE):
            # Existing logic for getting affected files
            if 'rm' in command:
                try:
                    parts = command.split()
                    path_index = next(i for i, part in enumerate(parts) 
                                   if not part.startswith('-') and part != 'rm')
                    path = parts[path_index]
                    expanded_paths = glob.glob(path)
                    if not expanded_paths:
                        expanded_paths = [path]
                    
                    for expanded_path in expanded_paths:
                        if os.path.exists(expanded_path):
                            if os.path.isfile(expanded_path):
                                affected_files.append(expanded_path)
                            else:
                                for root, dirs, files in os.walk(expanded_path):
                                    if files:
                                        affected_files.append(root + '/')
                                    for file in files:
                                        affected_files.append(os.path.join(root, file))
                                        
                except Exception as e:
                    affected_files = [f'Unable to determine affected files: {str(e)}']
            
            elif command.startswith('git'):
                # Existing git file detection logic
                try:
                    if 'reset' in command or 'clean' in command:
                        result = subprocess.run(
                            'git status --porcelain',
                            shell=True, capture_output=True, text=True
                        )
                        affected_files = [line[3:] for line in result.stdout.splitlines() if line]
                    elif 'revert' in command:
                        commit_hash = command.split()[-1]
                        result = subprocess.run(
                            f'git show --name-only {commit_hash}',
                            shell=True, capture_output=True, text=True
                        )
                        affected_files = [line for line in result.stdout.splitlines() 
                                        if line.strip() and not line.startswith('commit')]
                except Exception as e:
                    affected_files = [f'Unable to determine affected git files: {str(e)}']
            
            return True, info['reason'], affected_files

    # If not found in predefined patterns, use AI to analyze
    try:
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """You are a command-line security expert. Analyze the given command and determine if it's potentially destructive.
                    Consider operations that could:
                    - Delete or modify files/directories
                    - Affect system configuration
                    - Impact system stability
                    - Modify important settings
                    - Require elevated privileges
                    - Have network-wide effects
                    - Be irreversible
                    
                    Respond in JSON format:
                    {
                        "is_destructive": true/false,
                        "reason": "Brief explanation of why it's considered destructive",
                        "severity": "low/medium/high/critical",
                        "type": "filesystem/system/network/database/etc"
                    }"""
                },
                {
                    "role": "user",
                    "content": f"Analyze this command: {command}"
                }
            ],
            max_tokens=150,
            temperature=0.1
        )
        
        analysis = json.loads(completion.choices[0].message.content)
        
        if analysis['is_destructive']:
            return True, f"{analysis['reason']} (Severity: {analysis['severity']}, Type: {analysis['type']})", affected_files
    
    except Exception as e:
        print(f"AI analysis failed: {str(e)}")
        # Fall back to safe mode - assume potentially destructive if AI fails
        return True, "Unable to fully analyze command safety", []
    
    return False, '', []

def execute_command(command: str) -> bool:
    """Execute a shell command with proper shell activation handling"""
    try:
        # Check for destructive operations
        is_destructive, reason, affected_files = is_destructive_command(command)
        
        # Handle cd command specially
        if command.strip().startswith('cd'):
            try:
                directory = command.strip()[2:].strip() or os.path.expanduser("~")
                if not os.path.exists(directory):
                    print(f"Directory does not exist: {directory}")
                    return False
                os.chdir(directory)
                # Store successful cd command in context
                command_context.append({
                    'command': command,
                    'output': f"Changed directory to: {os.getcwd()}",
                    'timestamp': time.time()
                })
                if len(command_context) > COMMAND_HISTORY_LIMIT:
                    command_context.pop(0)
                return True
            except Exception as e:
                print(f"Error changing directory: {str(e)}")
                return False

        # For history command, use our internal command_context
        if command.strip() == 'history':
            output = "\n".join([f"{i+1}  {ctx['command']}" 
                              for i, ctx in enumerate(command_context)])
            print(output)
            return True
            
        # Regular command execution
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        output = result.stdout if result.stdout else result.stderr
        
        # Print the output
        if output:
            print(output.strip())
            
        # Store command and its output in context
        command_context.append({
            'command': command,
            'output': output,
            'timestamp': time.time()
        })
        
        # Keep only last N commands for context
        if len(command_context) > COMMAND_HISTORY_LIMIT:
            command_context.pop(0)
            
        return result.returncode == 0
        
    except Exception as e:
        print(f"Error executing command: {str(e)}")
        return False

def detect_package_manager():
    """Detect the system's package manager"""
    package_managers = {
        'apt-get': 'which apt-get',
        'yum': 'which yum',
        'dnf': 'which dnf',
        'pacman': 'which pacman',
        'brew': 'which brew'
    }
    
    for pm, check_cmd in package_managers.items():
        try:
            subprocess.run(check_cmd, shell=True, check=True, capture_output=True)
            return pm
        except subprocess.CalledProcessError:
            continue
    return None

def get_setup_commands(setup_request: str) -> List[Dict]:
    """Get setup commands with context awareness"""
    try:
        # Build context from recent commands, handle empty context
        context_str = ""
        if command_context:
            context_str = "\n".join([
                f"Previous command: {ctx['command']}\nOutput: {ctx['output']}\n"
                for ctx in command_context
            ])
        else:
            context_str = "No previous commands"
        
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """You are a command-line expert. Generate appropriate commands based on the request and previous command context.
                    Previous commands and their outputs are provided for context.
                    ALWAYS return response in this exact JSON format:
                    [
                        {
                            "description": "Brief description of what this step does",
                            "operation": "command",
                            "content": "the actual command to run"
                        }
                    ]
                    For simple commands, return just one step. Use common Unix/Linux commands."""
                },
                {
                    "role": "user",
                    "content": f"Recent command history:\n{context_str}\n\nRequest: {setup_request}"
                }
            ],
            max_tokens=1000,
            temperature=0.1
        )
        
        response = completion.choices[0].message.content.strip()
        
        # Try to extract JSON if it's wrapped in other text
        try:
            # Find JSON array in the response
            json_start = response.find('[')
            json_end = response.rfind(']') + 1
            if json_start >= 0 and json_end > json_start:
                response = response[json_start:json_end]
            
            steps = json.loads(response)
            
            # Validate the structure of each step
            validated_steps = []
            for step in steps:
                if not isinstance(step, dict):
                    continue
                if 'operation' not in step or 'content' not in step:
                    continue
                if step['operation'] not in ['command', 'file_create', 'file_edit']:
                    step['operation'] = 'command'
                if 'description' not in step:
                    step['description'] = step['content']
                validated_steps.append(step)
            
            return validated_steps if validated_steps else [{
                "description": "List files in current directory",
                "operation": "command",
                "content": "ls -la"
            }]
            
        except json.JSONDecodeError:
            # If JSON parsing fails, create a simple command step
            return [{
                "description": "Execute the following command",
                "operation": "command",
                "content": response.strip('`').strip()
            }]
        
    except Exception as e:
        print(f"Error generating setup commands: {str(e)}")
        # Provide a fallback command instead of returning empty list
        return [{
            "description": "List files in current directory",
            "operation": "command",
            "content": "ls -la"
        }]

def execute_setup_step(step: Dict) -> bool:
    """Execute a single setup step"""
    try:
        print(f"\nStep: {step['description']}")
        
        if step['operation'] == 'command':
            command = step['content']
            requires_sudo = step.get('requires_sudo', False)
            
            if requires_sudo:
                print("Note: This step requires administrative privileges")
            
            print(f"Command to execute: {command}")
            confirm = input("Execute this command? [y/N] ")
            
            if confirm.lower() == 'y':
                try:
                    return execute_command(command)
                except Exception as e:
                    print(f"Command failed: {str(e)}")
                    return False
                
        elif step['operation'] in ['file_create', 'file_edit']:
            path = step['path'].strip()
            if not path:
                print("Error: File path is empty")
                return False
                
            print(f"File: {path}")
            print("Content:")
            print("---")
            print(step['content'])
            print("---")
            
            confirm = input(f"{'Create' if step['operation'] == 'file_create' else 'Edit'} this file? [y/N] ")
            if confirm.lower() == 'y':
                try:
                    directory = os.path.dirname(path)
                    if directory:
                        os.makedirs(directory, exist_ok=True)
                    
                    mode = 'w' if step['operation'] == 'file_create' else 'a'
                    with open(path, mode) as f:
                        f.write(step['content'])
                    print(f"Successfully {'created' if step['operation'] == 'file_create' else 'edited'} {path}")
                    return True
                except Exception as e:
                    print(f"Error {'creating' if step['operation'] == 'file_create' else 'editing'} file: {str(e)}")
                    return False
            return False  # User declined
            
        print(f"Unknown operation: {step['operation']}")
        return False
        
    except Exception as e:
        print(f"Error executing step: {str(e)}")
        return False

def handle_setup_request(request: str):
    """Handle a setup wizard request"""
    print(f"\nAnalyzing setup request: {request}")
    steps = get_setup_commands(request)
    
    if not steps:
        print("Could not generate setup steps. Please try rephrasing your request.")
        return
        
    print("\nProposed setup steps:")
    for i, step in enumerate(steps, 1):
        print(f"\n{i}. {step['description']}")
        print(f"   Operation: {step['operation']}")
        if 'path' in step:
            print(f"   File: {step['path']}")
            
    confirm = input("\nWould you like to proceed with these steps? [y/N] ")
    if confirm.lower() != 'y':
        return
        
    for i, step in enumerate(steps, 1):
        print(f"\nExecuting step {i}/{len(steps)}")
        if not execute_setup_step(step):
            print("Step failed. Stopping setup.")
            confirm = input("Would you like to continue anyway? [y/N] ")
            if confirm.lower() != 'y':
                return
                
    print("\nSetup completed!")

def main():
    style = Style.from_dict({
        'prompt': '#00aa00 bold',
        'suggestion': '#666666 italic',
    })
    
    def get_prompt():
        cwd = os.getcwd()
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        return HTML(f'<prompt>{cwd} $ </prompt>')

    session = PromptSession(
        get_prompt,
        auto_suggest=AIAutoSuggest(),
        style=style,
        complete_while_typing=True,
        complete_in_thread=True
    )
    
    bindings = KeyBindings()

    @bindings.add("tab")
    @bindings.add("right")
    def _(event):
        buff = event.app.current_buffer
        if buff.suggestion:
            buff.insert_text(buff.suggestion.text)

    @bindings.add("c-c")
    def _(event):
        event.app.exit(result=None)
        raise KeyboardInterrupt()

    # Debounce suggestion requests
    last_fetch_time = 0
    min_delay_between_fetches = 0.3
    
    def on_text_changed(_):
        nonlocal last_fetch_time
        current_time = time.time()
        
        if current_time - last_fetch_time < min_delay_between_fetches:
            return
            
        last_fetch_time = current_time
        buffer_text = session.default_buffer.document.text
        
        if buffer_text.startswith("?") or len(buffer_text.strip()) < 2:
            return
            
        threading.Thread(
            target=fetch_suggestion_async,
            args=(buffer_text, session),
            daemon=True
        ).start()

    session.default_buffer.on_text_changed += on_text_changed

    print("=== AI Shell ===")
    print("Type commands directly or start with ? for natural language (e.g., ?how to list all files)")
    print("Special commands:")
    print("  %%  - Start setup wizard with context awareness")
    print("  ?   - Natural language command translation")
    print(f"  Note: Shell maintains history of last {COMMAND_HISTORY_LIMIT} commands for context")
    print("Press TAB or RIGHT ARROW to complete suggestions, ENTER to execute")
    
    while True:
        try:
            message = HTML('<prompt>$ </prompt>')
            user_input = session.prompt(message, key_bindings=bindings)
            
            if user_input is None:
                continue
                
            user_input = user_input.strip()
            if not user_input:
                continue
                
            if user_input.lower() in ("exit", "quit"):
                break

            # Handle %% command directly
            if user_input.startswith("%%"):
                request = user_input[2:].strip()
                if not request:
                    print("Please provide a setup request after %%")
                    continue
                handle_setup_request(request)
                continue

            if user_input.startswith("?"):
                query = user_input[1:].strip()
                if not query:
                    print("Please provide a query after ?")
                    continue
                    
                print("Translating query...")
                try:
                    command = get_shell_command(query)
                    if not command:
                        print("Could not generate a command for your query. Please try rephrasing it.")
                        continue
                        
                    confirm = session.prompt("Execute this command? [y/N] ")
                    if confirm.lower() != 'y':
                        continue
                    user_input = command
                except Exception as e:
                    print(f"Error processing query: {str(e)}")
                    continue

            command_history.append(user_input)
            with suggestion_lock:
                current_suggestion = ""
            
            execute_command(user_input)
            
        except KeyboardInterrupt:
            print("\nUse 'exit' or 'quit' to exit")
            continue
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    main()

