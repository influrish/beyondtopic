import hashlib, hmac, os, secrets
from pathlib import Path

def _secret():
    configured=os.environ.get('BEYONDTOPIC_SECRET')
    if configured:return configured.encode()
    default_path=Path('/tmp/beyondtopic-signing-key') if os.environ.get('VERCEL') else Path(__file__).resolve().parent.parent/'data'/'.signing-key'
    path=Path(os.environ.get('BEYONDTOPIC_SECRET_FILE',default_path))
    path.parent.mkdir(parents=True,exist_ok=True)
    try: value=path.read_bytes()
    except FileNotFoundError:
        value=secrets.token_bytes(48)
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(value)
        except FileExistsError:value=path.read_bytes()
    return value

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 240000).hex()
    return f"{salt}${digest}"

def verify_password(password, stored):
    try:
        salt, digest = stored.split('$', 1)
        return hmac.compare_digest(password_hash(password, salt).split('$', 1)[1], digest)
    except (ValueError, TypeError):
        return False

def sign(value):
    secret = _secret()
    mac = hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()
    return value + '.' + mac

def fingerprint(value):
    return hmac.new(_secret(),value.encode(),hashlib.sha256).hexdigest()

def unsign(value):
    if not value or '.' not in value: return None
    raw, mac = value.rsplit('.', 1)
    return raw if hmac.compare_digest(sign(raw).rsplit('.', 1)[1], mac) else None
