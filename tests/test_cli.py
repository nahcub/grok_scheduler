import contextlib
import io
import json
import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tte
from tte import cli, store

# 0.3.0이 만든 DB 스키마(user_version 0). 0.2.0은 여기서 guess_seconds만 없다.
SCHEMA_0_3_0 = """
CREATE TABLE tasks (
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


def run_tte(argv, now=1000.0):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(list(argv), now=now)
    return code, buf.getvalue()


def start_and_stop(i):
    """다른 프로세스에서 돈다. TTE_HOME은 부모 환경에서 물려받는다."""
    code1, out1 = run_tte(["start", f"동시 작업 {i}", "--guess", "60"], now=0)
    task_id = json.loads(out1).get("id")
    code2, out2 = run_tte(["stop", task_id], now=30)
    return code1, code2, out1.count("\n"), out2.count("\n")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = mock.patch.dict(os.environ, {"TTE_HOME": self.tmp.name})
        env.start()
        os.environ.pop("TTE_AGENT", None)
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)

    def tte(self, *argv, now=1000.0):
        code, line = run_tte(argv, now=now)
        self.assertEqual(line.count("\n"), 1, "출력은 한 줄이어야 한다")
        return code, json.loads(line)

    def start(self, task="작업", guess=100, kind="other", now=1000.0, extra=()):
        return self.tte("start", task, "--guess", str(guess), "--kind", kind, *extra, now=now)

    def record(self, n, guess, actual, kind="other"):
        for _ in range(n):
            self.start("기록", guess=guess, kind=kind, now=0)
            self.tte("stop", now=actual)

    def db(self):
        conn = sqlite3.connect(Path(self.tmp.name) / "tte.db")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        return conn

    # 기본 흐름

    def test_start_uses_guess(self):
        code, out = self.start("흰머리독수리 보고서", guess=90, kind="writing")
        self.assertEqual(code, 0)
        self.assertEqual(out["task"], "흰머리독수리 보고서")
        self.assertEqual(out["guess_seconds"], 90)
        self.assertEqual(out["p50_seconds"], 90)
        self.assertEqual(out["p85_seconds"], 135)
        self.assertEqual(out["basis"], {"method": "guess", "samples": 0})
        self.assertEqual(out["scope"], "small")
        self.assertEqual(out["concurrency"], 1)
        self.assertNotIn("open_tasks", out)
        self.assertNotIn("owner", out)

    def test_guess_is_required_and_positive(self):
        code, out = self.tte("start", "작업")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "bad_arguments")
        self.assertIn("--guess", out["message"])
        self.assertEqual(self.tte("start", "작업", "--guess", "0")[1]["error"], "bad_arguments")
        self.assertEqual(self.tte("estimate", "작업", "--guess", "abc")[1]["error"], "bad_arguments")

    def test_wait_time_excluded_from_actual(self):
        _, out = self.start(now=0)
        task_id = out["id"]
        self.tte("wait", now=100)
        _, out = self.tte("resume", now=160)
        self.assertEqual(out["waited_seconds"], 60)
        _, out = self.tte("stop", task_id, now=400)
        self.assertEqual(out["actual_seconds"], 340)
        self.assertEqual(out["waited_seconds"], 60)

    def test_stop_while_waiting_closes_wait(self):
        self.start(now=0)
        self.tte("wait", now=100)
        _, out = self.tte("stop", now=300)
        self.assertEqual(out["waited_seconds"], 200)
        self.assertEqual(out["actual_seconds"], 100)

    def test_stop_without_start_rejected(self):
        code, out = self.tte("stop")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "no_active_task")
        self.assertIn("tte start", out["hint"])

    def test_closed_and_unknown_ids(self):
        _, out = self.start()
        self.tte("stop", out["id"])
        self.assertEqual(self.tte("stop", out["id"])[1]["error"], "task_closed")
        self.assertEqual(self.tte("stop", "nope")[1]["error"], "unknown_task")

    def test_wait_resume_errors(self):
        self.start()
        self.assertEqual(self.tte("resume")[1]["error"], "not_waiting")
        self.tte("wait")
        self.assertEqual(self.tte("wait")[1]["error"], "already_waiting")

    def test_bad_arguments_are_json(self):
        code, out = self.tte("start", "작업", "--guess", "60", "--kind", "huge")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "bad_arguments")
        self.assertEqual(self.tte()[1]["error"], "bad_arguments")
        self.assertEqual(self.tte("start", "  ", "--guess", "60")[1]["error"], "empty_task")
        self.assertEqual(self.tte("start", "작업", "--guess", "60", "--scope", "x")[1]["error"],
                         "bad_arguments")

    def test_old_complexity_flag_still_accepted(self):
        code, _ = self.tte("start", "작업", "--guess", "60", "--complexity", "light")
        self.assertEqual(code, 0)

    def test_estimate_does_not_record(self):
        code, out = self.tte("estimate", "조사", "--guess", "200", "--kind", "research")
        self.assertEqual(code, 0)
        self.assertNotIn("id", out)
        self.assertEqual(out["p50_seconds"], 200)
        self.assertEqual(self.tte("list")[1], {"open": []})
        self.assertEqual(self.tte("estimate", " ", "--guess", "60")[1]["error"], "empty_task")

    # 1. 축소 혼합

    def test_calibrates_overestimating_bot(self):
        # 그록봇이 600초라고 했는데 매번 300초에 끝났다.
        self.record(5, guess=600, actual=300, kind="writing")
        _, out = self.start("보고서", guess=600, kind="writing", now=1000)
        self.assertEqual(out["p50_seconds"], 300)
        self.assertEqual(out["basis"]["method"], "calibrated")
        self.assertEqual(out["basis"]["scope"], "blend")
        self.assertEqual(out["basis"]["ratio"], 0.5)
        self.assertEqual(out["basis"]["kind_samples"], 5)
        self.assertEqual(out["basis"]["all_samples"], 5)
        self.assertEqual(out["confidence"], "medium")

    def test_small_kind_keeps_its_tendency(self):
        # coding은 비율 0.08, browser는 3건뿐이지만 비율 0.15.
        self.record(27, guess=1000, actual=80, kind="coding")
        self.record(3, guess=1000, actual=150, kind="browser")
        _, out = self.tte("estimate", "사이트 입력", "--guess", "1000", "--kind", "browser")
        self.assertGreater(out["p50_seconds"], 80)
        self.assertLess(out["p50_seconds"], 150)
        self.assertEqual(out["basis"]["kind_samples"], 3)
        self.assertEqual(out["basis"]["all_samples"], 30)

    # 2. 크기 구간과 P85 여유

    def test_scope_multi_widens_p85(self):
        self.record(10, guess=100, actual=50)
        _, small = self.tte("estimate", "작업", "--guess", "100")
        _, multi = self.tte("estimate", "작업", "--guess", "100", "--scope", "multi")
        self.assertEqual(small["p85_seconds"], 65)
        self.assertEqual(multi["p85_seconds"], 80)
        self.assertEqual(multi["scope"], "multi")
        _, started = self.start(guess=100, now=2000, extra=("--scope", "multi"))
        row = self.db().execute("SELECT scope FROM tasks WHERE id = ?",
                                (started["id"],)).fetchone()
        self.assertEqual(row["scope"], "multi")

    def test_size_bucket_in_basis(self):
        self.record(5, guess=100, actual=50)
        self.record(5, guess=1000, actual=1000)
        _, short = self.tte("estimate", "작은 작업", "--guess", "100")
        _, long = self.tte("estimate", "큰 작업", "--guess", "1000")
        self.assertEqual(short["basis"]["size_bucket"], "short")
        self.assertEqual(long["basis"]["size_bucket"], "long")
        self.assertEqual(long["basis"]["size_samples"], 5)
        # 큰 작업은 비율이 커서(1.0) 작은 작업(0.5)보다 비율이 크게 나온다.
        self.assertGreater(long["basis"]["ratio"], short["basis"]["ratio"])

    # 3. 동시 실행과 owner

    def test_concurrency_recorded(self):
        _, first = self.start("하나")
        _, second = self.start("둘")
        self.assertEqual(first["concurrency"], 1)
        self.assertEqual(second["concurrency"], 2)
        self.assertEqual(second["open_tasks"], [first["id"]])
        rows = self.db().execute("SELECT id, concurrency FROM tasks").fetchall()
        self.assertEqual({r["id"]: r["concurrency"] for r in rows},
                         {first["id"]: 1, second["id"]: 2})

    def test_multiple_open_tasks_need_id(self):
        _, first = self.start("하나")
        self.start("둘")
        code, out = self.tte("stop")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "ambiguous_task")
        self.assertEqual(self.tte("stop", first["id"])[0], 0)
        self.assertEqual(self.tte("stop")[0], 0)

    def test_owner_scopes_idless_commands(self):
        with mock.patch.dict(os.environ, {"TTE_AGENT": "sub-a"}):
            _, a = self.start("a의 작업")
        with mock.patch.dict(os.environ, {"TTE_AGENT": "sub-b"}):
            _, b = self.start("b의 작업")
            self.assertEqual(b["owner"], "sub-b")
            # 열린 작업은 둘이지만 sub-b 것은 하나라서 id 없이 멈출 수 있다.
            _, out = self.tte("stop")
            self.assertEqual(out["id"], b["id"])
        # TTE_AGENT가 없으면 owner 없는 작업만 후보다.
        self.assertEqual(self.tte("stop")[1]["error"], "no_active_task")
        _, listed = self.tte("list")
        self.assertEqual(listed["open"][0]["owner"], "sub-a")

    def test_stats_by_concurrency(self):
        self.start("혼자", guess=100, now=0)
        self.tte("stop", now=50)
        _, x = self.start("같이1", guess=100, now=0)
        _, y = self.start("같이2", guess=100, now=0)
        self.tte("stop", x["id"], now=100)
        self.tte("stop", y["id"], now=100)
        _, stats = self.tte("stats")
        self.assertEqual(stats["concurrency"], [
            {"concurrency": "1", "samples": 2, "guess_ratio_p50": 0.75, "p85_hit_rate": 1.0},
            {"concurrency": "2-3", "samples": 1, "guess_ratio_p50": 1.0, "p85_hit_rate": 1.0},
        ])

    # 4. 방치 판정

    def test_long_wait_is_still_learned(self):
        # 승인을 7시간 기다렸지만 실제 작업은 100초였다.
        self.start("승인 기다린 작업", guess=100, now=0)
        self.tte("wait", now=50)
        self.tte("resume", now=50 + 7 * 3600)
        _, out = self.tte("stop", now=100 + 7 * 3600)
        self.assertEqual(out["actual_seconds"], 100)
        self.assertEqual(self.tte("stats")[1]["done"], 1)

    def test_long_active_time_not_learned(self):
        self.record(5, guess=100, actual=store.STALE_SECONDS + 1)
        self.record(5, guess=100, actual=50, kind="writing")
        for _ in range(5):
            self.start("실패", now=0)
            self.tte("stop", "--status", "failed", now=100)
        _, stats = self.tte("stats")
        self.assertEqual(stats["done"], 5)

    def test_list_stale_uses_active_time(self):
        _, waiting = self.start("승인 대기", now=0)
        self.tte("wait", waiting["id"], now=10)
        _, forgotten = self.start("잊힌 작업", now=0)
        _, listed = self.tte("list", now=store.STALE_SECONDS + 100)
        by_id = {r["id"]: r for r in listed["open"]}
        self.assertFalse(by_id[waiting["id"]]["stale"])
        self.assertEqual(by_id[waiting["id"]]["active_seconds"], 10)
        self.assertTrue(by_id[forgotten["id"]]["stale"])

    def test_gc_cancels_only_stale(self):
        _, waiting = self.start("승인 대기", now=0)
        self.tte("wait", waiting["id"], now=10)
        _, forgotten = self.start("잊힌 작업", now=0)
        _, out = self.tte("gc", now=store.STALE_SECONDS + 100)
        self.assertEqual([r["id"] for r in out["cancelled"]], [forgotten["id"]])
        _, listed = self.tte("list", now=store.STALE_SECONDS + 100)
        self.assertEqual([r["id"] for r in listed["open"]], [waiting["id"]])
        _, out = self.tte("gc", "--older-than", "5", now=store.STALE_SECONDS + 100)
        self.assertEqual([r["id"] for r in out["cancelled"]], [waiting["id"]])

    # 5. DB 오류와 마이그레이션

    def test_db_error_is_one_line_json(self):
        with mock.patch.object(store, "connect",
                               side_effect=sqlite3.OperationalError("database is locked")):
            code, out = self.tte("list")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "db_error")
        self.assertIn("locked", out["message"])

    def make_old_db(self, schema, with_guess=True):
        conn = sqlite3.connect(Path(self.tmp.name) / "tte.db")
        conn.execute(schema)
        cols = "id, task, complexity, kind, status, started_at, ended_at, actual_seconds," \
               " p50_seconds, p85_seconds, method, samples"
        vals = "'old', '예전', 'medium', 'other', 'done', 0, 50, 50, 600, 900, 'rule', 0"
        if with_guess:
            cols += ", guess_seconds"
            vals += ", 100"
        conn.execute(f"INSERT INTO tasks ({cols}) VALUES ({vals})")
        conn.commit()
        conn.close()

    def test_migrates_0_3_0_database(self):
        self.make_old_db(SCHEMA_0_3_0)
        code, out = self.start(guess=60)
        self.assertEqual(code, 0)
        db = self.db()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], store.SCHEMA_VERSION)
        columns = {r["name"] for r in db.execute("PRAGMA table_info(tasks)")}
        self.assertTrue({"guess_seconds", "concurrency", "owner", "scope"} <= columns)
        _, stats = self.tte("stats")
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["concurrency"][-1]["concurrency"], "unknown")

    def test_migrates_0_2_0_database(self):
        self.make_old_db(SCHEMA_0_3_0.replace("    guess_seconds REAL,\n", ""), with_guess=False)
        code, out = self.start(guess=60)
        self.assertEqual(code, 0)
        self.assertEqual(out["basis"]["method"], "guess")
        self.assertEqual(self.tte("stats")[1]["done"], 1)

    def test_concurrent_processes(self):
        # 새 DB에 20개 프로세스가 동시에 처음 접속해 start/stop 한다(마이그레이션 경합 포함).
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(8) as pool:
            results = pool.map(start_and_stop, range(20))
        for code1, code2, lines1, lines2 in results:
            self.assertEqual((code1, code2, lines1, lines2), (0, 0, 1, 1))
        db = self.db()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 20)
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM tasks WHERE status = 'done'").fetchone()[0], 20)

    # 기타

    def test_stats(self):
        self.assertEqual(self.tte("stats")[1],
                         {"done": 0, "p85_hit_rate": None, "groups": [], "concurrency": []})
        for actual in (100, 400):
            self.start("조사", guess=200, kind="research", now=0)
            self.tte("stop", now=actual)
        _, stats = self.tte("stats")
        self.assertEqual(stats["done"], 2)
        # P85는 300초라서 400초 작업은 예측을 넘긴다.
        self.assertEqual(stats["p85_hit_rate"], 0.5)
        self.assertEqual(stats["groups"], [{"kind": "research", "samples": 2,
                                            "actual_p50_seconds": 250,
                                            "guess_ratio_p50": 1.25}])

    def test_version(self):
        self.assertEqual(self.tte("--version")[1], {"version": tte.__version__})


if __name__ == "__main__":
    unittest.main()
