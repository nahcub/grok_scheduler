# tte CLI 구현 계획

작성일: 2026-11-01. 그록봇 VM에 설치해서 쓰는 작업 시간 예측 CLI(`tte`)의 구현 계획이다. 배경과 결정 이유는 [CLAUDE.md](../CLAUDE.md)와 [grokbot-research.md](grokbot-research.md) 7절에 있다.

> **0.3.0 변경**: 3절·5절의 "복잡도 3단계 + 규칙표" 방식은 바뀌었다. 간단한 보고서도 medium(10분)으로 잡히는 문제가 있어서, 이제 그록봇이 `--guess <초>`(필수)로 직접 추정을 넘기고, 기록이 쌓이면 같은 `kind`(5건 미만이면 전체)의 "실제 ÷ 추정" 비율 백분위로 보정한다(`basis.method`: `guess` → `calibrated`). `--complexity`는 호환용으로만 받는다. 아래 본문은 처음 계획 그대로 둔다.

## 1. 목표

- 그록봇이 작업을 시작할 때 `tte start` 한 줄로 예상 시간(P50, P85)을 받는다.
- 끝날 때 `tte stop` 한 줄로 실제 시간을 남긴다.
- 기록이 쌓이면 규칙 기반 추정에서 기록 기반 백분위로 자동으로 넘어간다.

## 2. 기술 선택

| 항목 | 선택 | 이유 |
| --- | --- | --- |
| 언어 | Python 3.13 | 그록봇 VM에 설치돼 있다고 확인함 |
| 외부 의존성 | 없음(표준 라이브러리만) | 설치 실패 가능성을 없앤다 |
| 저장소 | SQLite (`sqlite3` 표준 모듈) | 그록봇이 백그라운드 작업을 2~4개 동시에 돌리므로 동시 쓰기에 안전해야 한다 |
| 저장 위치 | `/workspace/.tte/tte.db` | 그록봇이 작업 파일을 두는 곳. 환경변수 `TTE_HOME`으로 바꿀 수 있게 한다 |
| 설치 | venv + `pip install git+<저장소 URL>` | 그록봇이 venv `pip install`과 `git clone`을 할 수 있다고 확인함 |
| 테스트 | `unittest` | 의존성 없이 VM에서도 바로 돌릴 수 있다 |

## 3. 역할 나누기: 그록봇은 판단, 도구는 숫자

- **그록봇(LLM)**: 작업을 보고 `complexity`(light/medium/heavy)와 `kind`(작업 종류)를 판단해서 인자로 넘긴다. 키워드 규칙보다 LLM이 작업을 더 잘 이해한다.
- **tte**: 넘겨받은 특징으로 같은 종류의 과거 기록을 찾아 백분위를 계산한다. 인자가 없으면 기본값(medium, other)을 쓴다.

`kind` 초안: `research`(조사), `writing`(문서 작성), `coding`(코드), `browser`(사이트 조작·입력), `data`(데이터 처리), `other`.

## 4. 명령

모든 출력은 **한 줄 JSON**이다. 성공하면 종료 코드 0, 오류면 1.

| 명령 | 하는 일 | 출력 예 |
| --- | --- | --- |
| `tte estimate "설명" [--complexity heavy] [--kind research]` | 기록 없이 예측만(장바구니에 담을 때) | `start` 출력에서 `id`를 뺀 것 |
| `tte start "설명" [--complexity heavy] [--kind research]` | 작업 시작 기록 + 예측 | `{"id":"a3f","task":"...","complexity":"heavy","kind":"research","p50_seconds":1200,"p85_seconds":1800,"basis":{"method":"rule","samples":0},"confidence":"low"}` |
| `tte wait <id> [--reason approval]` | 대기 시작(승인, 사람 응답 등) | `{"id":"a3f","waiting":true,"reason":"approval"}` |
| `tte resume <id>` | 대기 끝 | `{"id":"a3f","waiting":false,"waited_seconds":95}` |
| `tte stop <id> [--status done\|failed\|cancelled]` | 종료 기록 | `{"id":"a3f","status":"done","actual_seconds":1450,"waited_seconds":95,"p50_seconds":1200,"p85_seconds":1800}` |
| `tte list` | 진행 중인 작업 목록 | `{"open":[{"id":"a3f","task":"...","elapsed_seconds":300}]}` |
| `tte stats` | 사람이 보는 요약(종류·복잡도별 건수, 중앙값, 예측 적중률) | 한 줄 JSON |

- 진행 중인 작업이 하나뿐이면 `wait`, `resume`, `stop`에서 `<id>`를 생략할 수 있다. 여러 개면 `<id>`가 필수다.
- `actual_seconds`는 **대기 시간을 뺀 작업 시간**이다. 예측과 학습도 이 값으로 한다. 사람을 기다린 시간이 추정을 흔들지 않게 하기 위해서다.

## 5. 예측 방식

1. **규칙(초기)**: 복잡도별 기본표로 P50을 정하고 P85 = P50 × 1.5로 둔다. 초기값은 임시로 light 180초, medium 600초, heavy 1500초로 두고, 며칠 써 본 기록으로 고친다.
2. **기록 기반**: 같은 `(kind, complexity)`의 `done` 기록이 5건 이상이면 그 기록의 실제 50번째, 85번째 백분위를 쓴다. 5건 미만이면 같은 `complexity` 전체 기록을 보고, 그것도 5건 미만이면 규칙으로 돌아간다.
3. **신뢰도**: 근거 기록이 5건 미만이면 `low`, 5~19건이면 `medium`, 20건 이상이면 `high`.

`failed`, `cancelled`로 끝난 작업은 학습에서 뺀다.

## 6. 빠뜨림 방지 장치

- 없는 `<id>`로 `stop`하거나, 진행 중인 작업이 없는데 `stop`하면 거부한다: `{"error":"no_active_task","hint":"먼저 tte start \"작업 설명\"을 실행하세요"}`.
- `start` 때 이미 열린 작업이 있으면 거부하지 않고 출력에 `open_tasks`를 덧붙인다(동시 작업은 정상이므로).
- 시작한 지 6시간이 넘었는데 열려 있는 작업은 `list`에서 `stale: true`로 표시하고 학습에서 뺀다.

## 7. 그록봇 쪽 설정

- **스킬**: `/home/box/agent-data/workflows/task-timer/SKILL.md`. 프런트매터 `description`에 "작업을 시작하기 전과 끝낸 뒤에 항상 사용"이라고 적고, 본문에 `start` → (승인 대기 시 `wait`/`resume`) → `stop` 절차와 사용자에게 P50·P85를 말하는 방법을 쓴다. 초안은 저장소의 `grokbot/skills/task-timer/SKILL.md`로 관리한다.
- **봇 프로필 description**: "모든 작업은 시작 전에 `tte start`, 끝난 뒤 `tte stop`" 한 줄을 넣는다.

## 8. 저장소 구조 (예정)

```
pyproject.toml          # 진입점 tte = tte.cli:main
src/tte/
  cli.py                # 인자 파싱, JSON 출력, 오류 처리
  store.py              # SQLite 스키마와 읽기·쓰기
  estimate.py           # 규칙표, 백분위 계산 (순수 함수)
tests/
  test_estimate.py
  test_cli.py           # 임시 TTE_HOME으로 명령 흐름 시험
grokbot/
  SKILL.md              # 그록봇에 등록할 스킬 초안
  INSTALL.md            # 그록봇에게 붙여넣을 설치 지시문
```

## 9. 진행 순서

1. **뼈대**: git 저장소, `pyproject.toml`, `tte --version`이 도는 상태.
2. **저장과 기본 흐름**: SQLite 스키마, `start`/`stop`/`list`. 이 단계의 `start`는 규칙 기반 예측만 낸다.
3. **대기 시간**: `wait`/`resume`, `actual_seconds`에서 대기 시간 빼기.
4. **기록 기반 예측**: 백분위 계산, 단계별 대체(kind+complexity → complexity → 규칙), 신뢰도.
5. **빠뜨림 방지와 오류**: 6절의 검사, 모든 오류를 JSON으로.
6. **테스트**: 예측 계산, 대기 시간 계산, 동시 작업, 오류 경우.
7. **그록봇 문서**: `SKILL.md`, `INSTALL.md`, `tte stats`.
8. **그록봇에서 실제 검증**: GitHub에 올리고 그록봇에게 설치시킨 뒤 확인한다.
   - 설치하고 실행할 수 있는가
   - 실제 작업에서 스킬이 매번 불려 와 `start`/`stop`이 남는가
9. **보정**: 며칠 쓴 기록으로 규칙표 초기값과 P85 배수를 고친다.

1~7은 이 PC에서 할 수 있고, 8~9는 그록봇 계정이 필요하다.

## 10. 정해야 할 것

- **GitHub 저장소 공개 여부**: 공개면 그록봇이 바로 설치할 수 있다. 비공개면 그록봇 VM에 GitHub 인증을 해 줘야 한다.
- **규칙표 초기값**: 위의 180/600/1500초는 임시값이다. 그록봇 담당 팀원이 체감 시간으로 먼저 조정하면 좋다.
- **`kind` 목록**: 그록봇이 실제로 받는 작업 종류에 맞게 팀원과 정한다.
