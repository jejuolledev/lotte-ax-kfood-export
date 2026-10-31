"""K-푸드 수출 유망국가 에이전트 — 심사위원용 실행 화면(Cloud Run).

질문 1건 = OpenAI 호출 1번(계획 단계, gpt-5.4-mini Structured Outputs). 설명 문장·순위·검증은 받아 둔 결과 파일로 코드가 낸다.
비용 통제: ACCESS_CODE(비밀번호) · 하루 DAILY_CAP 번 · 총 TOTAL_CAP 번(인스턴스 메모리 기준, max-instances=1) · 질문 300자 제한.
키는 환경변수 OPENAI_API_KEY 로만 읽는다. 어디에도 기록하지 않는다.
"""
import os, json, time, datetime, pathlib, threading, re
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

HERE = pathlib.Path(__file__).parent
import sys
sys.path.insert(0, str(HERE))
import plan_tools as PT  # 같은 폴더에 복사해 둔 계획 단계 코드

OUT = HERE / "결과"
R = json.load(open(OUT / "시범결과.json", encoding="utf-8"))
VER = {v["text"]: v for v in json.load(open(OUT / "검증_모델문장.json", encoding="utf-8")).get("모델문장_화면용", [])}
SENT = json.load(open(OUT / "모델문장_화면용.json", encoding="utf-8"))
EV = {r["id"]: r for r in R["근거행"]}
EXAMPLES = [json.load(open(f, encoding="utf-8")) for f in sorted(OUT.glob("계획실행_*.json")) if "_dry" not in f.name]

ACCESS_CODE = os.environ.get("ACCESS_CODE", "")
DAILY_CAP = int(os.environ.get("DAILY_CAP", "50"))
TOTAL_CAP = int(os.environ.get("TOTAL_CAP", "300"))
_lock = threading.Lock()
_state = {"day": None, "today": 0, "total": 0, "tokens_in": 0, "tokens_out": 0, "started": datetime.datetime.now().isoformat(timespec="seconds")}

CMD_KEY = {"1905": "비스킷·과자류(빼빼로·칸쵸 등)", "1806": "초콜릿(가나 등)", "1704": "캔디·껌(설탕 과자)", "2105": "아이스크림(빙과)"}


def region_codes(region):
    """plan_tools.REGION 의 나라 코드 집합. 결과 파일의 순위 항목엔 code 가 있어 코드로 거른다."""
    return PT.REGION.get(region or "", None)


def answer_from_results(plan):
    """계획이 정한 품목·지역으로 결과 파일을 좁혀 실제 답을 만든다(코드)."""
    hs = {s["args"].get("hs") for s in plan["steps"] if s["args"].get("hs")}
    region = next((s["args"].get("region") for s in plan["steps"] if s["args"].get("region")), None)
    codes = region_codes(region)
    region_names = {c["country"] for c in R["종합_전체순위_현지공장국가_제외"] if c["code"] in codes} | {c["country"] for v in R["품목별_전체순위_현지공장국가_제외"].values() for c in v if c["code"] in codes} | {x["country"] for x in R.get("올라오는_나라", []) if x["code"] in codes} if codes else None
    tools = [s["tool"] for s in plan["steps"]]
    ans = {"품목": [CMD_KEY[h] for h in hs if h in CMD_KEY], "지역": region or "전체"}

    if "score" in tools:
        full = R["품목별_전체순위_현지공장국가_제외"]
        if hs:
            full = {k: v for k, v in full.items() if any(CMD_KEY.get(h) == k for h in hs)}
        per, note = {}, None
        for k, v in full.items():
            v2 = [c for c in v if c["code"] in codes] if codes else v
            per[k] = v2[:3]
            if codes and not v2:
                note = f"{region}에는 비교 조건(한국 수출 100만 달러·그 나라 수입 2,000만 달러 이상)을 넘는 나라가 없음"
        ans["품목별_TOP3"] = per
        allrank = R["종합_전체순위_현지공장국가_제외"]
        top = [t for t in allrank if t["code"] in codes] if codes else allrank
        ans["종합_순위"] = top[:5]
        ans["검산"] = {"세트수": R["민감도_세트수"], "등장횟수": R["민감도_TOP3_등장횟수"]}
        if note:
            ans["주의"] = note
        if hs and per:
            k0 = next(iter(per)); ans["유망국가_TOP3"] = {"기준": k0 + (f" · {region}" if codes else ""), "나라": [c["country"] for c in per[k0]]}
        else:
            ans["유망국가_TOP3"] = {"기준": "종합(현지 공장 나라 제외)" + (f" · {region}" if codes else ""), "나라": [t["country"] for t in top[:3]]}
        ans = {"유망국가_TOP3": ans.pop("유망국가_TOP3"), **ans}
    if "explain" in tools:
        want = {c["country"] for k, v in ans.get("품목별_TOP3", R["품목별_TOP3_현지공장국가_제외"]).items() for c in v}
        shown, hidden = [], 0
        for c in SENT.get("countries", []):
            if want and c["country"] not in want:
                continue
            for s in c.get("sentences", []):
                v = VER.get(s["text"], {})
                srcs = [EV[i]["source"] for i in s.get("row_ids", []) if i in EV]
                if v.get("판정") == "표시":
                    shown.append({"나라": c["country"], "문장": s["text"], "출처": srcs})
                else:
                    hidden += 1
        ans["설명_문장"] = shown
        ans["숨긴_문장_수"] = hidden
        ans["설명_주의"] = "문장은 미리 생성해 검증해 둔 것(이 화면에서 새로 쓰지 않음). 검증기 v3 통과분만 표시."
    if "rising" in tools:
        rs = R.get("올라오는_나라", [])
        if hs:
            rs2 = [x for x in rs if any(CMD_KEY.get(h) == x["cmd"] for h in hs)]
            rs = rs2 or rs
        if region_names:
            rs = [x for x in rs if x["country"] in region_names] or rs
        ans["올라오는_곳"] = [{"나라": x["country"], "품목": x["cmd"], "한국수출_2021→2025_백만달러": [round(x["kor_2021_usd"] / 1e6, 2), round(x["kor_2025_usd"] / 1e6, 2)],
                            "연증가": x["kgrow_2021base"], "2022기준": x["kgrow_2022base"], "그나라수입_연증가": x["import_growth"],
                            "시장_백만달러": round(x["그나라_수입시장_USD"] / 1e6), "K푸드전반_연증가": x["한국가공식품_연증가율"], "점유율": x["kor_share_2025"], "표시": x["주의"] or x["tag"]} for x in rs]
        ans["올라오는_곳_규칙"] = R.get("올라오는_나라_규칙")
    if "gaps" in tools:
        ans["모르는_것"] = R.get("자료_빈_곳", [])
    if "fetch_trend" in tools:
        cs = next((s["args"].get("countries") for s in plan["steps"] if s["tool"] == "fetch_trend"), None) or []
        have = {"영국", "네덜란드", "미국"}
        ans["트렌드_문장"] = {"있음": sorted(set(cs) & have), "없음(다음 출처: aT KATI·KOTRA)": sorted(set(cs) - have)}
    return ans


app = FastAPI(title="K-푸드 수출 유망국가 에이전트")


class Ask(BaseModel):
    question: str
    code: str = ""


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "index.html").read_text(encoding="utf-8")


@app.get("/examples")
def examples():
    out = []
    for e in EXAMPLES:
        out.append({"질문": e["질문"], "모델": e.get("모델"), "초": e.get("계획_초"), "토큰": e.get("토큰"), "검사": e.get("검사"),
                    "순서": [{"도구": s["tool"], "이유": s.get("why", ""), "인자": {k: v for k, v in (s.get("args") or {}).items() if v}} for s in e["계획"]["steps"]],
                    "덧붙임": bool(e["계획"].get("_모델_JSON_뒤_덧붙임")),
                    "답": answer_from_results(e["계획"])})
    return out


DATA_USED = [
    {"자료": "UN Comtrade(유엔 무역통계) 공개 API", "무엇": "나라별 품목 수입(금액·무게)·수출, 한국의 나라별 수출 — HS 1905·1806·1704·2105와 가공식품 16~21류, 2021~2025년 연간치", "범위": "원본 54개 파일, 비교 16개국(넓힌 검산 26개국)", "한계": "베트남·몽골·UAE는 2023년까지, 영국 2025년 무게 없음, 멕시코 무게 없음"},
    {"자료": "롯데웰푸드 IR 2025년 4분기·2026년 2분기", "무엇": "해외 공장 나라(제외 규칙), 주요 수출국·입점국(맞춰 보기), 수출 실적", "범위": "공개 자료", "한계": "제품별 수출액·신고 품목코드는 없음"},
    {"자료": "aT KATI 국가조사·시장동향 보고서", "무엇": "소비 트렌드 문장(쪽 번호와 함께)", "범위": "영국·네덜란드·미국 3개국, 직접 뽑음", "한계": "자동 추출 아직 없음, 다른 나라 없음"},
    {"자료": "농림축산식품부 보도자료(2026-01-12)", "무엇": "연간 K-푸드 수출 실적(출처 간 숫자 차이 표시용)", "범위": "2025년", "한계": "품목 분류가 Comtrade와 다름"},
]
MORE_ACCURATE = [
    {"필요한 자료": "롯데웰푸드 제품별 수출 실적·신고 품목코드(사내)", "무엇이 좋아지나": "빼빼로 등 실제 제품 단위로 점수·「롯데 몫」 지표, 품목 비중을 롯데 실적으로", "어디서": "롯데 수출팀"},
    {"필요한 자료": "관세청 수출입무역통계 2026년 월별치", "무엇이 좋아지나": "2025년 연간치 → 올해 흐름 반영, 중동 차질 같은 변화가 바로 보임", "어디서": "관세청 unipass 통계"},
    {"필요한 자료": "그 나라 소비 통계(소매 판매·가구 소비)", "무엇이 좋아지나": "네덜란드처럼 재수출이 섞인 나라의 실제 소비 규모", "어디서": "aT KATI 보고서가 인용하는 유로모니터 등, 현지 통계청"},
    {"필요한 자료": "aT KATI·KOTRA 보고서 전 국가분", "무엇이 좋아지나": "소비 트렌드 지표를 16개국 전부에 적용", "어디서": "KATI 보고서 목록, KOTRA 해외시장뉴스"},
    {"필요한 자료": "수입 무게(영국 2025·멕시코 전체)", "무엇이 좋아지나": "값이 오른 것인지 더 먹는 것인지 가름", "어디서": "그 나라 통계청, 없으면 한국 관세청 수출 무게"},
    {"필요한 자료": "현지 규제·관세·입점 채널 자료", "무엇이 좋아지나": "영국 HFSS 매대 제한 같은 걸림돌을 점수에 반영", "어디서": "KOTRA 해외시장뉴스, 현지 법령"},
]


@app.get("/summary")
def summary():
    return {"기준": R["기준"], "대상_나라수": R["대상_나라수"], "분석한_자료": DATA_USED, "더_정확해지려면": MORE_ACCURATE,
            "유망국가_TOP3": [{"나라": t["country"], "점수": t["score"], "품목점수": t["품목점수"], "표시": t["tag"]} for t in R["TOP3_현지공장국가_제외"]],
            "품목별_TOP3": R["품목별_TOP3_현지공장국가_제외"], "검산": {"세트수": R["민감도_세트수"], "등장횟수": R["민감도_TOP3_등장횟수"], "세트": R["민감도_TOP3"]},
            "올라오는_곳": R.get("올라오는_나라", []), "모르는_것": R.get("자료_빈_곳", []), "범위_넓힘_상위10": R.get("범위_넓힘_상위10")}


@app.get("/status")
def status():
    with _lock:
        return {**_state, "daily_cap": DAILY_CAP, "total_cap": TOTAL_CAP}


@app.post("/ask")
def ask(a: Ask):
    q = (a.question or "").strip()
    if ACCESS_CODE and a.code != ACCESS_CODE:
        raise HTTPException(401, "비밀번호가 다릅니다(지원서·README에 적어 둔 코드).")
    if not q or len(q) > 300:
        raise HTTPException(400, "질문은 1~300자.")
    today = datetime.date.today().isoformat()
    with _lock:
        if _state["day"] != today:
            _state["day"], _state["today"] = today, 0
        if _state["today"] >= DAILY_CAP or _state["total"] >= TOTAL_CAP:
            raise HTTPException(429, f"오늘 한도({DAILY_CAP}번) 또는 총 한도({TOTAL_CAP}번)가 끝났습니다. 아래 실행 예시 6건은 그대로 볼 수 있습니다.")
        _state["today"] += 1; _state["total"] += 1
    t0 = time.time()
    try:
        plan, secs, model, usage = PT.make_plan_with_model(q)
    except Exception as e:  # 모델 쪽 오류는 사실대로
        raise HTTPException(502, f"모델 호출 실패: {type(e).__name__}")
    with _lock:
        if usage:
            _state["tokens_in"] += usage.get("input") or 0; _state["tokens_out"] += usage.get("output") or 0
    errs = PT.check_plan(plan)
    rec = {"질문": q, "모델": model, "계획_초": secs, "토큰": usage, "검사": errs or "통과",
           "순서": [{"도구": s["tool"], "이유": s.get("why", ""), "인자": {k: v for k, v in (s.get("args") or {}).items() if v}} for s in plan["steps"]],
           "덧붙임": bool(plan.get("_모델_JSON_뒤_덧붙임")), "질문_이해": plan.get("question_understood")}
    if not errs:
        rec["실행"] = PT.run_plan(plan)
        rec["답"] = answer_from_results(plan)
    rec["전체_초"] = round(time.time() - t0, 2)
    return JSONResponse(rec)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
