from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ID", 0))
DB_PATH = os.getenv("DB_PATH", "databases/database.db")