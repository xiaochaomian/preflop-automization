import os
from dotenv import load_dotenv

load_dotenv()

GAME_URL = os.getenv("GAME_URL", "")
PLAYER_NAME = os.getenv("PLAYER_NAME", "")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))
BIG_BLIND = float(os.getenv("BIG_BLIND", "10"))
SMALL_BLIND = float(os.getenv("SMALL_BLIND", "5"))
