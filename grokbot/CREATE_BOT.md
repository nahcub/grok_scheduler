# 묶음배송 봇 만들기

그록봇 메인 Bot과의 대화에 아래 블록을 그대로 붙여넣는다. tte 설치, 스킬 2개 등록, 새 Bot 생성, 예약 설정, 동작 확인까지 한 번에 한다.

- 스킬 원본: [skills/task-timer/SKILL.md](skills/task-timer/SKILL.md), [skills/bundle-delivery/SKILL.md](skills/bundle-delivery/SKILL.md)
- 그록봇은 이 공개 저장소에서 파일을 내려받는다. 스킬을 고친 뒤에는 `main`에 push하고 "스킬 업데이트" 블록을 보내야 반영된다.

```text
새 Bot을 하나 만들고 필요한 도구와 스킬을 설치해 줘. 단계마다 결과를 [확인함] / [실패]로 알려 줘. 실패하면 멈추고 이유와 출력을 보여 줘.

## 1. tte 설치 (이미 있으면 업데이트)
python3 -m venv /workspace/.venvs/tte   # 이미 있으면 건너뛰기
/workspace/.venvs/tte/bin/pip install --upgrade "git+https://github.com/nahcub/grok_scheduler.git"
ln -sf /workspace/.venvs/tte/bin/tte /usr/local/bin/tte   # 권한이 없으면 ~/.local/bin/tte 에 링크하고 PATH에 추가
tte --version   → {"version":"0.3.0"} 이상이어야 해

## 2. 스킬 2개 등록
for s in task-timer bundle-delivery; do
  mkdir -p /home/box/agent-data/workflows/$s
  curl -fsSL https://raw.githubusercontent.com/nahcub/grok_scheduler/main/grokbot/skills/$s/SKILL.md -o /home/box/agent-data/workflows/$s/SKILL.md
done
- task-timer: 모든 봇이 작업 시간을 기록할 때 쓰는 스킬
- bundle-delivery: 새로 만들 "묶음배송" Bot만 쓰는 스킬. 다른 봇은 따르지 않는다.

## 3. 상태 파일 준비 (없을 때만)
mkdir -p /workspace/.bundle
/workspace/.bundle/state.json 이 없으면 아래 내용으로 만들어 줘:
{"settings":{},"cart_override":null,"cart":[],"backlog":[],"deliveries":[]}
(settings를 비워 두면 묶음배송 Bot이 첫 대화에서 시간 설정을 물어본다.)

## 4. 새 Bot 만들기
- 이름: 묶음배송
- 프로필 description:
  "작업 묶음배송 비서. 모든 작업 요청은 bundle-delivery 스킬을 따른다. 바로 실행하지 않고 tte estimate로 예상 시간을 재서 장바구니에 담고, 합계가 주인이 정한 기준(기본 60분)에 차거나, 주인이 '즉시 배송'이라고 하거나, 주인이 정한 시각이 되면 한 번에 출발한다. 실행하는 작업마다 task-timer 스킬대로 tte start / tte stop을 기록한다. 급행 요청만 즉시 실행한다. 약속 시각 전에는 결과를 보고하지 않고, 승인·오류·방향 질문처럼 사람 입력이 필요할 때만 즉시 알린다. 상태는 /workspace/.bundle/state.json에 둔다."

## 5. 예약 방법 정하기
묶음배송 Bot은 두 시점에 스스로 깨어나야 해: 주인이 정한 출발 시각("3시에 보내 줘"), 도착 약속 시각.
- 특정 시각에 한 번만 실행되는 예약이 가능하면 그 방식을 쓰도록 Bot에게 알려 줘.
- 안 되면 5분마다 state.json을 읽고 출발·약속 시각이 지났는지 확인하는 루틴을 만들어 줘(cron: */5 * * * *). 지정 출발 시각도, 보고 안 한 배송도 없으면 아무것도 하지 않고 끝내게 해 줘.
어느 방식으로 했는지 알려 줘.

## 6. 동작 확인 (데모 모드)
묶음배송 Bot에게 차례로 보내고 각 답장을 보여 줘:
0. "안녕"   → 시간 설정 두 가지를 물어봐야 해. "기본값으로"라고 답해 줘
1. "데모 모드 켜"
2. "example.com 페이지 제목 알려 줘"   → 바로 실행하지 않고 🛒 장바구니 상태로 답해야 해
3. 1분 기다렸다가 장바구니가 그대로인지 확인한 뒤 "즉시 배송"   → 그때 출발(🚚)하고 도착 약속 시각을 알려야 해
4. 약속 시각까지 기다리기   → 시킨 것 / 다음 한 줄 / 바뀐 것 / 결정할 것 순서의 브리핑과 📦 예상→실제 줄이 와야 해
5. "급행: 오늘 날짜 알려 줘"   → 즉시 실행하고 바로 답해야 해
6. "example.com 링크 개수 세 줘" 후 "1분 뒤에 출발해 줘"   → 🛒 장바구니 상태에 출발 시각이 나오고, 그 시각에 출발해야 해
7. "데모 모드 꺼" 후 "설정 보여줘"   → ⚙️ 기준 60분 · 셧다운 23:00 이 나와야 해
마지막에 tte stats 결과를 보여 줘.
```

## 스킬 업데이트

스킬 파일을 고치고 `main`에 push한 뒤 보낸다.

```text
아래를 실행해서 스킬을 최신으로 바꾸고, 각 파일의 첫 10줄을 보여 줘.
for s in task-timer bundle-delivery; do
  curl -fsSL https://raw.githubusercontent.com/nahcub/grok_scheduler/main/grokbot/skills/$s/SKILL.md -o /home/box/agent-data/workflows/$s/SKILL.md
done
/workspace/.venvs/tte/bin/pip install --upgrade --force-reinstall "git+https://github.com/nahcub/grok_scheduler.git"
tte --version
```
