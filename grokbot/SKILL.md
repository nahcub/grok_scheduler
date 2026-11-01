---
name: task-timer
description: >-
  Use before starting ANY task and right after finishing it. Records the task
  with the `tte` CLI to get an estimated duration (P50/P85) to tell the owner,
  and logs the actual duration so future estimates improve.
---
# Task timer (tte)

모든 작업은 시작 전에 `tte start`, 끝난 뒤 `tte stop`을 실행한다. 출력은 한 줄 JSON이다.

## 1. 시작할 때

작업을 보고 복잡도와 종류를 판단해서 넘긴다.

```bash
tte start "작업 설명" --complexity <light|medium|heavy> --kind <research|writing|coding|browser|data|other>
```

- `light`: 몇 단계면 끝나는 일. `medium`: 보통. `heavy`: 여러 사이트·파일을 오가거나 긴 산출물을 만드는 일.
- `kind`: research(조사), writing(문서 작성), coding(코드), browser(사이트 조작·입력), data(데이터 처리), other.

출력 예:

```json
{"id":"a3f9c1","task":"...","p50_seconds":1200,"p85_seconds":1800,"basis":{"method":"rule","samples":0},"confidence":"low"}
```

- `id`를 기억한다. 끝날 때 쓴다.
- 사용자에게 `p50_seconds`와 `p85_seconds`를 분 단위로 말한다. 예: "보통 20분, 늦어도 30분 안에 드릴게요."
- `p85_seconds`가 약속 시간이다. `confidence`가 `low`면 "아직 기록이 적어서 대략적인 예상"이라고 덧붙인다.

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

- `no_active_task`: 시작 기록이 없다. 다음 작업부터는 시작 전에 `tte start`를 실행한다.
- `ambiguous_task`: 진행 중인 작업이 여러 개다. `<id>`를 붙여 다시 실행한다.
- 열린 작업이 기억나지 않으면 `tte list`로 확인한다.

## 5. 동시 작업

작업을 여러 개 동시에 돌려도 된다. 작업마다 따로 `tte start`를 하고, `wait`/`resume`/`stop`에는 반드시 `<id>`를 붙인다.
