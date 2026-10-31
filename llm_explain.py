"""시범 에이전트의 「설명」 단계 — OpenAI 모델이 근거 행만 보고 추천 이유 문장을 쓴다(구조화 출력).

입력: 결과/시범결과.json 의 근거행
출력: 결과/모델문장_정상.json  — 평소대로 쓴 문장(나라별, 문장마다 근거 행 id)
      결과/모델문장_함정.json  — 시험용: 모델에게 일부 문장의 숫자를 일부러 틀리게 쓰게 하고 어느 것인지 표시하게 함
사용: OPENAI_API_KEY=... python3 llm_explain.py   (키는 파일에 저장하지 않음)
"""
import json, os, pathlib, urllib.request, urllib.error, time

HERE = pathlib.Path(__file__).parent
R = json.load(open(HERE / "결과" / "시범결과.json", encoding="utf-8"))
MODEL = os.environ.get("MODEL", "gpt-5.4-mini")
KEY = os.environ["OPENAI_API_KEY"]

rows = [{k: v for k, v in e.items() if k != "source"} for e in R["근거행"]]
top = [t["country"] for t in R["TOP3_현지공장국가_제외"]]


def call(system, user, schema, name):
    body = {"model": MODEL, "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "text": {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}}
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.time()
    for attempt in range(4):  # 일시 오류(429·5xx)면 잠시 뒤 다시
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code < 429 or attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
    txt = next(c["text"] for o in d["output"] if o.get("type") == "message" for c in o["content"] if c.get("type") == "output_text")
    return json.loads(txt), d.get("usage", {}), round(time.time() - t0, 1), d.get("model")


SENT = {"type": "object", "additionalProperties": False, "required": ["text", "row_ids"],
        "properties": {"text": {"type": "string"}, "row_ids": {"type": "array", "items": {"type": "string"}}}}
SCHEMA_OK = {"type": "object", "additionalProperties": False, "required": ["countries"],
             "properties": {"countries": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                            "required": ["country", "sentences"],
                            "properties": {"country": {"type": "string"}, "sentences": {"type": "array", "items": SENT}}}}}}
TRAP = {"type": "object", "additionalProperties": False, "required": ["text", "row_ids", "is_wrong", "what_changed"],
        "properties": {"text": {"type": "string"}, "row_ids": {"type": "array", "items": {"type": "string"}},
                       "is_wrong": {"type": "boolean"}, "what_changed": {"type": "string"}}}
SCHEMA_TRAP = {"type": "object", "additionalProperties": False, "required": ["sentences"],
               "properties": {"sentences": {"type": "array", "items": TRAP}}}

SYS = ("너는 롯데웰푸드 수출팀을 돕는 분석 보조다. 사용자가 준 근거 행(JSON)만 쓴다. "
       "숫자는 근거 행의 값, 또는 그 값으로 계산한 증가율·배수·차이·점유율만 쓴다. 금액은 '백만 달러' 또는 '억 달러', 무게는 '톤' 단위로 써도 된다. "
       "근거 행에 없는 사실(관세, 소비자 취향, 경쟁사, 유통 채널 등)은 쓰지 않는다. 문장마다 사용한 근거 행 id를 row_ids에 모두 넣는다. 한국어, 짧은 평서문.")

user_ok = (f"추천 후보 나라: {', '.join(top)} (그리고 비교용 독일).\n"
           "나라마다 이 나라를 추천하거나 조심해야 하는 이유를 문장 4개로 써라. 금액만 늘고 무게는 덜 늘었으면 그 점도 써라. "
           "수입보다 수출이 많은 나라(재수출 관문 가능성)도 근거 행이 있으면 써라.\n근거 행:\n" + json.dumps(rows, ensure_ascii=False))
user_trap = ("검증기 시험용이다. 아래 근거 행으로 추천 이유 문장 16개를 써라. 그중 정확히 8개는 일부러 틀리게 써라: "
             "숫자 하나를 5~25% 바꾸거나, 연도를 바꾸거나, 다른 나라·다른 품목 행의 숫자를 섞어라(그 행 id는 row_ids에 넣지 말 것). "
             "틀린 문장은 is_wrong=true와 what_changed에 무엇을 바꿨는지 적고, 맞는 문장은 is_wrong=false. 틀린 문장도 자연스럽게 보이게 써라.\n근거 행:\n"
             + json.dumps(rows, ensure_ascii=False))

if os.environ.get("BIG_TEST") or os.environ.get("DISPLAY_RUN"):
    pass
else:
  out_ok, u1, t1, m1 = call(SYS, user_ok, SCHEMA_OK, "reasons")
  (HERE / "결과" / "모델문장_정상.json").write_text(json.dumps({"model": m1, "seconds": t1, "usage": u1, **out_ok}, ensure_ascii=False, indent=1))
  out_trap, u2, t2, m2 = call(SYS, user_trap, SCHEMA_TRAP, "trap")
  (HERE / "결과" / "모델문장_함정.json").write_text(json.dumps({"model": m2, "seconds": t2, "usage": u2, **out_trap}, ensure_ascii=False, indent=1))
  print(m1, t1, u1.get("input_tokens"), u1.get("output_tokens"), "|", m2, t2, u2.get("input_tokens"), u2.get("output_tokens"))

# --- 시험 세트 확장(2026-10-30 밤): 더 큰 모델이 쓴 「전부 틀린 20개」 「전부 맞는 20개」 ---
if os.environ.get("BIG_TEST") and not os.environ.get("DISPLAY_RUN"):
    MODEL = os.environ.get("BIG_MODEL", "gpt-5.4")
    user_wrong = ("검증기 시험용이다. 아래 근거 행으로 추천 이유 문장 20개를 써라. 20개 모두 숫자 하나씩만 일부러 틀리게 써라. "
                  "틀리는 방식은 고르게 섞어라: 금액·무게를 3~25% 바꾸기, 연도 바꾸기, 연평균 증가율을 잘못 계산하기, 배수(몇 배)를 잘못 계산하기, "
                  "단위를 10배 착각하기(백만↔천만), 다른 나라·다른 품목 행의 숫자 섞기(그 행 id는 row_ids에 넣지 말 것). "
                  "자연스럽게 보이게 쓰고, 각 문장 is_wrong=true, what_changed에 무엇을 어떻게 바꿨는지 정확히 적어라.\n근거 행:\n" + json.dumps(rows, ensure_ascii=False))
    user_right = ("검증기 시험용이다. 아래 근거 행으로 추천 이유 문장 20개를 써라. 20개 모두 정확해야 한다. "
                  "단순히 값을 옮기는 문장만 쓰지 말고, 절반 이상은 연평균 증가율, 몇 배 늘었는지, 수입과 수출의 차이, 금액과 무게 증가율 비교처럼 계산한 숫자를 넣어라. "
                  "금액은 억 달러·백만 달러·만 달러, 무게는 톤이나 kg 등 표현을 섞어라. 반올림은 소수 첫째 자리까지. 각 문장 is_wrong=false, what_changed는 빈 문자열.\n근거 행:\n"
                  + json.dumps(rows, ensure_ascii=False))
    w, u3, t3, m3 = call(SYS, user_wrong, SCHEMA_TRAP, "wrong20")
    (HERE / "결과" / "모델문장_틀림20.json").write_text(json.dumps({"model": m3, "seconds": t3, "usage": u3, **w}, ensure_ascii=False, indent=1))
    g, u4, t4, m4 = call(SYS, user_right, SCHEMA_TRAP, "right20")
    (HERE / "결과" / "모델문장_맞음20.json").write_text(json.dumps({"model": m4, "seconds": t4, "usage": u4, **g}, ensure_ascii=False, indent=1))
    print(m3, t3, u3.get("input_tokens"), u3.get("output_tokens"), "|", m4, t4, u4.get("input_tokens"), u4.get("output_tokens"))

# --- 화면용 문장 다시 쓰기(2026-10-30 밤, 2차 심사 반영): 수출>수입 해석을 현업 상식대로 ---
if os.environ.get("DISPLAY_RUN"):
    MODEL = "gpt-5.4-mini"
    sys2 = SYS + (" 어떤 나라의 같은 품목 수출이 수입보다 많으면 '현지 생산이 많거나 재수출이 섞여 있을 수 있어 실제 소비 규모와 경쟁 강도를 따로 봐야 한다'는 뜻으로만 쓰고, "
                  "'재수출 관문'이라고 단정하지 않는다. 시작값이 100만 달러보다 작은 증가율은 '시작값이 작다'고 함께 쓴다.")
    d5, u5, t5, m5 = call(sys2, user_ok, SCHEMA_OK, "reasons_display")
    (HERE / "결과" / "모델문장_화면용.json").write_text(json.dumps({"model": m5, "seconds": t5, "usage": u5, **d5}, ensure_ascii=False, indent=1))
    print(m5, t5, u5.get("input_tokens"), u5.get("output_tokens"))
