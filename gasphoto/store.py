"""Durable photo review ledger and revision-aware delivery queue.

Every operation owns its SQLite connection. Approval uses an immediate transaction
so temporal validation and revision allocation remain atomic across UI workers.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sqlite3


def _json_object(value):
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('Expected a serializable JSON object') from exc


def _capture(value):
    if not isinstance(value, str):
        raise ValueError('Capture time is required with an explicit timezone')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('Invalid ISO capture time') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Capture time requires an explicit timezone')
    try:
        parsed = parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError('Capture time is outside the supported UTC range') from exc
    if parsed > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError('Capture time is in the future')
    return parsed


def _value(value):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,5}(?:\.[0-9]{1,3})?', str(value)):
        raise ValueError('Reading requires five or fewer integer digits and up to three decimals')
    parsed = Decimal(str(value))
    if not parsed.is_finite() or not Decimal('0') <= parsed <= Decimal('99999.999'):
        raise ValueError('Reading must be between 0 and 99999.999 m³')
    return parsed


class Store:
    def __init__(self, db_path, max_m3_per_hour=6.0):
        self.db_path = Path(db_path)
        try:
            self.max_m3_per_hour = Decimal(str(max_m3_per_hour))
        except InvalidOperation as exc:
            raise ValueError('Invalid maximum consumption rate') from exc
        if not self.max_m3_per_hour.is_finite() or self.max_m3_per_hour <= 0:
            raise ValueError('Maximum consumption rate must be positive and finite')
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS photos (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    archive_path TEXT NOT NULL,
                    captured_at TEXT,
                    captured_utc TEXT,
                    metadata TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proposal TEXT,
                    value TEXT,
                    revision INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS photos_time ON photos(captured_utc);
                CREATE TABLE IF NOT EXISTS audit (
                    photo_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    record TEXT NOT NULL,
                    PRIMARY KEY(photo_id, revision)
                );
                CREATE TABLE IF NOT EXISTS training_examples (
                    photo_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    window_quad_json TEXT NOT NULL,
                    value_digits TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    model_version TEXT,
                    PRIMARY KEY(photo_id, revision)
                );
                CREATE TABLE IF NOT EXISTS model_versions (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_evaluations (
                    model_id TEXT NOT NULL,
                    photo_id TEXT NOT NULL,
                    result TEXT NOT NULL,
                    PRIMARY KEY(model_id, photo_id)
                );
            ''')

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _row(row):
        if row is None:
            return None
        result = dict(row)
        result.pop('captured_utc', None)
        result['metadata'] = json.loads(result['metadata'])
        result['proposal'] = json.loads(result['proposal']) if result['proposal'] is not None else None
        return result

    def _require(self, connection, id):
        row = self._row(connection.execute('SELECT * FROM photos WHERE id=?', (id,)).fetchone())
        if row is None:
            raise ValueError('Unknown photo')
        return row

    def add_photo(self, id, filename, archive_path, captured_at, metadata, error=None):
        if not isinstance(id, str) or not re.fullmatch(r'[0-9a-f]{64}', id):
            raise ValueError('Photo ID must be a lowercase SHA-256 hash')
        encoded = _json_object(metadata)
        try:
            utc = _capture(captured_at).isoformat(timespec='microseconds')
            status = 'needs_review'
        except ValueError:
            utc = None
            status = 'needs_timestamp'
        with self._connection() as connection:
            connection.execute('''INSERT OR IGNORE INTO photos
                (id, filename, archive_path, captured_at, captured_utc, metadata, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (id, str(filename), str(archive_path), captured_at, utc, encoded, status, error))
            return self._require(connection, id)

    def list_photos(self):
        with self._connection() as connection:
            return [self._row(row) for row in connection.execute(
                'SELECT * FROM photos ORDER BY captured_utc DESC, filename ASC, id ASC')]

    def get_photo(self, id):
        with self._connection() as connection:
            return self._row(connection.execute('SELECT * FROM photos WHERE id=?', (id,)).fetchone())

    def set_proposal(self, id, proposal, error=None):
        encoded = _json_object(proposal)
        if proposal.get('value'):
            status = 'counter_recognized'
        elif proposal.get('crop'):
            status = 'position_identified'
        else:
            status = 'needs_review'
        with self._connection() as connection:
            connection.execute('''UPDATE photos SET proposal=?, error=?, status=?
                WHERE id=? AND revision=0''', (encoded, error, status, id))
            return self._require(connection, id)

    def discard(self, id):
        """Discard an unreviewed photo; durable approved history is immutable."""
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = self._require(connection, id)
            if row['revision'] or row['status'] in ('pending_sync', 'synced'):
                raise ValueError('Jóváhagyott vagy szinkronizált leolvasás nem vethető el.')
            connection.execute('DELETE FROM training_examples WHERE photo_id=?', (id,))
            connection.execute('DELETE FROM audit WHERE photo_id=?', (id,))
            connection.execute('DELETE FROM photos WHERE id=?', (id,))
            return row

    def record_training_example(self, id, window_quad, value, decision, model_version=None):
        if decision not in ('approved', 'corrected'):
            raise ValueError('Training decision must be approved or corrected')
        if not isinstance(window_quad, list) or len(window_quad) != 4:
            raise ValueError('Window requires four normalized points')
        normalized = []
        for point in window_quad:
            if not isinstance(point, list) or len(point) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 1 for x in point):
                raise ValueError('Window points must be normalized coordinates')
            normalized.append([float(point[0]), float(point[1])])
        if len({tuple(point) for point in normalized}) != 4:
            raise ValueError('Window points must be distinct')
        match = re.fullmatch(r'([0-9]{1,5})\.([0-9]{3})', str(value))
        if not match:
            raise ValueError('Training reading requires five whole and three decimal digits')
        digits = match.group(1).zfill(5) + match.group(2)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            row = self._require(connection, id)
            if row['revision'] < 1:
                raise ValueError('Training example requires an approved reading')
            connection.execute('''INSERT OR REPLACE INTO training_examples
                (photo_id, revision, window_quad_json, value_digits, decision, created_at, model_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (id, row['revision'], _json_object({'points': normalized}), digits, decision, created_at, model_version))
            return self.training_example(id, row['revision'], connection)

    def training_example(self, id, revision=None, connection=None):
        own_connection = connection is None
        if own_connection:
            with self._connection() as opened:
                return self.training_example(id, revision, opened)
        query = 'SELECT * FROM training_examples WHERE photo_id=?'
        args = [id]
        if revision is not None:
            query += ' AND revision=?'
            args.append(revision)
        row = connection.execute(query + ' ORDER BY revision DESC LIMIT 1', args).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['window_quad'] = json.loads(result.pop('window_quad_json'))['points']
        return result

    def training_examples(self):
        with self._connection() as connection:
            rows = connection.execute('SELECT * FROM training_examples ORDER BY created_at, photo_id').fetchall()
            return [self.training_example(row['photo_id'], row['revision'], connection) for row in rows]

    def _validate_neighbors(self, connection, id, instant, value):
        utc = instant.isoformat(timespec='microseconds')
        same = connection.execute('''SELECT value FROM photos
            WHERE revision>0 AND id<>? AND captured_utc=?''', (id, utc)).fetchall()
        if any(Decimal(row['value']) != value for row in same):
            raise ValueError('Conflicting reading at the same capture time')
        for operator, order in [('<', 'DESC'), ('>', 'ASC')]:
            neighbor = connection.execute(f'''SELECT captured_at, value FROM photos
                WHERE revision>0 AND id<>? AND captured_utc {operator} ?
                ORDER BY captured_utc {order} LIMIT 1''', (id, utc)).fetchone()
            if neighbor is None:
                continue
            neighbor_time = datetime.fromisoformat(neighbor['captured_at']).astimezone(timezone.utc)
            if operator == '<':
                delta = value - Decimal(neighbor['value'])
                elapsed = instant - neighbor_time
            else:
                delta = Decimal(neighbor['value']) - value
                elapsed = neighbor_time - instant
            if delta < 0:
                raise ValueError('Reading decreases relative to an accepted temporal neighbor')
            microseconds = (elapsed.days * 86400 + elapsed.seconds) * 1000000 + elapsed.microseconds
            bound = self.max_m3_per_hour * Decimal(microseconds) / Decimal(3600000000) + Decimal('0.001')
            if delta > bound:
                raise ValueError('Consumption rate exceeds the configured maximum')

    def approve(self, id, value, captured_at=None):
        parsed_value = _value(value)
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = self._require(connection, id)
            capture = row['captured_at'] if captured_at is None else captured_at
            instant = _capture(capture)
            self._validate_neighbors(connection, id, instant, parsed_value)
            revision = row['revision'] + 1
            reviewed_at = datetime.now(timezone.utc).isoformat()
            metadata = row['metadata']
            metadata.setdefault('original_captured_at', row['captured_at'])
            history = metadata.setdefault('review_history', [])
            if not isinstance(history, list):
                raise ValueError('Review history metadata must be a list')
            history.append({'revision': revision, 'reviewed_at': reviewed_at,
                            'captured_at': capture, 'value': str(parsed_value),
                            'previous_captured_at': row['captured_at'], 'previous_value': row['value']})
            connection.execute('''UPDATE photos SET captured_at=?, captured_utc=?, metadata=?,
                status='pending_sync', value=?, revision=?, error=NULL WHERE id=?''',
                (capture, instant.isoformat(timespec='microseconds'), _json_object(metadata),
                 str(parsed_value), revision, id))
            approved = self._require(connection, id)
            connection.execute('INSERT INTO audit VALUES (?, ?, ?, ?)',
                               (id, revision, reviewed_at, _json_object(approved)))
            return approved

    def pending_readings(self):
        with self._connection() as connection:
            rows = connection.execute('''SELECT * FROM photos WHERE status='pending_sync'
                ORDER BY captured_utc ASC, filename ASC, id ASC''').fetchall()
            return [{'id': row['id'], 'meter_id': 'gas_main', 'captured_at': row['captured_at'],
                     'value': row['value'], 'revision': row['revision'], 'source': 'manual_review',
                     'metadata': json.loads(row['metadata'])} for row in rows]

    def mark_synced(self, id, revision):
        with self._connection() as connection:
            self._require(connection, id)
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ValueError('Revision must be a positive integer')
            result = connection.execute('''UPDATE photos SET status='synced', error=NULL
                WHERE id=? AND revision=? AND status='pending_sync' ''', (id, revision))
            return result.rowcount == 1

    def set_sync_error(self, id, error):
        with self._connection() as connection:
            connection.execute("UPDATE photos SET error=? WHERE id=? AND status='pending_sync'", (error, id))
            return self._require(connection, id)
