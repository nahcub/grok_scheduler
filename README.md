# grok_scheduler

그록봇(Grokbot)용 **에이전트 작업 묶음배송**. 1~10분짜리 작업 때문에 기다리거나 작업 사이를 오가지 않도록, 작은 작업을 장바구니에 모았다가 예상 시간이 기준(기본 60분)에 차면 한 번에 출발시키고 약속한 시각에 한 번에 보고한다.

이 저장소에는 두 가지가 들어 있다.

- **`tte` CLI**: 작업 시간 예측 도구. 그록봇 VM에 설치해서 작업 시작·종료를 기록하고, 예상 시간(P50, P85)을 돌려준다. 기록이 쌓이면 규칙 기반 추정에서 기록 기반 백분위로 넘어간다.
- **그록봇 스킬 2개**: `tte`를 쓰는 규칙(`task-timer`)과 묶음배송 봇의 동작(`bundle-delivery`).

## 그록봇에 설치하기

그록봇 대화창에 지시문 블록을 그대로 붙여넣으면 된다.

| 하려는 것 | 문서 |
| --- | --- |
| `tte`와 `task-timer` 스킬만 설치 | [grokbot/INSTALL.md](grokbot/INSTALL.md) |
| 묶음배송 Bot까지 만들기(설치·스킬 등록·예약·동작 확인 포함) | [grokbot/CREATE_BOT.md](grokbot/CREATE_BOT.md) |

그록봇은 이 공개 저장소의 `main`에서 파일을 내려받는다. 스킬이나 코드를 고친 뒤에는 push하고 각 문서의 "업데이트" 블록을 보내야 반영된다.

## tte 사용법

모든 출력은 한 줄 JSON이다. 성공하면 종료 코드 0, 오류면 1이고 오류 출력에는 `error`와 `hint`가 들어 있다.

```bash
tte start "작업 설명" --complexity medium --kind writing   # 시작 기록 + 예측, id를 돌려줌
tte wait <id> --reason approval                            # 사람 응답 대기 시작
tte resume <id>                                            # 대기 끝 (대기 시간은 작업 시간에서 빠짐)
tte stop <id> [--status done|failed|cancelled]             # 종료 기록
tte estimate "작업 설명" --complexity light --kind research # 기록 없이 예측만
tte list                                                   # 진행 중인 작업
tte stats                                                  # 기록 요약
```

- `--complexity`: `light` / `medium` / `heavy` (기본 `medium`)
- `--kind`: `research` / `writing` / `coding` / `browser` / `data` / `other` (기본 `other`)
- 진행 중인 작업이 하나뿐이면 `wait`, `resume`, `stop`의 `<id>`를 생략할 수 있다.
- 시작 기록 없이 `stop`하면 거부한다.

### 예측 방식

1. 같은 `(kind, complexity)`의 완료 기록이 5건 이상이면 그 기록의 50·85번째 백분위를 쓴다.
2. 모자라면 같은 `complexity` 전체 기록을 본다.
3. 그것도 5건 미만이면 규칙을 쓴다: P50은 light 3분, medium 10분, heavy 25분, P85 = P50 × 1.5.

P85가 도착 약속 시간이다. 근거 기록 수에 따라 `confidence`가 `low`(5건 미만) / `medium`(5~19건) / `high`(20건 이상)로 나온다. 실패·취소된 작업과 6시간 넘게 열려 있던 작업은 학습에서 뺀다.

### 기록 위치

`TTE_HOME` → `/workspace/.tte` → `~/.tte` 순으로 정하고, 그 안의 `tte.db`(SQLite)에 남긴다.

## 개발

Python 3.11 이상, 표준 라이브러리만 쓴다.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e .
```

```bash
.venv/Scripts/python -m unittest discover -s tests
```

Linux/macOS에서는 `.venv/Scripts/` 대신 `.venv/bin/`을 쓴다. 손으로 시험할 때는 `TTE_HOME`을 임시 폴더로 둔다.

```
src/tte/
  cli.py        # 명령, JSON 출력
  store.py      # SQLite
  estimate.py   # 예측 (순수 함수)
grokbot/
  INSTALL.md, CREATE_BOT.md       # 그록봇에 붙여넣을 지시문
  skills/task-timer/SKILL.md
  skills/bundle-delivery/SKILL.md
docs/           # 구현 계획, 그록봇 조사 기록
```

설계 배경과 결정 이유는 [docs/cli-plan.md](docs/cli-plan.md)와 [docs/grokbot-research.md](docs/grokbot-research.md)에 있다.
