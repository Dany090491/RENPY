import os
import datetime
import pathlib

LOG_DIR = str(pathlib.Path(__file__).parent.parent / "logs")
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
MAX_SIZE = 5 * 1024 * 1024  # 5MB

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

class Logger:
    callbacks = []

    @staticmethod
    def _rotate():
        if not os.path.exists(LOG_FILE):
            return
        if os.path.getsize(LOG_FILE) < MAX_SIZE:
            return
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        os.rename(LOG_FILE, os.path.join(LOG_DIR, f"bot-{ts}.log"))

    @staticmethod
    def _write(level, msg):
        Logger._rotate()
        line = f"{datetime.datetime.now().isoformat()} [{level}] {msg}\n"
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
        for cb in Logger.callbacks:
            cb(line.strip())

    @staticmethod
    def info(msg): Logger._write("INFO", msg)
    @staticmethod
    def warn(msg): Logger._write("WARN", msg)
    @staticmethod
    def error(msg): Logger._write("ERROR", msg)
