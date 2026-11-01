import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tte import cli, store


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = mock.patch.dict(os.environ, {"TTE_HOME": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)

    def tte(self, *argv, now=1000.0):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(list(argv), now=now)
        line = buf.getvalue()
        self.assertEqual(line.count("\n"), 1, "출력은 한 줄이어야 한다")
        return code, json.loads(line)

    def start(self, task="작업", guess=100, kind="other", now=1000.0):
        return self.tte("start", task, "--guess", str(guess), "--kind", kind, now=now)

    def test_start_uses_guess(self):
        code, out = self.start("흰머리독수리 보고서", guess=90, kind="writing")
        self.assertEqual(code, 0)
        self.assertEqual(out["task"], "흰머리독수리 보고서")
        self.assertEqual(out["guess_seconds"], 90)
        self.assertEqual(out["p50_seconds"], 90)
        self.assertEqual(out["p85_seconds"], 135)
        self.assertEqual(out["basis"], {"method": "guess", "samples": 0})
        self.assertNotIn("open_tasks", out)

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

    def test_calibrates_overestimating_bot(self):
        # 그록봇이 600초라고 했는데 매번 300초에 끝났다.
        for _ in range(5):
            self.start("보고서", guess=600, kind="writing", now=0)
            self.tte("stop", now=300)
        _, out = self.start("보고서", guess=600, kind="writing", now=1000)
        self.assertEqual(out["p50_seconds"], 300)
        self.assertEqual(out["basis"], {"method": "calibrated", "scope": "kind",
                                        "samples": 5, "ratio": 0.5})
        self.assertEqual(out["confidence"], "medium")

    def test_failed_and_stale_not_learned(self):
        for _ in range(5):
            self.start("실패", now=0)
            self.tte("stop", "--status", "failed", now=100)
        for _ in range(5):
            self.start("방치", now=0)
            self.tte("stop", now=store.STALE_SECONDS + 1)
        _, out = self.start("새 작업", now=100000)
        self.assertEqual(out["basis"]["method"], "guess")

    def test_stop_without_start_rejected(self):
        code, out = self.tte("stop")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "no_active_task")
        self.assertIn("tte start", out["hint"])

    def test_multiple_open_tasks(self):
        _, first = self.start("하나")
        _, second = self.start("둘")
        self.assertEqual(second["open_tasks"], [first["id"]])
        code, out = self.tte("stop")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "ambiguous_task")
        self.assertEqual(self.tte("stop", first["id"])[0], 0)
        self.assertEqual(self.tte("stop")[0], 0)

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

    def test_list(self):
        _, out = self.start(now=0)
        self.tte("wait", now=10)
        _, listed = self.tte("list", now=store.STALE_SECONDS + 1)
        self.assertEqual(listed["open"][0]["id"], out["id"])
        self.assertTrue(listed["open"][0]["waiting"])
        self.assertTrue(listed["open"][0]["stale"])

    def test_stats(self):
        self.assertEqual(self.tte("stats")[1], {"done": 0, "p85_hit_rate": None, "groups": []})
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

    def test_migrates_old_database(self):
        # 0.2.0이 만든 DB(guess_seconds 없음)에 기록이 남아 있어도 그대로 쓴다.
        conn = sqlite3.connect(Path(self.tmp.name) / "tte.db")
        conn.execute(store.SCHEMA.replace("    guess_seconds REAL,\n", ""))
        conn.execute(
            "INSERT INTO tasks (id, task, complexity, kind, status, started_at, ended_at,"
            " actual_seconds, p50_seconds, p85_seconds, method, samples)"
            " VALUES ('old', '예전', 'medium', 'other', 'done', 0, 50, 50, 600, 900, 'rule', 0)"
        )
        conn.commit()
        conn.close()
        code, out = self.start(guess=60)
        self.assertEqual(code, 0)
        self.assertEqual(out["basis"]["method"], "guess")
        self.assertEqual(self.tte("stats")[1]["done"], 1)

    def test_version(self):
        self.assertEqual(self.tte("--version")[1], {"version": "0.3.0"})


if __name__ == "__main__":
    unittest.main()
