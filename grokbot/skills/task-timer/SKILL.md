---
name: task-timer
description: >-
  Use before starting ANY task and right after finishing it. You estimate how
  long the task will take, pass it to the `tte` CLI, tell the owner the
  calibrated estimate (P50/P85), and log the actual duration so tte can learn
  how far off your estimates usually are.
---
# Task timer (tte)

모든 작업은 시작 전에 `tte start`, 끝난 뒤 `tte stop`을 실행한다. 출력은 한 줄 JSON이다.

## 1. 시작할 때

먼저 **네가 직접 이 작업이 보통 몇 초 걸릴지 추정**해서 `--guess`로 넘긴다. 필수 인자다.

```bash
tte start "작업 설명" --guess <초> --kind <research|writing|coding|browser|data|other>
```

추정 요령:

- 여유를 붙이지 말고 **보통 걸릴 시간**을 말한다. 여유는 tte가 P85로 따로 계산한다.
- 일부러 맞추려고 애쓰지 않아도 된다. tte가 실제 시간과 비교해서 네가 늘 길게 또는 짧게 말하는 버릇을 자동으로 보정한다.
- 처음 기준으로 삼을 만한 값(네 경험이 다르면 네 경험을 따른다):

| 작업 | 보통 |
| --- | --- |
| 짧은 답, 한두 문단 글 | 30~90초 |
| 조사 없이 쓰는 1~2쪽 보고서 | 1~3분 |
| 웹 검색 몇 번 + 요약 | 3~8분 |
| 여러 사이트를 오가며 조작·입력(브라우저) | 5~20분 |
| 코드 수정 + 테스트 | 5~30분 |

- `kind`: research(조사), writing(문서 작성), coding(코드), browser(사이트 조작·입력), data(데이터 처리), other.
- 백엔드·프런트·DB·기존 테스트처럼 **여러 층을 한꺼번에 바꾸는 작업**이면 `--scope multi`를 붙인다. 이런 작업은 늦어질 때가 많아서 tte가 P85 여유를 더 둔다.

출력 예:

```json
{"id":"a3f9c1","task":"...","kind":"writing","guess_seconds":90,"scope":"small","p50_seconds":90,"p85_seconds":135,"basis":{"method":"guess","samples":0},"confidence":"low","concurrency":1}
```

- `id`를 기억한다. 끝날 때 쓴다.
- 사용자에게는 `p50_seconds`와 `p85_seconds`를 말한다(네 `--guess`가 아니라 보정된 값). 예: "보통 1분 30초, 늦어도 2분 15초 안에 드릴게요."
- `basis.method`가 `guess`면 아직 기록이 적어 네 추정을 그대로 쓴 것이다. `calibrated`면 기록으로 보정한 값이고, `basis.ratio`는 실제 ÷ 네 추정의 보정된 중앙값이다. 같은 `kind` 기록이 적으면(`kind_weight`가 작으면) 전체 기록 쪽으로 더 기운다.

### 시작하지 않고 예상만 볼 때

장바구니에 담을 때처럼 아직 실행하지 않는 작업은 `tte estimate`를 쓴다. 인자와 출력은 `start`와 같고 `id`가 없으며 아무것도 기록하지 않는다.

```bash
tte estimate "작업 설명" --guess 120 --kind writing
```

## 2. 사람을 기다릴 때

승인 요청이나 질문으로 사람 답을 기다리기 직전과 직후에 기록한다. 기다린 시간은 작업 시간에서 빠진다.

```bash
tte wait <id> --reason approval
tte resume <id>
```

## 3. 끝날 때

```bash
tte stop <id>                    # 정상 완료
tte stop <id> --status failed    # 실패
tte stop <id> --status cancelled # 취소
```

## 4. 오류가 나면

출력에 `error`가 있으면 `hint`에 적힌 대로 한다.

- `bad_arguments`이고 `--guess` 이야기가 있으면: 추정한 초를 넣어 다시 실행한다.
- `no_active_task`: 시작 기록이 없다. 다음 작업부터는 시작 전에 `tte start`를 실행한다.
- `ambiguous_task`: 진행 중인 작업이 여러 개다. `<id>`를 붙여 다시 실행한다.
- `db_error`: 기록 파일이 잠시 잠겨 있다. 몇 초 뒤 같은 명령을 다시 실행한다.
- 열린 작업이 기억나지 않으면 `tte list`로 확인한다. `stale: true`인 작업은 `tte stop <id> --status cancelled`로 닫거나, `tte gc`로 한 번에 정리한다.

## 5. 동시 작업

작업을 여러 개 동시에 돌려도 된다. 작업마다 따로 `tte start`를 하고, `wait`/`resume`/`stop`에는 반드시 `<id>`를 붙인다. tte가 시작 때 함께 열려 있던 작업 수를 `concurrency`로 기록한다.

서브에이전트나 다른 봇이 같은 컴퓨터에서 tte를 쓰면 각자 `TTE_AGENT=<이름>`을 붙여 실행한다. 그러면 `<id>` 없이 실행한 `stop`/`wait`/`resume`이 자기 작업만 찾는다.

```bash
TTE_AGENT=sub-1 tte start "테스트 추가" --guess 120 --kind coding
TTE_AGENT=sub-1 tte stop
```

## 6. 내 추정 버릇 보기

`tte stats`의 `groups[].guess_ratio_p50`이 1보다 크면 그 종류 작업을 짧게, 작으면 길게 추정하는 버릇이 있다는 뜻이다. `concurrency[]`는 동시에 돌린 작업 수별(1 / 2-3 / 4+)로 같은 값을 보여 준다.
