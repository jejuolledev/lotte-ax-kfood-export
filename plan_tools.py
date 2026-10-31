"""계획 단계 — 질문을 받아 모델이 도구 호출 순서를 정하고, 코드가 그 순서대로 실행한다.

모델이 정하는 것: 어떤 도구를 어떤 인자로 어떤 순서로 부를지(Structured Outputs 로 JSON 계획).
모델이 정하지 않는 것: 점수·순위·검증(코드 고정). 모델이 낸 계획은 코드가 검사한다(모르는 도구·순서 오류·검증 누락이면 거부).

사용:
  python3 plan_tools.py --dry "빼빼로 다음 유럽 나라"          # 모델 호출 없이, 손으로 만든 계획으로 실행기만 시험
  python3 plan_tools.py "빼빼로 다음 유럽 나라"                # OpenAI 호출 1회(계획) + 실행
결과는 결과/계획실행_<시각>.json 에 남긴다(질문·계획 원문·검사 결과·실행 순서·걸린 시간).
"""
import json, sys, time, pathlib, datetime, re

HERE = pathlib.Path(__file__).parent
OUT = HERE / "결과"
OUT.mkdir(exist_ok=True)

# ---------- 도구 정의(모델에 보여 주는 목록) ----------
TOOLS = {
    "fetch_import":    {"desc": "나라별 품목 수입(금액·무게)을 가져온다", "args": {"hs": "품목코드 1905|1806|1704|2105", "region": "유럽|아시아|북미|중남미|중동|오세아니아|전체"}},
    "fetch_kor_export": {"desc": "한국의 나라별 해당 품목 수출을 가져온다", "args": {"hs": "품목코드"}},
    "fetch_trend":     {"desc": "aT KATI 보고서에서 해당 나라들의 소비 트렌드 문장을 가져온다(지금은 영국·네덜란드·미국만 있음)", "args": {"countries": "나라 이름 목록"}},
    "score":           {"desc": "지표를 백분위로 바꿔 나라 점수·순위를 낸다(가중치는 코드 기본값, 바꾸려면 weights)", "args": {"weights": "선택. size/growth/kgrow/kfood 비중"}},
    "rising":          {"desc": "지금 TOP3 밖에서 작지만 빠른 나라를 규칙으로 거른다", "args": {}},
    "gaps":            {"desc": "자료가 비어 있는 곳과 다음 출처를 목록으로 낸다", "args": {}},
    "explain":         {"desc": "근거 행만 보고 추천 이유 문장을 쓴다(모델)", "args": {"top_n": "설명할 나라 수"}},
    "verify":          {"desc": "설명 문장의 숫자·연도·방향을 원자료와 대조해 맞는 것만 남긴다", "args": {}},
}
REGION = {"유럽": {826, 528, 276, 250, 724, 380, 616, 203, 752, 208, 246, 578, 40, 757, 372, 348, 642, 300, 620, 56},
          "아시아": {392, 156, 344, 704, 496, 458, 702, 764, 360, 608, 116, 418, 860, 417, 50, 144, 524, 96, 446},
          "북미": {842, 124}, "중남미": {484, 76, 152, 604, 170, 32, 218, 858, 600, 68, 862, 591, 188, 320, 214},
          "중동": {682, 784, 414, 634, 512, 48, 400, 818, 376, 792}, "오세아니아": {36, 554, 242}}
PRODUCT_HS = {"빼빼로": "1905", "칸쵸": "1905", "과자": "1905", "비스킷": "1905", "가나": "1806", "초콜릿": "1806",
              "캔디": "1704", "껌": "1704", "월드콘": "2105", "빙과": "2105", "아이스크림": "2105"}

PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "question_understood": {"type": "string", "description": "질문을 한 줄로 다시 쓴 것"},
        "intent": {"type": "string", "enum": ["top3", "why_country", "item_for_country", "rising", "gaps", "compare", "off_topic"],
                   "description": "top3=유망국가 묻기 / why_country=특정 나라가 왜 높은지·낮은지 / item_for_country=특정 나라에 먼저 보낼 품목 / rising=작지만 올라오는 나라 / gaps=자료 빈 곳 / compare=나라끼리 비교 / off_topic=K-푸드 수출 유망국가와 무관한 질문(이때 steps 는 빈 배열, limits 에 이유)"},
        "focus_countries": {"type": ["array", "null"], "items": {"type": "string"}, "description": "질문이 가리키는 나라 이름(한국어). 없으면 null"},
        "exclude_regions": {"type": ["array", "null"], "items": {"type": "string"}, "description": "빼라고 한 지역(유럽|아시아|북미|중남미|중동|오세아니아). 없으면 null"},
        "exclude_countries": {"type": ["array", "null"], "items": {"type": "string"}, "description": "빼라고 한 나라 이름. 없으면 null"},
        "limits": {"type": ["string", "null"], "description": "이 도구들로는 답하지 못하는 부분이 있으면 한 줄(예: 「빵을 뺀 수치는 비스킷 검산에서만 봄」). 없으면 null"},
        "steps": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"tool": {"type": "string", "enum": list(TOOLS)},
                           "args": {"type": "object", "additionalProperties": False,
                                    "properties": {"hs": {"type": ["string", "null"]}, "region": {"type": ["string", "null"]},
                                                   "countries": {"type": ["array", "null"], "items": {"type": "string"}},
                                                   "weights": {"type": ["object", "null"], "additionalProperties": False,
                                                               "properties": {k: {"type": ["number", "null"]} for k in ("size", "growth", "kgrow", "kfood")},
                                                               "required": ["size", "growth", "kgrow", "kfood"]},
                                                   "top_n": {"type": ["integer", "null"]}},
                                    "required": ["hs", "region", "countries", "weights", "top_n"]},
                           "why": {"type": "string"}},
            "required": ["tool", "args", "why"]}},
    },
    "required": ["question_understood", "intent", "focus_countries", "exclude_regions", "exclude_countries", "limits", "steps"],
}

SYSTEM = ("너는 K-푸드 수출 유망국가 에이전트의 계획 단계다. 담당자의 질문을 읽고, 아래 도구를 어떤 순서로 어떤 인자로 부를지 JSON 으로만 답한다. "
          "질문이 K-푸드 수출 유망국가(품목·나라·순위·근거·자료)와 무관하면(예: 이름·날씨·잡담) intent=off_topic 으로 두고 도구를 하나도 부르지 않는다(steps 빈 배열). 먼저 intent(질문 종류)와 focus_countries(질문이 가리키는 나라), 그리고 「~는 빼고」가 있으면 exclude_regions·exclude_countries 를 정한다(빼는 지역은 fetch_import 의 region 에 넣지 않는다). 가중치는 질문이 바꾸라고 할 때만 score 의 weights 에 size(시장 규모)·growth(수입 성장)·kgrow(한국 수출 성장)·kfood(K-푸드 전반) 비중을 합이 1이 되게 넣고, 그 밖엔 반드시 null 로 둔다(기본 가중치 각 25%). 규칙: 점수·순위는 score 도구만 낸다(네가 순위를 정하지 않는다). 특정 나라를 묻는 질문(why_country·item_for_country)은 score → explain → verify → gaps 를 포함한다. explain 뒤에는 반드시 verify 가 온다. "
          "질문에 제품 이름이 있으면 품목코드로 바꾼다(빼빼로·칸쵸=1905, 가나=1806, 캔디=1704, 월드콘=2105). 품목을 안 정한 질문(K-푸드 전체·유망국가 전체)이면 hs 를 비워 둔다(= 전체 품목). "
          "질문에 지역이 없으면 region 은 null(전체)로 두고 지역을 지어내지 않는다. 뺄 지역은 exclude_regions 에만 쓰고 나머지 지역으로 쪼개지 않는다. 질문에 지역이 있으면 fetch_import 의 region 에 넣는다(동남아·동북아·중앙아시아·인도 등은 아시아, 남미·라틴아메리카·멕시코는 중남미, EU·서유럽·동유럽·영국은 유럽, 미국·캐나다는 북미, 걸프·중동은 중동, 호주·뉴질랜드는 오세아니아 — 이 여섯 이름이나 전체만 쓴다).  자료가 없는 나라가 있을 수 있으니 마지막엔 gaps 를 부른다. 도구가 못 하는 것(예: 품목 6단위 분리, 소비 트렌드 자동 수집, 롯데 제품별 실적)은 limits 에 적는다.\n도구 목록:\n"
          + "\n".join(f"- {k}: {v['desc']} / 인자 {json.dumps(v['args'], ensure_ascii=False)}" for k, v in TOOLS.items()))


# ---------- 계획 검사(코드) ----------
def check_plan(plan):
    errs = []
    tools = [s["tool"] for s in plan.get("steps", [])]
    for t in tools:
        if t not in TOOLS:
            errs.append(f"모르는 도구 {t}")
    if plan.get("intent") == "off_topic":
        return errs  # 무관한 질문: 도구 없이 안내만
    if "score" not in tools and plan.get("intent") not in ("rising", "gaps"):
        errs.append("score 없음(순위가 안 나옴)")
    if "explain" in tools and ("verify" not in tools or tools.index("verify") < tools.index("explain")):
        errs.append("explain 뒤에 verify 가 없음")
    if "score" in tools:
        need = ["fetch_import", "fetch_kor_export"]
        before = set(tools[:tools.index("score")])
        missing = [t for t in need if t not in before]
        if missing:  # 거부하지 않고 코드가 앞에 끼워 넣는다(기록 남김)
            A0 = {"hs": None, "region": None, "countries": None, "weights": None, "top_n": None}
            idx = tools.index("score")
            for t in reversed(missing):
                plan["steps"].insert(idx, {"tool": t, "args": dict(A0), "why": "코드가 보충(계획에 빠져 있던 수집 단계)"})
            plan["_코드_보충"] = missing
    for s in plan.get("steps", []):
        a = s.get("args") or {}
        if s["tool"] in ("fetch_import", "fetch_kor_export") and (a.get("hs") not in (None, "1905", "1806", "1704", "2105")):
            errs.append(f"{s['tool']} 의 hs 가 잘못됨: {a.get('hs')}")
        if s["tool"] == "fetch_import" and a.get("region") not in (None, "전체", *REGION):
            errs.append(f"region 이 잘못됨: {a.get('region')}")
    return errs


# ---------- 실행기(코드) ----------
def run_plan(plan, dry=False):
    """analyze.py 의 결과(시범결과.json)를 도구 단위로 다시 읽어 순서대로 돌린다. 계획이 정한 품목·지역으로 범위를 좁힌다."""
    R = json.load(open(OUT / "시범결과.json", encoding="utf-8"))
    log, ctx = [], {"hs": set(), "region": None}
    for i, s in enumerate(plan["steps"], 1):
        t, a = s["tool"], s.get("args") or {}
        t0 = time.time()
        if t == "fetch_import":
            if a.get("hs"): ctx["hs"].add(a["hs"])
            ctx["region"] = a.get("region")
            rows = [r for r in R["근거행"] if (not a.get("hs") or r["id"].split("-")[1] == a["hs"]) and r["id"].endswith("-M")]
            out = f"수입 행 {len(rows)}개(HS {a.get('hs') or '전체 품목'}, {a.get('region') or '전체'})"
        elif t == "fetch_kor_export":
            rows = [r for r in R["근거행"] if (not a.get("hs") or r["id"].split("-")[1] == a["hs"]) and r["id"].endswith("-K")]
            out = f"한국 수출 행 {len(rows)}개(HS {a.get('hs') or '전체 품목'})"
        elif t == "fetch_trend":
            have = {"영국", "네덜란드", "미국"}
            cs = a.get("countries") or []
            out = f"트렌드 문장 있음 {sorted(set(cs) & have)} / 없음 {sorted(set(cs) - have)}"
        elif t == "score":
            top = [x["country"] for x in R["TOP3_현지공장국가_제외"]]
            per = {k: [c["country"] for c in v] for k, v in R["품목별_TOP3_현지공장국가_제외"].items()}
            CMD_KEY = {"1905": "비스킷·과자류(빼빼로·칸쵸 등)", "1806": "초콜릿(가나 등)", "1704": "캔디·껌(설탕 과자)", "2105": "아이스크림(빙과)"}
            if ctx["hs"]:
                per = {k: v for k, v in per.items() if any(CMD_KEY.get(h) == k for h in ctx["hs"])}
            if a.get("weights"):
                out_w = {k: v for k, v in a["weights"].items() if v}
                top = f"(가중치 {out_w} 적용 — 실제 순위는 화면 답 참조)"
            out = "점수·순위 계산(지역·제외·가중치 반영한 실제 순위는 화면 답에 표시)"
        elif t == "rising":
            out = [f"{x['country']} {x['cmd'].split('(')[0]} 연 {x['kgrow_2021base']*100:.0f}%" for x in R["올라오는_나라"]]
        elif t == "gaps":
            out = [f"{g['country']}: {g['빈 곳']}" for g in R["자료_빈_곳"]]
        elif t == "explain":
            sents = json.load(open(OUT / "모델문장_화면용.json", encoding="utf-8")) if (OUT / "모델문장_화면용.json").exists() else []
            out = f"설명 문장 {len(sents)}개(받아 둔 것을 씀{' · dry' if dry else ''})"
        elif t == "verify":
            v = json.load(open(OUT / "검증_v3_요약.json", encoding="utf-8")) if (OUT / "검증_v3_요약.json").exists() else {}
            v3 = (v.get("v3") or {}) if isinstance(v, dict) else {}
            out = {"검증기": "v3", "저장문장72": v3.get("가_저장문장72"), "공격17": v3.get("나_공격17"), "어려운세트50": v3.get("다_어려운세트50")}
        else:
            out = "모르는 도구"
        log.append({"순서": i, "도구": t, "인자": a, "이유": s.get("why"), "결과": out, "초": round(time.time() - t0, 3)})
    return log


def make_plan_with_model(question):
    from openai import OpenAI  # 키는 환경변수 OPENAI_API_KEY — 코드에 적지 않는다
    client = OpenAI(timeout=20.0, max_retries=1)  # 최대 약 40초, 화면은 50초에 끊음
    t0 = time.time()
    resp = client.responses.create(
        model="gpt-5.4-mini",
        input=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
        text={"format": {"type": "json_schema", "name": "plan", "schema": PLAN_SCHEMA, "strict": True}},
    )
    u = getattr(resp, "usage", None)
    usage = {"input": getattr(u, "input_tokens", None), "output": getattr(u, "output_tokens", None)} if u else None
    raw = resp.output_text
    try:
        plan = json.loads(raw)
        extra = False
    except json.JSONDecodeError:
        # 모델이 JSON 을 둘 보내는 경우가 있다(10/31 8번 중 3번): 첫 JSON 객체만 쓰고 기록에 남긴다
        plan, end = json.JSONDecoder().raw_decode(raw)
        extra = raw[end:].strip()[:200]
    plan["_모델_JSON_뒤_덧붙임"] = extra
    return plan, round(time.time() - t0, 2), getattr(resp, "model", None), usage


def hand_plan(question):
    """--dry 용. 질문에서 품목·지역을 규칙으로 뽑아 고정 순서 계획을 만든다(모델 없이 실행기만 시험)."""
    hs = next((v for k, v in PRODUCT_HS.items() if k in question), "1905")
    region = next((r for r in REGION if r in question), "전체")
    A = lambda **kw: {"hs": None, "region": None, "countries": None, "weights": None, "top_n": None, **kw}
    return {"question_understood": f"HS {hs}, {region} — 다음 나라", "intent": "top3", "focus_countries": None, "exclude_regions": None, "exclude_countries": None, "limits": None, "steps": [
        {"tool": "fetch_import", "args": A(hs=hs, region=region), "why": "손 계획"},
        {"tool": "fetch_kor_export", "args": A(hs=hs), "why": "손 계획"},
        {"tool": "score", "args": A(), "why": "손 계획"},
        {"tool": "fetch_trend", "args": A(countries=["영국", "네덜란드", "미국"]), "why": "손 계획"},
        {"tool": "explain", "args": A(top_n=3), "why": "손 계획"},
        {"tool": "verify", "args": A(), "why": "손 계획"},
        {"tool": "rising", "args": A(), "why": "손 계획"},
        {"tool": "gaps", "args": A(), "why": "손 계획"}]}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    q = args[0] if args else "빼빼로 다음 유럽 나라는 어디인가"
    if dry:
        plan, secs, model, usage = hand_plan(q), 0.0, "(모델 없음 · 손 계획)", None
    else:
        plan, secs, model, usage = make_plan_with_model(q)
    errs = check_plan(plan)
    rec = {"질문": q, "모델": model, "계획_초": secs, "토큰": usage, "계획": plan, "검사": errs or "통과"}
    if not errs:
        rec["실행"] = run_plan(plan, dry=dry)
    stamp = datetime.datetime.now().strftime("%m%d_%H%M%S")
    path = OUT / f"계획실행_{stamp}{'_dry' if dry else ''}.json"
    json.dump(rec, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"질문": q, "모델": model, "초": secs, "토큰": usage, "검사": rec["검사"], "순서": [s["tool"] for s in plan["steps"]], "저장": path.name}, ensure_ascii=False))
