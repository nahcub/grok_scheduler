# grok_scheduler

그록봇(Grokbot)용 **에이전트 작업 묶음배송**. 1~10분짜리 작업 때문에 기다리거나 작업 사이를 오가지 않도록, 작은 작업을 장바구니에 모았다가 예상 시간이 기준(기본 60분)에 차면 한 번에 출발시키고 약속한 시각에 한 번에 보고한다.

이 저장소에는 두 가지가 들어 있다.

- **`tte` CLI**: 작업 시간 예측 도구. 그록봇 VM에 설치해서 작업 시작·종료를 기록하고, 예상 시간(P50, P85)을 돌려준다. 그록봇이 직접 추정한 시간에서 출발하고, 기록이 쌓이면 "실제 ÷ 추정" 비율로 보정한다.
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
tte start "작업 설명" --guess 120 --kind writing [--scope multi]   # 시작 기록 + 예측, id를 돌려줌
tte wait <id> --reason approval                                   # 사람 응답 대기 시작
tte resume <id>                                                   # 대기 끝 (대기 시간은 작업 시간에서 빠짐)
tte stop <id> [--status done|failed|cancelled]                    # 종료 기록
tte estimate "작업 설명" --guess 300 --kind research               # 기록 없이 예측만
tte list                                                          # 진행 중인 작업
tte stats                                                         # 기록 요약 (kind별, 동시 실행 수별)
tte gc [--older-than 21600]                                       # 방치된 열린 작업을 cancelled로 정리
```

- `--guess`(필수): 그록봇이 추정한 보통 걸릴 시간(초).
- `--kind`: `research` / `writing` / `coding` / `browser` / `data` / `other` (기본 `other`)
- `--scope`: `small`(기본) / `multi`. 여러 층(백엔드·프런트·DB·기존 테스트)을 함께 바꾸는 작업이면 `multi`. P85 여유를 더 둔다.
- `--complexity`는 0.2.0 이하와의 호환용으로 받기만 하고 예측에는 쓰지 않는다.
- 진행 중인 작업이 하나뿐이면 `wait`, `resume`, `stop`의 `<id>`를 생략할 수 있다. 환경변수 `TTE_AGENT`를 주면 같은 `TTE_AGENT`로 시작한 작업만 후보로 본다(서브에이전트 여럿이 같은 DB를 쓸 때).
- 시작 기록 없이 `stop`하면 거부한다. DB 잠금 같은 SQLite 오류도 `{"error":"db_error",...}` 한 줄로 나온다.

### 예측 방식 (0.4.0)

1. 완료 기록이 5건 미만이면 `--guess`를 그대로 P50으로 쓴다. P85 = P50 × 1.5(`multi`는 1.6).
2. 5건 이상이면 "실제 ÷ 추정" 비율로 보정한다(`basis.method: calibrated`, `scope: blend`).
   - 기본은 전체 기록의 비율이다.
   - 같은 `kind`의 비율을 표본 수 n만큼 섞는다: `n / (n + 5)` 비중. 표본이 3건이면 37%, 20건이면 80%만 그 kind 비율을 따른다. 0.3.0은 5건 미만이면 그 kind를 통째로 버렸다.
   - 추정 크기 구간(`short` 120초 미만 / `mid` 120~480초 / `long` 480초 이상)의 비율도 같은 방식으로 섞는다. 큰 작업은 비율이 작은 작업과 달라서다.
   - P50과 P85를 각각 이 방식으로 계산한다.
3. P85는 최소 P50 × 1.3(`multi`는 1.6)이다. 기록이 고르게 모여 비율 분포가 좁을 때도 여유를 둔다.

P85가 도착 약속 시간이다. 근거가 된 전체 기록 수에 따라 `confidence`가 `low`(5건 미만) / `medium`(5~19건) / `high`(20건 이상)로 나온다. `basis`에는 `kind_samples`, `all_samples`, `kind_weight`, `size_bucket`, `size_samples`, `size_weight`가 함께 나온다.

학습에서 빼는 기록: 실패·취소된 작업, 대기를 뺀 작업 시간이 6시간을 넘는 작업(기록을 빠뜨린 것으로 본다). 승인을 오래 기다렸어도 실제 작업 시간이 짧으면 학습에 들어간다.

### 기록 위치

`TTE_HOME` → `/workspace/.tte` → `~/.tte` 순으로 정하고, 그 안의 `tte.db`(SQLite)에 남긴다. 스키마 버전은 `PRAGMA user_version`으로 관리하고, 0.3.0 이하 DB는 처음 열 때 자동으로 바뀐다(기존 기록 유지). 0.4.0부터 작업마다 `concurrency`(시작 때 함께 열려 있던 작업 수, 자기 포함), `owner`(`TTE_AGENT`), `scope`를 저장한다.

## 개발

Python 3.11 이상, 표준 라이브러리만 쓴다.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e .
```

테스트는 저장소 루트에서 실행한다. `tests/__init__.py`가 `src`를 경로에 넣으므로 설치하지 않아도 된다.

```bash
python -m unittest
```

`PYTHONPATH=src python3 -m unittest discover -s tests`도 같은 테스트를 돌린다. Linux/macOS에서는 `.venv/Scripts/` 대신 `.venv/bin/`을 쓴다. 손으로 시험할 때는 `TTE_HOME`을 임시 폴더로 둔다.

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
