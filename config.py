import os
from dotenv import load_dotenv

load_dotenv()

MI_USER = os.getenv("MI_USER", "")
MI_PASS = os.getenv("MI_PASS", "")
DEVICE_ID = os.getenv("DEVICE_ID", "")

LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_SYSTEM_PROMPT = os.getenv(
    "LLM_SYSTEM_PROMPT",
    "你是一个智能助手，通过小爱音箱与用户对话。请用简洁、口语化的方式回答，控制在100字以内。",
)

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.5"))
