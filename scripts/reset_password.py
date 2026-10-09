"""Reset a local publishing account password interactively."""
import getpass
from app import db
from app.security import password_hash

db.initialize()
username=input('Account username: ').strip()
password=getpass.getpass('New password (12+ characters): ')
confirm=getpass.getpass('Repeat password: ')
if len(password)<12 or password!=confirm:raise SystemExit('Passwords must match and be at least 12 characters.')
with db.connect() as conn:
    cur=conn.execute('update users set password_hash=? where username=?',(password_hash(password),username))
    if not cur.rowcount:raise SystemExit('No account with that username.')
    conn.execute('delete from sessions where user_id=(select id from users where username=?)',(username,))
print('Password updated; previous sessions were signed out.')
