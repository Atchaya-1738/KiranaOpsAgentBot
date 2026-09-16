from dotenv import load_dotenv
load_dotenv()

from db.database import init_db
from seed_data import seed_if_empty
from bot.telegram_bot import main as run_bot

if __name__ == "__main__":
    init_db()
    seed_if_empty()
    run_bot()
