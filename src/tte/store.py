"""SQLite 저장소. 작업 하나가 tasks 테이블의 행 하나다."""

import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# 시작한 지 이보다 오래 열려 있던 작업은 기록을 빠뜨린 것으로 보고 학습에서 뺀다.
STALE_SECONDS = 6 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    complexity TEXT NOT NULL,
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
    samples INTEGER NOT NULL
)
"""


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
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(SCHEMA)
    # 0.2.0 이하로 만든 DB에는 guess_seconds가 없다.
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
    if "guess_seconds" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN guess_seconds REAL")
    return conn


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


def insert_task(conn, *, task_id, task, complexity, kind, guess, now, estimate):
    conn.execute(
        "INSERT INTO tasks (id, task, complexity, kind, guess_seconds, started_at,"
        " p50_seconds, p85_seconds, method, samples)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id, task, complexity, kind, guess, now,
            estimate["p50_seconds"], estimate["p85_seconds"],
            estimate["basis"]["method"], estimate["basis"]["samples"],
        ),
    )


def get_task(conn, task_id):
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def open_tasks(conn):
    return conn.execute(
        "SELECT * FROM tasks WHERE status = 'open' ORDER BY started_at"
    ).fetchall()


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
    """학습에 쓸 기록: 정상 종료했고 오래 방치되지 않은 작업."""
    sql = "SELECT * FROM tasks WHERE status = 'done' AND ended_at - started_at <= ?"
    params = [STALE_SECONDS]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    return conn.execute(sql, params).fetchall()


def ratios(conn, kind=None):
    """실제 ÷ 그록봇 추정. 추정 없이 기록된 예전 작업은 뺀다."""
    return [r["actual_seconds"] / r["guess_seconds"] for r in done_tasks(conn, kind)
            if r["guess_seconds"]]
