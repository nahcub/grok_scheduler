import contextlib
import io
import json
import os
import tempfile
import unittest
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

    def test_start_returns_rule_estimate(self):
        code, out = self.tte("start", "보고서 작성", "--complexity", "heavy", "--kind", "research")
        self.assertEqual(code, 0)
        self.assertEqual(out["task"], "보고서 작성")
        self.assertEqual(out["p50_seconds"], 1500)
        self.assertEqual(out["p85_seconds"], 2250)
        self.assertEqual(out["basis"], {"method": "rule", "samples": 0})
        self.assertNotIn("open_tasks", out)

    def test_wait_time_excluded_from_actual(self):
        _, out = self.tte("start", "작업", now=0)
        task_id = out["id"]
        self.tte("wait", now=100)
        _, out = self.tte("resume", now=160)
        self.assertEqual(out["waited_seconds"], 60)
        _, out = self.tte("stop", task_id, now=400)
        self.assertEqual(out["actual_seconds"], 340)
        self.assertEqual(out["waited_seconds"], 60)

    def test_stop_while_waiting_closes_wait(self):
        self.tte("start", "작업", now=0)
        self.tte("wait", now=100)
        _, out = self.tte("stop", now=300)
        self.assertEqual(out["waited_seconds"], 200)
        self.assertEqual(out["actual_seconds"], 100)

    def test_history_replaces_rule(self):
        for actual in (100, 200, 300, 400, 500):
            self.tte("start", "조사", "--kind", "research", now=0)
            self.tte("stop", now=actual)
        _, out = self.tte("start", "조사", "--kind", "research", now=1000)
        self.assertEqual(out["p50_seconds"], 300)
        self.assertEqual(out["basis"], {"method": "history", "scope": "kind", "samples": 5})
        self.assertEqual(out["confidence"], "medium")

    def test_failed_and_stale_not_learned(self):
        for _ in range(5):
            self.tte("start", "실패", now=0)
            self.tte("stop", "--status", "failed", now=100)
        for _ in range(5):
            self.tte("start", "방치", now=0)
            self.tte("stop", now=store.STALE_SECONDS + 1)
        _, out = self.tte("start", "새 작업", now=100000)
        self.assertEqual(out["basis"]["method"], "rule")

    def test_stop_without_start_rejected(self):
        code, out = self.tte("stop")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "no_active_task")
        self.assertIn("tte start", out["hint"])

    def test_multiple_open_tasks(self):
        _, first = self.tte("start", "하나")
        _, second = self.tte("start", "둘")
        self.assertEqual(second["open_tasks"], [first["id"]])
        code, out = self.tte("stop")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "ambiguous_task")
        code, _ = self.tte("stop", first["id"])
        self.assertEqual(code, 0)
        code, _ = self.tte("stop")
        self.assertEqual(code, 0)

    def test_closed_and_unknown_ids(self):
        _, out = self.tte("start", "작업")
        self.tte("stop", out["id"])
        self.assertEqual(self.tte("stop", out["id"])[1]["error"], "task_closed")
        self.assertEqual(self.tte("stop", "nope")[1]["error"], "unknown_task")

    def test_wait_resume_errors(self):
        self.tte("start", "작업")
        self.assertEqual(self.tte("resume")[1]["error"], "not_waiting")
        self.tte("wait")
        self.assertEqual(self.tte("wait")[1]["error"], "already_waiting")

    def test_bad_arguments_are_json(self):
        code, out = self.tte("start", "작업", "--complexity", "huge")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "bad_arguments")
        self.assertEqual(self.tte()[1]["error"], "bad_arguments")
        self.assertEqual(self.tte("start", "  ")[1]["error"], "empty_task")

    def test_list_and_stats(self):
        _, out = self.tte("start", "작업", now=0)
        self.tte("wait", now=10)
        _, listed = self.tte("list", now=store.STALE_SECONDS + 1)
        self.assertEqual(listed["open"][0]["id"], out["id"])
        self.assertTrue(listed["open"][0]["waiting"])
        self.assertTrue(listed["open"][0]["stale"])

        _, stats = self.tte("stats")
        self.assertEqual(stats, {"done": 0, "p85_hit_rate": None, "groups": []})

    def test_stats_groups(self):
        for actual in (100, 1000):
            self.tte("start", "조사", "--kind", "research", now=0)
            self.tte("stop", now=actual)
        _, stats = self.tte("stats")
        self.assertEqual(stats["done"], 2)
        # medium 규칙의 P85는 900초라서 1000초 작업은 예측을 넘긴다.
        self.assertEqual(stats["p85_hit_rate"], 0.5)
        self.assertEqual(stats["groups"][0]["kind"], "research")
        self.assertEqual(stats["groups"][0]["samples"], 2)

    def test_estimate_does_not_record(self):
        code, out = self.tte("estimate", "조사", "--complexity", "light", "--kind", "research")
        self.assertEqual(code, 0)
        self.assertNotIn("id", out)
        self.assertEqual(out["p50_seconds"], 180)
        self.assertEqual(self.tte("list")[1], {"open": []})
        self.assertEqual(self.tte("estimate", " ")[1]["error"], "empty_task")

    def test_estimate_uses_history(self):
        for actual in (100, 200, 300, 400, 500):
            self.tte("start", "조사", "--kind", "research", now=0)
            self.tte("stop", now=actual)
        _, out = self.tte("estimate", "조사", "--kind", "research")
        self.assertEqual(out["p50_seconds"], 300)
        self.assertEqual(out["basis"]["method"], "history")

    def test_version(self):
        self.assertEqual(self.tte("--version")[1], {"version": "0.2.0"})


if __name__ == "__main__":
    unittest.main()
