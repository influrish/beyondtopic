"""Create an additional administrator/editor account."""
import getpass
from app import db
from app.security import password_hash

db.initialize()
name=input('Username: ').strip()
password=getpass.getpass('Password: ')
if len(password)<12: raise SystemExit('Use at least 12 characters.')
with db.connect() as conn:
    conn.execute('insert into users(username,password_hash,role) values(?,?,?)',(name,password_hash(password),'admin'))
print('Account created.')
