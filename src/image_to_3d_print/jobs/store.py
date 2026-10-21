"""短事务持久化；不在数据库锁内运行工具或等待用户。"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import time
from ..tools import ToolFailure


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


class Store:
    def __init__(self, root):
        from pathlib import Path
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'tasks.sqlite3'
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks(
                    run TEXT PRIMARY KEY, create_key TEXT UNIQUE, create_body TEXT NOT NULL,
                    status TEXT NOT NULL, context TEXT NOT NULL, response TEXT NOT NULL,
                    created REAL NOT NULL, active_seconds REAL NOT NULL DEFAULT 0,
                    runner_pid INTEGER, runner_birth REAL);
                CREATE TABLE IF NOT EXISTS submissions(
                    run TEXT NOT NULL, submission_id TEXT NOT NULL, pending_id TEXT NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(run,submission_id), UNIQUE(run,pending_id));
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL,
                    kind TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_run ON events(run,id);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=15000')
        try: yield db
        finally: db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def row(self, run, db=None):
        if db is None:
            with self.connect() as connection: return self.row(run, connection)
        row = db.execute('SELECT * FROM tasks WHERE run=?', (str(run),)).fetchone()
        if row is None: raise ToolFailure('REFERENCE_NOT_FOUND', '任务不存在')
        result = dict(row)
        result['context'] = json.loads(row['context'])
        result['response'] = json.loads(row['response'])
        return result

    def event(self, db, run, kind, context, data=None):
        db.execute('INSERT INTO events(run,kind,created_at,data) VALUES(?,?,?,?)',
            (str(run), kind, datetime.now(timezone.utc).isoformat(), dumps({
                'stage': context['stage'], 'status': context['status'], **(data or {})})))

    def create(self, context, response, body, key):
        with self.transaction() as db:
            if key:
                row = db.execute('SELECT run,create_body FROM tasks WHERE create_key=?', (key,)).fetchone()
                if row:
                    if row['create_body'] != dumps(body):
                        raise ToolFailure('STATE_CONFLICT', '同一创建幂等键已用于不同请求')
                    return self.row(row['run'], db)
            db.execute('INSERT INTO tasks(run,create_key,create_body,status,context,response,created) VALUES(?,?,?,?,?,?,?)',
                (context['run_id'], key, dumps(body), 'queued', dumps(context), dumps(response), time.time()))
            self.event(db, context['run_id'], 'created', context)
            return self.row(context['run_id'], db)

    def save(self, context, response, kind='progress', data=None):
        with self.transaction() as db:
            row = self.row(context['run_id'], db)
            # API取消请求不能被晚到的节点结果覆盖。
            if row['status'] == 'cancel_requested' and context['status'] not in {'failed', 'cancelled'}:
                context['status'] = 'cancel_requested'
                response['status'] = 'cancel_requested'
                response['data']['state']['status'] = 'cancel_requested'
                context['pending'] = None
                response['data']['state']['pending_input_id'] = None
                response['data']['state']['pending_input_type'] = None
            db.execute('UPDATE tasks SET status=?,context=?,response=? WHERE run=?',
                (context['status'], dumps(context), dumps(response), context['run_id']))
            self.event(db, context['run_id'], kind, context, data)

    def events(self, run, after=0, limit=100):
        self.row(run)
        with self.connect() as db:
            rows = db.execute('SELECT * FROM events WHERE run=? AND id>? ORDER BY id LIMIT ?',
                (str(run), after, limit)).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row['data'])
            result.append({'event_id': row['id'], 'run_id': str(run), 'kind': row['kind'],
                'created_at': row['created_at'], 'stage': payload.pop('stage'),
                'status': payload.pop('status'), 'data': payload})
        return result

    def claim(self):
        with self.transaction() as db:
            row = db.execute("SELECT run FROM tasks WHERE status='queued' ORDER BY created,run LIMIT 1").fetchone()
            if row is None: return None
            db.execute("UPDATE tasks SET status='running' WHERE run=?", (row['run'],))
            return self.row(row['run'], db)

    def pending_submission(self, run, pending):
        with self.connect() as db:
            row = db.execute('SELECT body FROM submissions WHERE run=? AND pending_id=?', (str(run), pending)).fetchone()
        return json.loads(row['body']) if row else None
