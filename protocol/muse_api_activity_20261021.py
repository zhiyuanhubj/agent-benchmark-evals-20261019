"""Persistent request counts without API secrets, prompts or response content."""
import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path


class BackgroundYielded(Exception):
    pass


async def wait_or_yield(awaitable, cancel):
    task = asyncio.create_task(awaitable)
    signal = asyncio.create_task(cancel.wait())
    try:
        done, _ = await asyncio.wait([task, signal], return_when=asyncio.FIRST_COMPLETED)
        if signal in done:
            raise BackgroundYielded()
        return await task
    finally:
        for pending in (task, signal):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, signal, return_exceptions=True)


class Activity:
    def __init__(self, path, idle_seconds=120):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.idle_seconds = idle_seconds
        self.active = {}
        self.started = time.time()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, label TEXT, '
                       'background INTEGER, started REAL, finished REAL, status INTEGER, '
                       'prompt_tokens INTEGER, completion_tokens INTEGER)')
            row = db.execute('SELECT MAX(started) FROM requests WHERE background=0').fetchone()
            first = db.execute('SELECT MIN(started) FROM requests').fetchone()[0]
        self.last_real = max(row[0] or self.started, self.started)
        self.observed_since = first or self.started
        self.path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA journal_mode=WAL')
        return db

    def begin(self, label, background):
        now = time.time()
        if background and (self.active or now - self.last_real < self.idle_seconds):
            return None
        if not background:
            self.last_real = now
            for record in self.active.values():
                if record['background']:
                    record['cancel'].set()
        request_id = uuid.uuid4().hex
        record = {'id': request_id, 'label': label, 'background': background,
                  'started': now, 'cancel': asyncio.Event()}
        with self.connect() as db:
            db.execute('INSERT INTO requests (id,label,background,started) VALUES (?,?,?,?)',
                       (request_id, label, int(background), now))
        self.active[request_id] = record
        return record

    def finish(self, record, status, usage=None):
        if self.active.pop(record['id'], None) is None:
            return
        usage = usage or {}
        with self.connect() as db:
            db.execute('UPDATE requests SET finished=?,status=?,prompt_tokens=?,completion_tokens=? WHERE id=?',
                       (time.time(), status, usage.get('prompt_tokens'), usage.get('completion_tokens'), record['id']))

    def snapshot(self):
        now = time.time()
        with self.connect() as db:
            labels = [row[0] for row in db.execute('SELECT DISTINCT label FROM requests')]
            by_key = {}
            for label in labels:
                row = db.execute('SELECT COUNT(*),SUM(status BETWEEN 200 AND 299),'
                                 'SUM(status>=400),MAX(started),SUM(prompt_tokens),SUM(completion_tokens) '
                                 'FROM requests WHERE label=?', (label,)).fetchone()
                windows = {str(window): db.execute('SELECT COUNT(*) FROM requests WHERE label=? AND started>=?',
                           (label, now-window)).fetchone()[0] for window in (300, 900, 3600)}
                by_key[label] = dict(requests=row[0], succeeded=row[1] or 0, errors=row[2] or 0,
                                     last_started=row[3], prompt_tokens=row[4] or 0,
                                     completion_tokens=row[5] or 0, requests_in_seconds=windows)
        return dict(observed_since=self.observed_since, process_started=self.started,
                    last_real_activity=self.last_real, idle_seconds=now-self.last_real,
                    real_active=sum(not r['background'] for r in self.active.values()),
                    background_active=sum(r['background'] for r in self.active.values()), by_key=by_key,
                    qualification='Counts begin when instrumentation was installed; historical per-key usage is unknown.')


def response_usage(payload):
    try:
        return json.loads(payload).get('usage') or {}
    except (ValueError, AttributeError):
        return {}
