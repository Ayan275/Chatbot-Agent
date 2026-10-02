import os
import sys
import json
import time
import subprocess
from google import genai
from google.genai import types

# ---------------------------------------------------------
# Configurations & Environment Setup
# ---------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PRIMARY_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

# Fallback sequence for high demand (503 / 429 errors)
FALLBACK_MODELS = [
    PRIMARY_MODEL,
    "gemini-3.7-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash"
]

# Path resolution for C++ Chatbot Executable (Windows & Linux/Render/Railway)
def get_cpp_executable():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "chatbot_backend"),
        os.path.join(base_dir, "chatbot_backend.exe"),
        os.path.join(base_dir, "build", "chatbot_backend"),
        os.path.join(base_dir, "build", "chatbot_backend.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return os.path.join(base_dir, "chatbot_backend" if sys.platform != "win32" else "chatbot_backend.exe")

CPP_EXECUTABLE = get_cpp_executable()

# Initialize Google GenAI Client with lazy fallback
_client = None

def get_genai_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing!")
    _client = genai.Client(api_key=api_key)
    return _client

if GEMINI_API_KEY:
    try:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[WARN] Failed to initialize Google GenAI Client at startup: {e}", file=sys.stderr)
else:
    print("[WARN] GEMINI_API_KEY environment variable is currently not set.", file=sys.stderr)

# ---------------------------------------------------------
# Gemini API Call Handler (with Fallback Logic)
# ---------------------------------------------------------
def call_gemini_api(prompt, system_instruction=None, media_files=None):
    """
    Calls Gemini API with fallbacks for service unavailable errors.
    Supports text, images, audio, and PDF attachments.
    """
    client = get_genai_client()
    contents = []
    
    # Process visual/multimodal inputs if provided
    if media_files:
        for file_path, mime_type in media_files:
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                contents.append(
                    types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
                )
    
    contents.append(prompt)

    config = types.GenerateContentConfig()
    if system_instruction:
        config.system_instruction = system_instruction

    # Attempt primary and fallback models sequentially
    for model_name in FALLBACK_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
            return response.text
        except Exception as e:
            err_msg = str(e)
            if "503" in err_msg or "UNAVAILABLE" in err_msg or "429" in err_msg:
                print(f"[WARN] Model {model_name} busy/unavailable. Retrying/Falling back...", file=sys.stderr)
                time.sleep(2)
                continue
            else:
                print(f"[ERROR] Gemini API Error on {model_name}: {err_msg}", file=sys.stderr)
                raise e

    raise RuntimeError("All configured Gemini models failed or were unavailable.")

# ---------------------------------------------------------
# C++ Subprocess IPC Bridge
# ---------------------------------------------------------
def query_cpp_backend(prompt: str, timeout: int = 15) -> str:
    """
    Sends a message to the C++ backend binary subprocess via standard I/O pipe
    and returns its output.
    """
    executable = get_cpp_executable()
    if not os.path.exists(executable):
        return f"[ERROR] Executable not found at {executable}"

    try:
        process = subprocess.Popen(
            [executable],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        stdout, stderr = process.communicate(input=prompt + "\n", timeout=timeout)
        output = stdout.strip() if stdout else stderr.strip()
        return output
    except subprocess.TimeoutExpired:
        process.kill()
        return "[ERROR] C++ backend subprocess timed out."
    except Exception as e:
        return f"[ERROR] Subprocess pipe error: {e}"

def run_cpp_chatbot_loop():
    """
    Launches the C++ backend process and routes messages back and forth in an interactive terminal session.
    """
    executable = get_cpp_executable()
    if not os.path.exists(executable):
        print(f"[ERROR] Executable not found at {executable}", file=sys.stderr)
        return

    process = subprocess.Popen(
        [executable],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    print(f"[INFO] C++ Chatbot Backend ({executable}) initialized with Gemini Engine.")

    try:
        while True:
            user_input = input("User > ")
            if user_input.strip().lower() in ["exit", "quit"]:
                process.terminate()
                break

            # Send prompt to C++ backend
            process.stdin.write(user_input + "\n")
            process.stdin.flush()

            # Read intermediate/processed state from C++
            cpp_output = process.stdout.readline().strip()
            
            # Send processed request to Gemini API
            bot_response = call_gemini_api(prompt=cpp_output)

            # Return response back to C++ binary/User
            print(f"Bot > {bot_response}\n")

    except KeyboardInterrupt:
        process.terminate()
        print("\n[INFO] Session terminated.")

if __name__ == "__main__":
    run_cpp_chatbot_loop()