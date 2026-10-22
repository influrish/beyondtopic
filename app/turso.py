"""Thin sqlite3-compatible adapter over Turso/libSQL, so app/server.py and
app/db.py need no changes beyond selecting this connection when
TURSO_DATABASE_URL is configured. Keeps the same execute/fetchone/fetchall/
row-by-name-or-index contract as sqlite3.Connection and sqlite3.Row.
"""
import libsql_client


class TursoCursor:
    def __init__(self, result):
        self._result = result
        self._rows = list(result.rows)
        self._idx = 0

    def fetchone(self):
        if self._idx >= len(self._rows):
            return None
        row = self._rows[self._idx]
        self._idx += 1
        return row

    def fetchall(self):
        rows = self._rows[self._idx:]
        self._idx = len(self._rows)
        return rows

    def __iter__(self):
        return iter(self._rows[self._idx:])

    def __getitem__(self, key):
        return self._rows[key]

    @property
    def lastrowid(self):
        return self._result.last_insert_rowid

    @property
    def rowcount(self):
        return self._result.rows_affected


class TursoConnection:
    def __init__(self, url, auth_token):
        self._client = libsql_client.create_client_sync(url=url, auth_token=auth_token)
        self._in_transaction = False

    def execute(self, sql, params=()):
        result = self._client.execute(sql, list(params) if params else None)
        if sql.strip().lower().startswith('begin'):
            self._in_transaction = True
        return TursoCursor(result)

    def executescript(self, script):
        for statement in script.split(';'):
            statement = statement.strip()
            if statement:
                self._client.execute(statement)

    def commit(self):
        if self._in_transaction:
            self._client.execute('COMMIT')
            self._in_transaction = False

    def rollback(self):
        if self._in_transaction:
            self._client.execute('ROLLBACK')
            self._in_transaction = False

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def connect(url, auth_token):
    db = TursoConnection(url, auth_token)
    db.execute("PRAGMA foreign_keys=ON")
    return db
