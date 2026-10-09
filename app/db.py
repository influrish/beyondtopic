import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("BEYONDTOPIC_DB", ROOT / "data" / "beyondtopic.sqlite3"))

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'admin', author_id INTEGER REFERENCES authors(id));
CREATE TABLE IF NOT EXISTS authors(id INTEGER PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, bio TEXT DEFAULT '', title TEXT DEFAULT 'Editor');
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, slug TEXT UNIQUE NOT NULL, description TEXT DEFAULT '', parent_id INTEGER REFERENCES categories(id), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, slug TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, excerpt TEXT DEFAULT '', body TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'draft', author_id INTEGER REFERENCES authors(id), category_id INTEGER REFERENCES categories(id), featured INTEGER NOT NULL DEFAULT 0, affiliate_disclosure INTEGER NOT NULL DEFAULT 0, is_sample INTEGER NOT NULL DEFAULT 0, seo_title TEXT DEFAULT '', meta_description TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, published_at TEXT, featured_image TEXT DEFAULT '', image_alt TEXT DEFAULT '', image_caption TEXT DEFAULT '', image_credit TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, body TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'draft', seo_title TEXT DEFAULT '', meta_description TEXT DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, canonical_url TEXT DEFAULT '', social_image TEXT DEFAULT '', noindex INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS post_tags(post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE, tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY(post_id,tag_id));
CREATE TABLE IF NOT EXISTS subscribers(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL DEFAULT 'subscribed', consent_at TEXT);
CREATE TABLE IF NOT EXISTS media(id INTEGER PRIMARY KEY, filename TEXT NOT NULL, alt TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS affiliate_links(id INTEGER PRIMARY KEY, name TEXT NOT NULL, destination TEXT NOT NULL, affiliate_url TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS redirects(id INTEGER PRIMARY KEY, source TEXT UNIQUE NOT NULL, destination TEXT NOT NULL, code INTEGER NOT NULL DEFAULT 301, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, username TEXT NOT NULL, action TEXT NOT NULL, detail TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS post_revisions(id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, snapshot TEXT NOT NULL, editor TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS page_revisions(id INTEGER PRIMARY KEY, page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE, snapshot TEXT NOT NULL, editor TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT DEFAULT '', description TEXT DEFAULT '', image_url TEXT DEFAULT '', price TEXT DEFAULT '', currency TEXT DEFAULT 'USD', merchant TEXT DEFAULT '', destination_url TEXT DEFAULT '', affiliate_url TEXT DEFAULT '', market TEXT DEFAULT '', verified_at TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS menu_items(id INTEGER PRIMARY KEY, label TEXT NOT NULL, url TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS homepage_sections(id INTEGER PRIMARY KEY, title TEXT NOT NULL, section_type TEXT NOT NULL DEFAULT 'latest', position INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS analytics_events(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS auth_attempts(id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL, succeeded INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
"""

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db

def initialize():
    with connect() as db:
        db.executescript(SCHEMA)
        # Forward-only lightweight schema upgrades for databases created by earlier starter versions.
        additions = {
            "users": {"author_id": "INTEGER REFERENCES authors(id)"},
            "categories": {"active": "INTEGER NOT NULL DEFAULT 1"},
            "posts": {"scheduled_at": "TEXT", "trashed_at": "TEXT", "canonical_url": "TEXT DEFAULT ''", "social_image": "TEXT DEFAULT ''", "noindex": "INTEGER NOT NULL DEFAULT 0", "is_sample": "INTEGER NOT NULL DEFAULT 0", "featured_image": "TEXT DEFAULT ''", "image_alt": "TEXT DEFAULT ''", "image_caption": "TEXT DEFAULT ''", "image_credit": "TEXT DEFAULT ''", "updated_at": "TEXT"},
            "pages": {"template": "TEXT DEFAULT 'general'", "scheduled_at": "TEXT", "trashed_at": "TEXT", "canonical_url": "TEXT DEFAULT ''", "social_image": "TEXT DEFAULT ''", "noindex": "INTEGER NOT NULL DEFAULT 0"},
            "authors": {"photo_url": "TEXT DEFAULT ''", "job_title": "TEXT DEFAULT ''", "email": "TEXT DEFAULT ''", "social_links": "TEXT DEFAULT ''"},
            "subscribers": {"status": "TEXT NOT NULL DEFAULT 'subscribed'", "consent_at": "TEXT"},
            "media": {"alt": "TEXT DEFAULT ''", "caption": "TEXT DEFAULT ''", "description": "TEXT DEFAULT ''", "mime_type": "TEXT DEFAULT ''", "size": "INTEGER DEFAULT 0"},
            "affiliate_links": {"merchant": "TEXT DEFAULT ''", "campaign": "TEXT DEFAULT ''", "product_id": "INTEGER", "post_id": "INTEGER", "created_at": "TEXT", "updated_at": "TEXT"},
            "redirects": {"notes": "TEXT DEFAULT ''"},
        }
        for table, columns in additions.items():
            present = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in present:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
