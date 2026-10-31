"""K-푸드 수출 유망국가 에이전트 — 심사위원용 실행 화면(Cloud Run).

질문 1건 = OpenAI 호출 1번(계획 단계, gpt-5.4-mini Structured Outputs). 설명 문장·순위·검증은 받아 둔 결과 파일로 코드가 낸다.
비용 통제: ACCESS_CODE(비밀번호) · 하루 DAILY_CAP 번 · 총 TOTAL_CAP 번(인스턴스 메모리 기준, max-instances=1) · 질문 300자 제한.
키는 환경변수 OPENAI_API_KEY 로만 읽는다. 어디에도 기록하지 않는다.
"""
import os, json, time, datetime, pathlib, threading, re
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
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


def country_answer(focus, hs, intent):
    """특정 나라 질문: 그 나라의 순위·점수·지표를 품목 1위와 나란히."""
    M = R["나라별_지표"]; full = R["품목별_전체순위_현지공장국가_제외"]
    out = []
    for c in focus:
        m = M[c]; items = []
        for k, v in m["품목"].items():
            if hs and not any(CMD_KEY.get(h) == k for h in hs):
                continue
            lead = full[k][0] if full.get(k) else None
            lm = M.get(lead["country"], {}).get("품목", {}).get(k) if lead else None
            items.append({"품목": k, "순위": v["품목순위"], "전체": len(full.get(k, [])), "점수": v["품목점수"], "지표백분위": v["지표백분위"],
                          "수입_연증가": v["수입_연증가"], "수입무게_연증가": v["수입무게_연증가"], "한국수출_연증가": v["한국수출_연증가"], "한국점유율": v["한국점유율"], "한국가공식품_연증가": v["한국가공식품_연증가"],
                          "한국수출_2021→2025_백만달러": [round(v["한국수출_2021USD"] / 1e6, 2), round(v["한국수출_2025USD"] / 1e6, 2)], "수입_최근_백만달러": round(v["수입_최근USD"] / 1e6),
                          "1위": lead["country"] if lead else None,
                          "1위_지표": {"수입_연증가": lm["수입_연증가"], "한국수출_연증가": lm["한국수출_연증가"], "한국점유율": lm["한국점유율"], "한국가공식품_연증가": lm["한국가공식품_연증가"]} if lm else None})
        items.sort(key=lambda x: x["순위"] or 99)
        gaps = [g for g in R.get("자료_빈_곳", []) if g["country"] == c]
        if not gaps:  # 대상 나라의 재수출 확인표에서 바로 만든다
            for h in R.get("재수출_확인", []):
                if h["country"] == c and h.get("import_2025") and h.get("export_2025") and h["export_2025"] / h["import_2025"] > 0.5:
                    gaps.append({"country": c, "cmd": CMD_KEY.get(h["cmd"], h["cmd"]), "빈 곳": "수출(재수출 포함)이 수입의 절반 넘음(수입이 소비인지 모름)", "다음 출처": "그 나라 소비 통계(aT KATI 보고서가 인용하는 유로모니터 등)"})
                    break
        out.append({"나라": c, "표시": m["tag"], "종합순위": m["종합순위"], "종합점수": m["종합점수"],
                    "종합순위_없는_이유": None if m["종합순위"] else "비교 조건(한국 수출 100만 달러·그 나라 수입 2,000만 달러)을 넘는 품목이 2개 미만이라 종합 순위에 안 들어감",
                    "품목별": items, "빈_곳": gaps,
                    "먼저_보낼_품목": (items[0]["품목"] if items else None) if intent == "item_for_country" else None})
    return out


def P(x):
    return "-" if x is None else f"{x*100:.0f}%"


def J(w, a, b):
    """받침에 따라 조사: J('독일','은','는') → 독일은"""
    ch = w[-1]
    return w + (a if ("가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28) else b)


def one_line(ans):
    """질문 종류별 한 줄 답 — 코드가 숫자로 쓴다(모델이 쓰지 않음)."""
    it = ans.get("질문_종류")
    if ans.get("나라_답"):
        parts = []
        for c in ans["나라_답"]:
            if not c["품목별"]:
                parts.append(f"{J(c['나라'],'은','는')} 비교 조건을 넘는 품목이 없어 순위가 없습니다."); continue
            i = c["품목별"][0]; nm = i["품목"].split("(")[0]; L = i.get("1위_지표") or {}
            if it == "item_for_country":
                parts.append(f"{c['나라']}에 먼저 보낼 품목은 {nm}입니다({len(c['품목별'])}개 품목 중 순위가 가장 높은 {i['순위']}위/{i['전체']}, 점수 {i['점수']}). 그 나라 수입은 연 {P(i['수입_연증가'])}, 한국 수출은 연 {P(i['한국수출_연증가'])} 늘었고 점유율은 {i['한국점유율']*100:.2f}%입니다.")
            else:
                cmp = f" 1위 {J(i['1위'],'과','와')} 견주면 그 나라 수입 증가 {P(i['수입_연증가'])} vs {P(L.get('수입_연증가'))}, 한국 수출 증가 {P(i['한국수출_연증가'])} vs {P(L.get('한국수출_연증가'))}, 한국 점유율 {i['한국점유율']*100:.2f}% vs {(L.get('한국점유율') or 0)*100:.2f}%입니다." if L else ""
                g = f" {c['빈_곳'][0]['빈 곳']}." if c["빈_곳"] else ""
                parts.append(f"{J(c['나라'],'은','는')} {nm} {i['순위']}위/{i['전체']}(점수 {i['점수']})입니다.{cmp}{g}" + (f" {c['종합순위_없는_이유']}." if c.get("종합순위_없는_이유") else ""))
        return " ".join(parts)
    if it == "rising" and ans.get("올라오는_곳"):
        return "지금은 작지만 올라오는 곳은 " + ", ".join(f"{x['나라']} {x['품목'].split('(')[0]}(한국 수출 연 {P(x['연증가'])}, 시장 {x['시장_백만달러']}백만 달러)" for x in ans["올라오는_곳"][:3]) + "입니다. 바로 보낼 곳이 아니라 테스트 물량을 넣어 볼 곳입니다."
    if it == "gaps" and ans.get("모르는_것"):
        return "이 자료로 모르는 것은 " + "; ".join(f"{g['country']} {g['빈 곳']}" for g in ans["모르는_것"][:4]) + " 등입니다. 다음 출처는 표에 있습니다."
    t = ans.get("유망국가_TOP3")
    if t:
        if not t["나라"]:
            return ans.get("주의") or "해당 조건에 맞는 나라가 없습니다."
        k = ans.get("검산") or {}
        cnt = k.get("등장횟수") or {}
        return f"유망국가 TOP3는 {' · '.join(t['나라'])}입니다({t['기준']})." + (f" 기준과 비교 범위를 바꿔 {k.get('세트수')}번 다시 계산해도 " + ", ".join(f"{c} {cnt.get(c, 0)}번" for c in t["나라"] if c in cnt) + " TOP3에 남았습니다." if cnt else "")
    return ""


def answer_from_results(plan):
    """계획이 정한 품목·지역으로 결과 파일을 좁혀 실제 답을 만든다(코드)."""
    hs = {s["args"].get("hs") for s in plan["steps"] if s["args"].get("hs")}
    region = next((s["args"].get("region") for s in plan["steps"] if s["args"].get("region")), None)
    codes = region_codes(region)
    region_names = {c["country"] for c in R["종합_전체순위_현지공장국가_제외"] if c["code"] in codes} | {c["country"] for v in R["품목별_전체순위_현지공장국가_제외"].values() for c in v if c["code"] in codes} | {x["country"] for x in R.get("올라오는_나라", []) if x["code"] in codes} if codes else None
    tools = [s["tool"] for s in plan["steps"]]
    ans = {"품목": [CMD_KEY[h] for h in hs if h in CMD_KEY], "지역": region or "전체"}
    intent = plan.get("intent") or "top3"
    focus = [c for c in (plan.get("focus_countries") or []) if c in R.get("나라별_지표", {})]
    ans["질문_종류"] = intent
    if intent in ("why_country", "item_for_country", "compare") and focus:
        ans["나라_답"] = country_answer(focus, hs, intent)

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
        if len(hs) == 1 and per:
            k0 = next(iter(per)); ans["유망국가_TOP3"] = {"기준": k0 + (f" · {region}" if codes else ""), "나라": [c["country"] for c in per[k0]]}
        else:
            ans["유망국가_TOP3"] = {"기준": "종합(현지 공장 나라 제외)" + (f" · {region}" if codes else ""), "나라": [t["country"] for t in top[:3]]}
        ans = {"유망국가_TOP3": ans.pop("유망국가_TOP3"), **ans}
    if "explain" in tools:
        want = {c["country"] for k, v in ans.get("품목별_TOP3", R["품목별_TOP3_현지공장국가_제외"]).items() for c in v}
        if focus:
            want = set(focus)
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
    ans["한_줄_답"] = one_line(ans)
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


TEMPLATE_CSV = "나라,품목코드,연도,수출액_USD,수출무게_kg\n영국,1905,2021,4000474,\n영국,1905,2025,7013029,\n네덜란드,2105,2025,2230000,\n"
KNOWN = {c["country"]: c["code"] for c in R["종합_전체순위_현지공장국가_제외"]} | {c["country"]: c["code"] for v in R["품목별_전체순위_현지공장국가_제외"].values() for c in v}


@app.get("/template.csv")
def template():
    from fastapi.responses import Response
    return Response(content="\ufeff" + TEMPLATE_CSV, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=lotte_export_template.csv"})


@app.post("/upload")
async def upload(file: UploadFile = File(...), code: str = Form("")):
    """부족한 자료 올리기 — 지금은 읽고 검사해서 어디에 쓰일지만 보여 준다. 저장하지 않고 점수도 바꾸지 않는다(본선에서 반영)."""
    if ACCESS_CODE and code != ACCESS_CODE:
        raise HTTPException(401, "비밀번호가 다릅니다.")
    raw = await file.read()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "1MB 이하 CSV만 받습니다.")
    text = None
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc); break
        except Exception:
            continue
    if text is None:
        raise HTTPException(400, "글자 인코딩을 못 읽었습니다(UTF-8 또는 CP949).")
    import csv, io
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise HTTPException(400, "표에 행이 없습니다. 서식 CSV를 내려받아 채워 주세요.")
    need = ["나라", "품목코드", "연도", "수출액_USD"]
    cols = list(rows[0].keys())
    missing = [c for c in need if c not in cols]
    if missing:
        raise HTTPException(400, f"필요한 열이 없습니다: {missing}. 서식 CSV의 열 이름을 그대로 써 주세요.")
    bad, countries, hs, years, unknown = 0, set(), set(), set(), set()
    for r in rows:
        c = (r.get("나라") or "").strip(); h = (r.get("품목코드") or "").strip(); y = (r.get("연도") or "").strip(); v = (r.get("수출액_USD") or "").replace(",", "").strip()
        if not (c and h and y and v):
            bad += 1; continue
        try:
            float(v); int(y)
        except Exception:
            bad += 1; continue
        (countries if c in KNOWN else unknown).add(c); hs.add(h); years.add(y)
    return {"파일": file.filename, "행": len(rows), "못 읽은 행": bad, "아는 나라": sorted(countries), "모르는 나라(이름 확인 필요)": sorted(unknown)[:10],
            "품목코드": sorted(hs), "연도": sorted(years),
            "어디에 쓰이나": ["품목별 한국 전체 수출 대신 롯데 수출 증가율로 kgrow 지표를 바꿈", "품목 비중을 한국 전체 비중 대신 롯데 품목별 실적 비중으로", "제품군↔품목코드 연결표를 실제 신고 코드로 교체"],
            "지금 상태": "읽고 검사만 했습니다. 서버에 저장하지 않았고 점수도 바꾸지 않았습니다. 점수 반영은 롯데 자료를 받는 본선에서 붙입니다."}


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
    except Exception as e:  # 모델 쪽 오류는 사실대로(서버 로그에 상세, 화면엔 종류만)
        import traceback; traceback.print_exc()
        raise HTTPException(502, f"모델 호출 실패: {type(e).__name__}: {str(e)[:120]}")
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
    rec["다음_질문_예시"] = next_questions(rec.get("답") or {}, q)
    rec["전체_초"] = round(time.time() - t0, 2)
    return JSONResponse(rec)


def next_questions(ans, q):
    top = (ans.get("유망국가_TOP3") or {}).get("나라") or []
    out = []
    if ans.get("나라_답"):
        c = ans["나라_답"][0]["나라"]
        out.append(f"{c}에 먼저 보낼 품목은?" if ans.get("질문_종류") != "item_for_country" else f"{c}에서 그 품목이 1위인 나라와 비교해줘")
        out.append("K-푸드 수출 유망국가 TOP3는 어디인가")
    if top:
        out.append(f"{top[0]}에 먼저 보낼 품목과 그 이유는?")
        if len(top) > 1:
            out.append(f"왜 {top[1]}인가, 근거 숫자로 보여줘")
    if "올라오는_곳" not in ans:
        out.append("지금은 작지만 빠르게 올라오는 나라는 어디야?")
    if "모르는_것" not in ans:
        out.append("이 답에서 모르는 것과 더 필요한 자료는?")
    if "유럽" not in q:
        out.append("유럽에서만 보면 어디가 유망해?")
    if "아시아" not in q and "동남아" not in q:
        out.append("동남아에서 캔디는 어느 나라부터?")
    out.append("독일은 입점국인데 왜 순위가 낮아?")
    return [x for x in out if x != q][:5]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
