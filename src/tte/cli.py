"""tte 명령. 모든 출력은 한 줄 JSON이고, 성공하면 0, 오류면 1로 끝난다."""

import argparse
import json
import os
import sqlite3
import sys
import time

from . import __version__, store
from .estimate import estimate, percentile, size_bucket
from .store import TteError

COMPLEXITIES = ("light", "medium", "heavy")
KINDS = ("research", "writing", "coding", "browser", "data", "other")
STATUSES = ("done", "failed", "cancelled")
SCOPES = ("small", "multi")
# stats의 동시 실행 구간: (이름, 하한, 상한). 상한 포함.
CONCURRENCY_BUCKETS = (("1", 1, 1), ("2-3", 2, 3), ("4+", 4, float("inf")))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TteError("bad_arguments", message, "tte --help 로 사용법을 확인하세요")


def seconds(text):
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value <= 0:
        raise argparse.ArgumentTypeError(f"1 이상의 초 단위 정수여야 함: {text}")
    return value


def current_owner():
    """같은 VM에서 여러 에이전트가 tte를 쓸 때 TTE_AGENT로 자기 작업을 구분한다."""
    return os.environ.get("TTE_AGENT") or None


def build_parser():
    parser = Parser(prog="tte", description="그록봇용 작업 시간 예측 CLI")
    parser.add_argument("--version", action="store_true", help="버전 출력")
    sub = parser.add_subparsers(dest="command")

    for name, help_text in (("start", "작업 시작 기록 + 예상 시간"),
                            ("estimate", "기록 없이 예상 시간만")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("task", help="작업 설명")
        p.add_argument("--guess", type=seconds, required=True,
                       help="그록봇이 추정한 보통 걸릴 시간(초)")
        p.add_argument("--kind", choices=KINDS, default="other")
        p.add_argument("--scope", choices=SCOPES, default="small",
                       help="multi: 여러 층(백엔드·프런트·DB 등)을 함께 바꾸는 작업. P85 여유를 더 둔다")
        # 0.2.0 이하와의 호환용 태그. 예측에는 쓰지 않는다.
        p.add_argument("--complexity", choices=COMPLEXITIES, default="medium",
                       help=argparse.SUPPRESS)

    p = sub.add_parser("wait", help="대기 시작(승인, 사람 응답 등)")
    p.add_argument("id", nargs="?")
    p.add_argument("--reason", default="approval")

    p = sub.add_parser("resume", help="대기 끝")
    p.add_argument("id", nargs="?")

    p = sub.add_parser("stop", help="작업 종료 기록")
    p.add_argument("id", nargs="?")
    p.add_argument("--status", choices=STATUSES, default="done")

    sub.add_parser("list", help="진행 중인 작업")
    sub.add_parser("stats", help="기록 요약")

    p = sub.add_parser("gc", help="방치된 열린 작업을 cancelled로 정리")
    p.add_argument("--older-than", type=seconds, default=store.STALE_SECONDS,
                   help="대기를 뺀 작업 시간이 이보다 길면 정리(초)")
    return parser


def resolve(conn, task_id):
    """id가 없으면 같은 owner의 진행 중인 작업이 하나일 때만 그 작업을 고른다."""
    if task_id:
        row = store.get_task(conn, task_id)
        if row is None:
            raise TteError("unknown_task", f"{task_id} 작업이 없음",
                           "tte list 로 진행 중인 작업 id를 확인하세요")
        if row["status"] != "open":
            raise TteError("task_closed", f"{task_id} 작업은 이미 끝남",
                           '새 작업이면 tte start "작업 설명"을 실행하세요')
        return row
    rows = store.open_tasks(conn, owner=current_owner())
    if not rows:
        raise TteError("no_active_task", "진행 중인 작업이 없음",
                       '먼저 tte start "작업 설명"을 실행하세요')
    if len(rows) > 1:
        ids = ", ".join(r["id"] for r in rows)
        raise TteError("ambiguous_task", f"진행 중인 작업이 여러 개임: {ids}",
                       "id를 지정하세요. 예: tte stop <id>")
    return rows[0]


def predict(conn, args):
    task = args.task.strip()
    if not task:
        raise TteError("empty_task", "작업 설명이 비어 있음",
                       f'tte {args.command} "작업 설명" 형식으로 다시 실행하세요')
    bucket, lo, hi = size_bucket(args.guess)
    est = estimate(
        args.guess,
        store.ratios(conn, args.kind),
        store.ratios(conn),
        store.ratios(conn, guess_range=(lo, hi)),
        scope=args.scope,
        bucket=bucket,
    )
    return task, est


def cmd_estimate(conn, args, now):
    task, est = predict(conn, args)
    return {"task": task, "kind": args.kind, "guess_seconds": args.guess,
            "scope": args.scope, **est}


def cmd_start(conn, args, now):
    task, est = predict(conn, args)
    owner = current_owner()
    with store.write(conn):
        others = [r["id"] for r in store.open_tasks(conn)]
        task_id = store.new_id(conn)
        # 이 작업을 포함해 동시에 열려 있는 작업 수. 1이면 단독 실행.
        concurrency = len(others) + 1
        store.insert_task(conn, task_id=task_id, task=task, complexity=args.complexity,
                          kind=args.kind, guess=args.guess, now=now, estimate=est,
                          concurrency=concurrency, owner=owner, scope=args.scope)
    out = {"id": task_id, "task": task, "kind": args.kind,
           "guess_seconds": args.guess, "scope": args.scope, **est,
           "concurrency": concurrency}
    if owner:
        out["owner"] = owner
    if others:
        out["open_tasks"] = others
    return out


def cmd_wait(conn, args, now):
    with store.write(conn):
        row = resolve(conn, args.id)
        if row["wait_started_at"] is not None:
            raise TteError("already_waiting", f"{row['id']} 작업은 이미 대기 중",
                           f"대기가 끝났으면 tte resume {row['id']} 을 실행하세요")
        store.start_wait(conn, row["id"], args.reason, now)
    return {"id": row["id"], "waiting": True, "reason": args.reason}


def cmd_resume(conn, args, now):
    with store.write(conn):
        row = resolve(conn, args.id)
        if row["wait_started_at"] is None:
            raise TteError("not_waiting", f"{row['id']} 작업은 대기 중이 아님",
                           f"대기를 시작하려면 tte wait {row['id']} 을 실행하세요")
        waited = store.end_wait(conn, row["id"], now)
    return {"id": row["id"], "waiting": False, "waited_seconds": round(waited)}


def cmd_stop(conn, args, now):
    with store.write(conn):
        row = store.finish(conn, resolve(conn, args.id)["id"], args.status, now)
    return {
        "id": row["id"],
        "status": row["status"],
        "actual_seconds": round(row["actual_seconds"]),
        "waited_seconds": round(row["waited_seconds"]),
        "p50_seconds": row["p50_seconds"],
        "p85_seconds": row["p85_seconds"],
    }


def cmd_list(conn, args, now):
    out = []
    for r in store.open_tasks(conn):
        active = store.active_seconds(r, now)
        item = {
            "id": r["id"],
            "task": r["task"],
            "elapsed_seconds": round(now - r["started_at"]),
            "active_seconds": round(active),
            "waiting": r["wait_started_at"] is not None,
            "stale": active > store.STALE_SECONDS,
        }
        if r["owner"]:
            item["owner"] = r["owner"]
        out.append(item)
    return {"open": out}


def cmd_gc(conn, args, now):
    with store.write(conn):
        stale = store.cancel_stale(conn, now, args.older_than)
    return {"cancelled": [
        {"id": r["id"], "task": r["task"], "active_seconds": round(store.active_seconds(r, now))}
        for r in stale
    ]}


def concurrency_bucket(n):
    if n is None:
        return "unknown"
    for name, lo, hi in CONCURRENCY_BUCKETS:
        if lo <= n <= hi:
            return name
    return CONCURRENCY_BUCKETS[-1][0]


def cmd_stats(conn, args, now):
    rows = store.done_tasks(conn)
    hits = sum(1 for r in rows if r["actual_seconds"] <= r["p85_seconds"])
    groups = []
    for kind in sorted({r["kind"] for r in rows}):
        actuals = [r["actual_seconds"] for r in rows if r["kind"] == kind]
        ratios = store.ratios(conn, kind)
        groups.append({
            "kind": kind,
            "samples": len(actuals),
            "actual_p50_seconds": round(percentile(actuals, 0.5)),
            # 1보다 크면 그록봇이 짧게, 작으면 길게 추정하는 버릇이 있다.
            "guess_ratio_p50": round(percentile(ratios, 0.5), 2) if ratios else None,
        })
    by_concurrency = {}
    for r in rows:
        by_concurrency.setdefault(concurrency_bucket(r["concurrency"]), []).append(r)
    order = [name for name, _, _ in CONCURRENCY_BUCKETS] + ["unknown"]
    concurrency = []
    for name in order:
        bucket_rows = by_concurrency.get(name)
        if not bucket_rows:
            continue
        ratios = [r["actual_seconds"] / r["guess_seconds"] for r in bucket_rows
                  if r["guess_seconds"]]
        concurrency.append({
            "concurrency": name,
            "samples": len(bucket_rows),
            "guess_ratio_p50": round(percentile(ratios, 0.5), 2) if ratios else None,
            "p85_hit_rate": round(sum(1 for r in bucket_rows
                                      if r["actual_seconds"] <= r["p85_seconds"])
                                  / len(bucket_rows), 2),
        })
    return {
        "done": len(rows),
        "p85_hit_rate": round(hits / len(rows), 2) if rows else None,
        "groups": groups,
        "concurrency": concurrency,
    }


COMMANDS = {
    "estimate": cmd_estimate, "start": cmd_start, "wait": cmd_wait, "resume": cmd_resume,
    "stop": cmd_stop, "list": cmd_list, "stats": cmd_stats, "gc": cmd_gc,
}


def run(argv, now):
    args = build_parser().parse_args(argv)
    if args.version:
        return {"version": __version__}
    if not args.command:
        raise TteError("bad_arguments", "명령이 없음", "tte --help 로 사용법을 확인하세요")
    conn = store.connect()
    try:
        return COMMANDS[args.command](conn, args, now)
    finally:
        conn.close()


def main(argv=None, now=None):
    try:
        out, code = run(argv, time.time() if now is None else now), 0
    except TteError as e:
        out, code = e.to_dict(), 1
    except sqlite3.Error as e:
        # 잠금 시간 초과 등. 한 줄 JSON 약속은 DB 오류에서도 지킨다.
        out, code = {"error": "db_error", "message": str(e), "hint": "잠시 후 다시 실행"}, 1
    # Windows 기본 인코딩(cp1252 등)에서도 한글이 깨지지 않게 한다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
