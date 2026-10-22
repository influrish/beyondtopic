"""Dependency-free Turso/libSQL client using Turso's HTTP API (the Hrana
"v1/execute" endpoint), built only on the standard library.

A prior version of this module used the official `libsql-client` package,
which depends on `aiohttp`. Vercel's Python runtime bundles its own internal
copy of `aiohttp` for its own use, and the two conflicted at runtime,
crashing every request with FUNCTION_INVOCATION_FAILED as soon as a Turso
connection was configured. This module avoids that entirely by speaking
Turso's plain HTTPS/JSON protocol directly with `urllib.request`.

Each statement is executed as its own independent HTTP request (Turso's
stateless `/v1/execute` endpoint), so there is no persistent "connection" to
reuse across statements. That's fine for everything this app does: each
statement already carries its own `last_insert_rowid` in its own response
(see `TursoCursor.lastrowid`), so code never needs a follow-up query for it.
The app's few explicit BEGIN/COMMIT/ROLLBACK statements are treated as
client-side no-ops (each individual statement already autocommits), trading
multi-statement atomicity for a request/response model simple enough to
implement correctly without a live server to test against.
"""
import base64
import json
import urllib.error
import urllib.request

_MIN_INTEGER = -(2**63)
_MAX_INTEGER = 2**63 - 1
_TRANSACTION_CONTROL = {'begin', 'begin immediate', 'begin deferred', 'begin exclusive', 'commit', 'rollback', 'end'}


class TursoError(Exception):
    pass


def _value_to_proto(value):
    if value is None:
        return {'type': 'null'}
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        if value < _MIN_INTEGER or value > _MAX_INTEGER:
            raise OverflowError('Integer exceeds the range of SQLite integers (64 bits, signed)')
        return {'type': 'integer', 'value': str(value)}
    if isinstance(value, float):
        return {'type': 'float', 'value': value}
    if isinstance(value, (bytes, bytearray)):
        return {'type': 'blob', 'base64': base64.b64encode(bytes(value)).decode('ascii')}
    return {'type': 'text', 'value': str(value)}


def _value_from_proto(value):
    kind = value.get('type')
    if kind == 'null': return None
    if kind == 'text': return str(value['value'])
    if kind == 'integer': return int(value['value'])
    if kind == 'float': return float(value['value'])
    if kind == 'blob': return base64.b64decode(value['base64'] + '====')
    raise TursoError(f'Unknown Turso value type {kind!r}')


class TursoRow:
    __slots__ = ('_cols', '_values')

    def __init__(self, cols, values):
        self._cols = cols
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._cols.index(key)]
        return self._values[key]

    def keys(self):
        return list(self._cols)

    def __repr__(self):
        return repr(dict(zip(self._cols, self._values)))


class TursoCursor:
    def __init__(self, cols, rows, affected_row_count, last_insert_rowid):
        self._rows = [TursoRow(cols, row) for row in rows]
        self._idx = 0
        self.rowcount = affected_row_count
        self.lastrowid = last_insert_rowid

    def fetchone(self):
        if self._idx >= len(self._rows): return None
        row = self._rows[self._idx]; self._idx += 1
        return row

    def fetchall(self):
        rows = self._rows[self._idx:]; self._idx = len(self._rows)
        return rows

    def __iter__(self):
        return iter(self._rows[self._idx:])


class TursoConnection:
    def __init__(self, url, auth_token, timeout=10):
        self._base = url.replace('libsql://', 'https://').rstrip('/')
        self._token = auth_token
        self._timeout = timeout

    def _request(self, path, body):
        req = urllib.request.Request(
            f'{self._base}/{path}',
            data=json.dumps(body).encode(),
            method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self._token}'},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')
            raise TursoError(f'Turso request failed ({exc.code}): {detail}') from exc
        except urllib.error.URLError as exc:
            raise TursoError(f'Could not reach Turso: {exc.reason}') from exc

    def execute(self, sql, params=()):
        stripped = sql.strip().lower()
        if stripped in _TRANSACTION_CONTROL:
            return TursoCursor([], [], 0, None)
        stmt = {'sql': sql, 'args': [_value_to_proto(p) for p in (params or ())], 'named_args': [], 'want_rows': True}
        body = self._request('v1/execute', {'stmt': stmt})
        if 'result' not in body:
            error = body.get('error') or body.get('message') or body
            raise TursoError(f'Turso did not return a result for statement {sql!r}: {error}')
        result = body['result']
        cols = tuple(c.get('name') or '' for c in result.get('cols', []))
        rows = [[_value_from_proto(cell) for cell in row] for row in result.get('rows', [])]
        affected = result.get('affected_row_count', 0)
        last_id_raw = result.get('last_insert_rowid')
        last_id = int(last_id_raw) if last_id_raw is not None else None
        return TursoCursor(cols, rows, affected, last_id)

    def executescript(self, script):
        for statement in script.split(';'):
            statement = statement.strip()
            if statement:
                self.execute(statement)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def connect(url, auth_token):
    db = TursoConnection(url, auth_token)
    db.execute('PRAGMA foreign_keys=ON')
    return db
