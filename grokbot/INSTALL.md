# 그록봇에 tte 설치하기

tte와 `task-timer` 스킬만 설치한다. 묶음배송 봇까지 만들려면 [CREATE_BOT.md](CREATE_BOT.md)를 쓴다(설치 단계가 들어 있다).

아래 블록을 그록봇에게 그대로 붙여넣는다. 저장소: https://github.com/nahcub/grok_scheduler

```text
작업 시간 예측 CLI인 tte를 네 컴퓨터에 설치하고 스킬로 등록해 줘.

1. 설치
   python3 -m venv /workspace/.venvs/tte
   /workspace/.venvs/tte/bin/pip install "git+https://github.com/nahcub/grok_scheduler.git"
   ln -sf /workspace/.venvs/tte/bin/tte /usr/local/bin/tte   # 권한이 없으면 ~/.local/bin/tte 에 링크하고 PATH에 추가

2. 확인
   tte --version   → {"version":"0.2.0"} 이 나와야 해
   tte start "설치 확인" --complexity light --kind other
   tte stop
   두 명령의 출력을 보여 줘.

3. 스킬 등록
   mkdir -p /home/box/agent-data/workflows/task-timer
   curl -fsSL https://raw.githubusercontent.com/nahcub/grok_scheduler/main/grokbot/skills/task-timer/SKILL.md -o /home/box/agent-data/workflows/task-timer/SKILL.md

4. 봇 프로필 description에 이 한 줄을 추가해 줘:
   "모든 작업은 시작 전에 tte start, 끝난 뒤 tte stop (task-timer 스킬 참고)"

각 단계 결과를 [확인함] / [실패] 로 알려 줘.
```

## 업데이트

```text
/workspace/.venvs/tte/bin/pip install --upgrade --force-reinstall "git+https://github.com/nahcub/grok_scheduler.git" 를 실행하고 tte --version 결과를 보여 줘.
```

기록은 `/workspace/.tte/tte.db`에 있어서 업데이트해도 남는다.
