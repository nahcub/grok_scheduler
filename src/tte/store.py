"""SQLite 저장소. 작업 하나가 tasks 테이블의 행 하나다."""

import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# 대기를 뺀 작업 시간이 이보다 길면 기록을 빠뜨린 것으로 보고 학습에서 뺀다.
STALE_SECONDS = 6 * 3600

# PRAGMA user_version. 0 = 0.3.0 이하(버전 관리 전), 1 = 0.4.0.
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    complexity TEXT NOT NULL DEFAULT 'medium',
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    started_at REAL NOT NULL,
    ended_at REAL,
    waited_seconds REAL NOT NULL DEFAULT 0,
    wait_started_at REAL,
    wait_reason TEXT,
    actual_seconds REAL,
    guess_seconds REAL,
    p50_seconds INTEGER NOT NULL,
    p85_seconds INTEGER NOT NULL,
    method TEXT NOT NULL,
    samples INTEGER NOT NULL,
    concurrency INTEGER,
    owner TEXT,
    scope TEXT
)
"""

# 예전 DB에 없을 수 있는 컬럼. 0.2.0 이하에는 guess_seconds도 없다.
ADDED_COLUMNS = {
    "guess_seconds": "REAL",
    "concurrency": "INTEGER",
    "owner": "TEXT",
    "scope": "TEXT",
}

# open_tasks에서 owner로 거르지 않을 때 쓰는 표시.
ANY_OWNER = object()


class TteError(Exception):
    """그록봇에게 JSON으로 돌려줄 오류. hint는 다음에 할 행동이다."""

    def __init__(self, code, message, hint):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self):
        return {"error": self.code, "message": self.message, "hint": self.hint}


def default_home():
    env = os.environ.get("TTE_HOME")
    if env:
        return Path(env)
    # 그록봇 VM은 작업 파일을 /workspace에 둔다.
    if Path("/workspace").is_dir():
        return Path("/workspace/.tte")
    return Path.home() / ".tte"


def connect(home=None):
    home = Path(home) if home else default_home()
    home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(home / "tte.db", timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        migrate(conn)
    return conn


def migrate(conn):
    """처음 접속하는 프로세스 여럿이 겹쳐도 한 번만 바뀌도록 잠금 안에서 다시 확인한다."""
    conn.execute("PRAGMA journal_mode=WAL")
    with write(conn):
        if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
            return
        conn.execute(SCHEMA)
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        for name, sql_type in ADDED_COLUMNS.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {sql_type}")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


@contextmanager
def write(conn):
    """동시에 도는 다른 tte 프로세스와 겹치지 않게 쓰기 잠금을 잡는다."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def new_id(conn):
    while True:
        task_id = secrets.token_hex(3)
        if get_task(conn, task_id) is None:
            return task_id


def insert_task(conn, *, task_id, task, complexity, kind, guess, now, estimate,
                concurrency, owner, scope):
    conn.execute(
        "INSERT INTO tasks (id, task, complexity, kind, guess_seconds, started_at,"
        " p50_seconds, p85_seconds, method, samples, concurrency, owner, scope)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id, task, complexity, kind, guess, now,
            estimate["p50_seconds"], estimate["p85_seconds"],
            estimate["basis"]["method"], estimate["basis"]["samples"],
            concurrency, owner, scope,
        ),
    )


def get_task(conn, task_id):
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def open_tasks(conn, owner=ANY_OWNER):
    sql = "SELECT * FROM tasks WHERE status = 'open'"
    params = []
    if owner is not ANY_OWNER:
        # IS는 NULL끼리도 같다고 본다(TTE_AGENT를 안 쓰는 기본 환경).
        sql += " AND owner IS ?"
        params.append(owner)
    return conn.execute(sql + " ORDER BY started_at", params).fetchall()


def active_seconds(row, now):
    """대기를 뺀 작업 시간. 지금 대기 중이면 그 대기도 뺀다."""
    waited = row["waited_seconds"]
    if row["wait_started_at"] is not None:
        waited += max(0.0, now - row["wait_started_at"])
    return max(0.0, now - row["started_at"] - waited)


def start_wait(conn, task_id, reason, now):
    conn.execute(
        "UPDATE tasks SET wait_started_at = ?, wait_reason = ? WHERE id = ?",
        (now, reason, task_id),
    )


def end_wait(conn, task_id, now):
    """대기를 끝내고 이번 대기 시간(초)을 돌려준다."""
    row = get_task(conn, task_id)
    waited = max(0.0, now - row["wait_started_at"])
    conn.execute(
        "UPDATE tasks SET waited_seconds = waited_seconds + ?,"
        " wait_started_at = NULL, wait_reason = NULL WHERE id = ?",
        (waited, task_id),
    )
    return waited


def finish(conn, task_id, status, now):
    if get_task(conn, task_id)["wait_started_at"] is not None:
        end_wait(conn, task_id, now)
    row = get_task(conn, task_id)
    actual = max(0.0, now - row["started_at"] - row["waited_seconds"])
    conn.execute(
        "UPDATE tasks SET status = ?, ended_at = ?, actual_seconds = ? WHERE id = ?",
        (status, now, actual, task_id),
    )
    return get_task(conn, task_id)


def done_tasks(conn, kind=None):
    """학습에 쓸 기록: 정상 종료했고, 대기를 뺀 작업 시간이 방치 기준 이하인 작업."""
    sql = "SELECT * FROM tasks WHERE status = 'done' AND actual_seconds <= ?"
    params = [STALE_SECONDS]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    return conn.execute(sql, params).fetchall()


def ratios(conn, kind=None, guess_range=None):
    """실제 ÷ 그록봇 추정. 추정 없이 기록된 예전 작업은 뺀다.

    guess_range=(lo, hi)이면 추정이 lo 이상 hi 미만인 작업만 본다.
    """
    out = []
    for r in done_tasks(conn, kind):
        guess = r["guess_seconds"]
        if not guess:
            continue
        if guess_range and not guess_range[0] <= guess < guess_range[1]:
            continue
        out.append(r["actual_seconds"] / guess)
    return out


def cancel_stale(conn, now, threshold):
    """대기를 뺀 작업 시간이 threshold를 넘은 열린 작업을 cancelled로 닫는다."""
    stale = [r for r in open_tasks(conn) if active_seconds(r, now) > threshold]
    for r in stale:
        finish(conn, r["id"], "cancelled", now)
    return stale
