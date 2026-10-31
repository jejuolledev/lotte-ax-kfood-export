# 실행 화면(심사위원용) — Cloud Run

질문 1건 = OpenAI 호출 1번(계획 단계). 순위·검증·빈 곳·설명 문장은 `../결과/` 파일로 코드가 냅니다.

- 로컬: `cd live && mkdir -p 결과 && cp ../결과/시범결과.json ../결과/검증_모델문장.json ../결과/모델문장_화면용.json ../결과/검증_v3_요약.json ../결과/계획실행_*.json 결과/ && cp ../plan_tools.py . && OPENAI_API_KEY=... ACCESS_CODE=아무거나 uv run --with fastapi --with 'uvicorn[standard]' --with openai python app.py` → http://127.0.0.1:8080
- 비용 통제: 비밀번호(ACCESS_CODE) · 하루 DAILY_CAP 번 · 총 TOTAL_CAP 번(인스턴스 메모리 기준, max-instances=1) · 질문 300자.
- 키는 환경변수로만. 이 폴더에 키 파일을 두지 마세요.
