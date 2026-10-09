"""Create a consistent SQLite backup."""
from datetime import datetime
from app.db import DB_PATH, connect

target=DB_PATH.with_name(f'{DB_PATH.stem}-{datetime.now().strftime("%Y%m%d-%H%M%S")}.backup.sqlite3')
with connect() as source, __import__('sqlite3').connect(target) as dest:
    source.backup(dest)
print(target)
