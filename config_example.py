import os
from dotenv import load_dotenv

load_dotenv()

# --- LLM ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# --- Agent ---
MAX_TOOL_ROUNDS = 5   # Maximum tool-calling loops before stopping
                      # Prevents runaway agent loops

# --- Data ---
DATA_PATH = "./data"
