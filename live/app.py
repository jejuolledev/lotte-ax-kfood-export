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


PLANT = {"카자흐스탄", "파키스탄", "벨기에", "인도", "러시아", "미얀마"}  # 롯데웰푸드 현지 공장 나라(IR) — 추천 대상에서 제외
ALIAS = {"사우디": "사우디아라비아", "UAE": "아랍에미리트", "아랍에미리트연합": "아랍에미리트", "두바이": "아랍에미리트", "UK": "영국", "잉글랜드": "영국", "USA": "미국", "US": "미국", "미합중국": "미국",
         "홀란드": "네덜란드", "화란": "네덜란드", "타이완": "대만", "오스트레일리아": "호주", "멕시코": "멕시코", "타이": "태국", "베트남": "베트남", "인니": "인도네시아", "필리핀": "필리핀",
         "일본": "일본", "중국": "중국", "홍콩": "홍콩", "싱가포르": "싱가포르", "몽골": "몽골", "독일": "독일", "프랑스": "프랑스", "캐나다": "캐나다", "브라질": "브라질", "아르헨티나": "아르헨티나", "말레이시아": "말레이시아"}


def norm_country(c):
    """줄인 이름·별칭을 자료의 이름으로. 모르면 원문 그대로."""
    c = (c or "").strip()
    if not c:
        return c
    if c in ALIAS:
        return ALIAS[c]
    M = R["나라별_지표"]
    if c in M or c in PLANT:
        return c
    for k in M:
        if k.startswith(c) or c.startswith(k):
            return k
    return c
ITEM_W = R.get("품목_비중_한국수출2025USD", {})
METRIC_NAMES = {"size": "시장 규모", "growth": "수입 성장", "kgrow": "한국 수출 성장", "kfood": "K-푸드 전반"}


def region_codes(region):
    return PT.REGION.get(region or "", None)


def P(x):
    return "-" if x is None else f"{x*100:.0f}%"


def grew(x):
    """증감 말: 늘었/줄었"""
    if x is None:
        return "변화 자료 없음"
    return f"연 {abs(x)*100:.0f}% {'늘었' if x >= 0 else '줄었'}"


def J(w, a, b):
    """받침에 따라 조사: J('독일','은','는') → 독일은"""
    ch = w[-1]
    return w + (a if ("가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28) else b)


def rankings(weights=None, codes=None, excl=None):
    """품목별·종합 순위. weights 가 있으면 나라별 지표의 백분위로 다시 점수를 낸다(코드 계산). codes=지역 안만, excl=뺄 나라 코드."""
    M = R["나라별_지표"]
    per_full = R["품목별_전체순위_현지공장국가_제외"]
    excl = excl or set()
    if weights:
        tot = sum(v for v in weights.values() if v) or 1
        W = {k: (weights.get(k) or 0) / tot for k in ("size", "growth", "kgrow", "kfood")}
        per = {}
        for k in per_full:
            rows = []
            for c, m in M.items():
                if c in PLANT or k not in m["품목"]:
                    continue
                pct = m["품목"][k]["지표백분위"]
                rows.append({"country": c, "code": m["code"], "score": round(sum(W[x] * pct.get(x, 0) for x in W), 1)})
            per[k] = sorted(rows, key=lambda r: -r["score"])
        overall = []
        for c, m in M.items():
            if c in PLANT or len(m["품목"]) < 2:
                continue
            ws = sum(ITEM_W.get(k, 1) for k in m["품목"])
            sc = sum(next(r["score"] for r in per[k] if r["country"] == c) * ITEM_W.get(k, 1) for k in m["품목"]) / ws
            overall.append({"country": c, "code": m["code"], "score": round(sc, 1), "tag": m["tag"], "품목수": len(m["품목"])})
        overall.sort(key=lambda r: -r["score"])
        wnote = "가중치 " + "·".join(f"{METRIC_NAMES[k]} {W[k]*100:.0f}%" for k in W)
    else:
        per = {k: [dict(r) for r in v] for k, v in per_full.items()}
        overall = [dict(r, 품목수=len(M[r["country"]]["품목"])) for r in R["종합_전체순위_현지공장국가_제외"]]
        wnote = None
    f = lambda rows: [r for r in rows if (codes is None or r["code"] in codes) and r["code"] not in excl]
    return {k: f(v) for k, v in per.items()}, f(overall), wnote


def country_answer(focus, hs, intent, per, overall):
    """특정 나라 질문: 그 나라의 순위·점수·지표를 품목 1위와 나란히(자기가 1위면 2위와)."""
    M = R["나라별_지표"]
    GAPS = {g["country"]: g for g in R.get("자료_빈_곳", [])}
    out = []
    for c in focus:
        if c in PLANT:
            out.append({"나라": c, "표시": "롯데웰푸드 현지 공장 나라", "종합순위": None, "종합점수": None, "품목별": [], "빈_곳": [],
                        "종합순위_없는_이유": "현지 공장에서 생산해 공급하는 나라라 수출 추천 대상에서 뺐습니다(IR 기준)", "먼저_보낼_품목": None})
            continue
        m = M.get(c)
        if not m:
            why = (GAPS[c]["빈 곳"] + " → " + GAPS[c]["다음 출처"]) if c in GAPS else "비교 조건(한국 수출 100만 달러·그 나라 수입 2,000만 달러)을 넘는 품목이 없거나 Comtrade 자료가 없어 순위를 내지 못했습니다"
            out.append({"나라": c, "표시": "자료에 없는 나라", "종합순위": None, "종합점수": None, "품목별": [], "빈_곳": [GAPS[c]] if c in GAPS else [],
                        "종합순위_없는_이유": why, "먼저_보낼_품목": None})
            continue
        items, missing = [], []
        for k, v in m["품목"].items():
            if hs and not any(CMD_KEY.get(h) == k for h in hs):
                continue
            rows = per.get(k, [])
            me = next((i for i, r in enumerate(rows) if r["country"] == c), None)
            rank = (me + 1) if me is not None else None
            cmp = next((r for r in rows if r["country"] != c), None)
            cm = M.get(cmp["country"], {}).get("품목", {}).get(k) if cmp else None
            items.append({"품목": k, "순위": rank, "전체": len(rows), "점수": next((r["score"] for r in rows if r["country"] == c), v["품목점수"]), "지표백분위": v["지표백분위"],
                          "수입_연증가": v["수입_연증가"], "수입무게_연증가": v["수입무게_연증가"], "한국수출_연증가": v["한국수출_연증가"], "한국점유율": v["한국점유율"], "한국가공식품_연증가": v["한국가공식품_연증가"],
                          "한국수출_2021→2025_백만달러": [round(v["한국수출_2021USD"] / 1e6, 2), round(v["한국수출_2025USD"] / 1e6, 2)], "수입_최근_백만달러": round(v["수입_최근USD"] / 1e6),
                          "비교": cmp["country"] if cmp else None, "비교_순위": (rows.index(cmp) + 1) if cmp else None, "비교_지표백분위": cm["지표백분위"] if cm else None,
                          "비교_지표": {"수입_연증가": cm["수입_연증가"], "한국수출_연증가": cm["한국수출_연증가"], "한국점유율": cm["한국점유율"], "한국가공식품_연증가": cm["한국가공식품_연증가"]} if cm else None})
        for h in (hs or []):
            k = CMD_KEY.get(h)
            if k and k not in m["품목"]:
                missing.append(k)
        items.sort(key=lambda x: -(x["점수"] or 0))  # 먼저 보낼 품목 = 점수가 가장 높은 품목
        gaps = [g for g in R.get("자료_빈_곳", []) if g["country"] == c]
        if not gaps:
            for h in R.get("재수출_확인", []):
                if h["country"] == c and h.get("import_2025") and h.get("export_2025") and h["export_2025"] / h["import_2025"] > 0.5:
                    gaps.append({"country": c, "cmd": CMD_KEY.get(h["cmd"], h["cmd"]), "빈 곳": "수출(재수출 포함)이 수입의 절반 넘음(수입이 소비인지 모름)", "다음 출처": "그 나라 소비 통계(aT KATI 보고서가 인용하는 유로모니터 등)"})
                    break
        orank = next((i + 1 for i, r in enumerate(overall) if r["country"] == c), None)
        out.append({"나라": c, "표시": m["tag"], "종합순위": orank, "종합점수": next((r["score"] for r in overall if r["country"] == c), None), "종합_전체": len(overall),
                    "종합순위_없는_이유": None if orank else "비교 조건(한국 수출 100만 달러·그 나라 수입 2,000만 달러)을 넘는 품목이 2개 미만이라 종합 순위에는 없음(품목별 순위만)",
                    "품목별": items, "빈_곳": gaps, "품목_없음": missing,
                    "가진_품목": [k.split("(")[0] for k in m["품목"]],
                    "먼저_보낼_품목": (items[0]["품목"] if items else None) if intent == "item_for_country" else None})
    return out


def one_line(ans):
    """질문 종류별 한 줄 답 — 코드가 숫자로 쓴다(모델이 쓰지 않음)."""
    it = ans.get("질문_종류")
    if ans.get("나라_답"):
        parts = []
        for c in ans["나라_답"]:
            if not c["품목별"]:
                if c.get("품목_없음"):
                    parts.append(f"{J(c['나라'],'은','는')} {'·'.join(k.split('(')[0] for k in c['품목_없음'])} 품목이 비교 조건(한국 수출 100만 달러·그 나라 수입 2,000만 달러)을 못 넘어 순위가 없습니다. {c['나라']}에서 조건을 넘는 품목은 {'·'.join(c.get('가진_품목') or []) or '없음'}입니다."); continue
                parts.append(f"{J(c['나라'],'은','는')} {c['종합순위_없는_이유']}."); continue
            i = c["품목별"][0]; nm = i["품목"].split("(")[0]; L = i.get("비교_지표") or {}
            if it == "item_for_country":
                parts.append(f"{c['나라']}에 먼저 보낼 품목은 {nm}입니다({len(c['품목별'])}개 품목 중 점수가 가장 높은 {i['점수']}점, {i['순위']}위/{i['전체']}). 그 나라 수입은 {grew(i['수입_연증가'])}고, 한국 수출은 {grew(i['한국수출_연증가'])}으며 점유율은 {i['한국점유율']*100:.2f}%입니다." + (f" {'·'.join(k.split('(')[0] for k in c['품목_없음'])}은 비교 조건 미달." if c.get("품목_없음") else ""))
            else:
                who = f"{i['비교_순위']}위 {J(i['비교'],'과','와')}" if i.get("비교") else ""
                cmp = f" {who} 견주면 그 나라 수입 증가 {P(i['수입_연증가'])} vs {P(L.get('수입_연증가'))}, 한국 수출 증가 {P(i['한국수출_연증가'])} vs {P(L.get('한국수출_연증가'))}, 한국 점유율 {i['한국점유율']*100:.2f}% vs {(L.get('한국점유율') or 0)*100:.2f}%입니다." if L else ""
                g = f" {c['빈_곳'][0]['빈 곳']}." if c["빈_곳"] else ""
                head = f"{J(c['나라'],'은','는')} {nm} {i['순위']}위/{i['전체']}(점수 {i['점수']})" + (f", 종합 {c['종합순위']}위/{c['종합_전체']}" if c.get("종합순위") else "") + "입니다."
                parts.append(head + cmp + g + (f" {c['종합순위_없는_이유']}." if c.get("종합순위_없는_이유") else ""))
        return " ".join(parts)
    if it == "rising":
        rs = ans.get("올라오는_곳") or []
        if not rs:
            return ans.get("올라오는_곳_주의") or "이 조건(품목·지역)에서는 「올라오는 곳」 규칙에 걸리는 나라가 없습니다."
        new = [x for x in rs if "IR 주요 수출국" != x["표시"]]
        old = [x for x in rs if "IR 주요 수출국" == x["표시"]]
        s_ = "지금은 작지만 올라오는 곳은 " + ", ".join(f"{x['나라']} {x['품목'].split('(')[0]}(한국 수출 연 {P(x['연증가'])}, 시장 {x['시장_백만달러']}백만 달러)" for x in new[:3]) + "입니다. 바로 보낼 곳이 아니라 테스트 물량을 넣어 볼 곳입니다."
        if old:
            s_ += " " + ", ".join(f"{x['나라']} {x['품목'].split('(')[0]}(연 {P(x['연증가'])})" for x in old) + "도 같은 규칙에 걸리지만 이미 주요 수출국이라 「넓힐 곳」입니다."
        return s_
    if it == "gaps" and ans.get("모르는_것"):
        return "이 자료로 모르는 것은 " + "; ".join(f"{g['country']} {g['빈 곳']}" for g in ans["모르는_것"][:4]) + " 등입니다. 다음 출처는 표에 있습니다."
    t = ans.get("유망국가_TOP3")
    if t:
        if not t["나라"]:
            return ans.get("주의") or "해당 조건에 맞는 나라가 없습니다."
        s_ = (f"유망국가 TOP3는 {' · '.join(t['나라'])}입니다({t['기준']})." if len(t['나라']) >= 3 else f"유망국가 종합 순위에 드는 나라는 {' · '.join(t['나라'])}입니다({t['기준']}).")
        if ans.get("종합_셋미만_이유"):
            s_ += " " + ans["종합_셋미만_이유"]
        k = ans.get("검산")
        if k and k.get("해당"):
            cnt = k.get("등장횟수") or {}
            s_ += f" 기준·범위·품목 정의를 바꾼 {k.get('세트수')}가지 계산에서 " + ", ".join(f"{c} {cnt.get(c, 0)}번" for c in t["나라"]) + " TOP3에 남았습니다."
        if ans.get("가중치"):
            s_ += f" ({ans['가중치']}로 다시 계산한 결과)"
        return s_
    return ""


def answer_from_results(plan):
    """계획이 정한 품목·지역·제외·가중치·대상 나라로 결과 파일을 좁혀 실제 답을 만든다(코드)."""
    steps = plan["steps"]
    hs = {s["args"].get("hs") for s in steps if (s.get("args") or {}).get("hs")}
    regions = [s["args"].get("region") for s in steps if (s.get("args") or {}).get("region") and s["args"]["region"] in PT.REGION]
    excl_regions = [r for r in (plan.get("exclude_regions") or []) if r in PT.REGION]
    regions = [r for r in dict.fromkeys(regions) if r not in excl_regions]
    region = "·".join(regions) if regions else None
    codes = set().union(*[PT.REGION[r] for r in regions]) if regions else None
    if codes is not None and all(r in regions for r in PT.REGION):  # 전 지역을 다 적으면 전체와 같음
        codes, region = None, None
    excl = set()
    for r in excl_regions:
        excl |= PT.REGION[r]
    M = R["나라별_지표"]
    excl_names = [norm_country(c) for c in (plan.get("exclude_countries") or [])]
    for c in excl_names:
        if c in M:
            excl.add(M[c]["code"])
    weights = next((s["args"].get("weights") for s in steps if s["tool"] == "score" and (s.get("args") or {}).get("weights")), None)
    weights = {k: v for k, v in (weights or {}).items() if v} or None
    tools = [s["tool"] for s in steps]
    intent = plan.get("intent") or "top3"
    if intent == "off_topic":
        return {"질문_종류": "off_topic", "도구_한계": plan.get("limits"),
                "한_줄_답": "이 질문은 이 에이전트가 다루는 범위(K-푸드 수출 유망국가: 어느 나라에 무슨 품목을, 왜, 얼마나 믿나, 어떤 자료가 더 필요한가) 밖이라 도구를 돌리지 않았습니다. 예: 「캔디 수출 유망국 TOP3는?」 「독일은 왜 순위가 낮아?」 「중동 빼고 빼빼로는 어디로?」"}
    focus_all = [norm_country(c) for c in (plan.get("focus_countries") or [])]
    focus = [c for c in focus_all if c in M or c in PLANT]
    unknown = [c for c in focus_all if c not in M and c not in PLANT]
    per, overall, wnote = rankings(weights, codes, excl)
    if hs:
        per = {k: v for k, v in per.items() if any(CMD_KEY.get(h) == k for h in hs)}
    cond = (" · " + region if codes else "") + (" · " + "·".join(excl_regions) + " 제외" if excl_regions else "") + (" · " + "·".join(excl_names) + " 제외" if excl_names else "")
    ans = {"품목": [CMD_KEY[h] for h in hs if h in CMD_KEY], "지역": region or "전체", "제외": excl_regions + excl_names, "질문_종류": intent}
    if plan.get("limits"):
        ans["도구_한계"] = plan["limits"]
    if wnote:
        ans["가중치"] = wnote
    if unknown:
        ans["주의"] = f"자료에 없는 나라: {', '.join(unknown)} (비교 조건 미달 또는 Comtrade 미보고)"
    if intent in ("why_country", "item_for_country", "compare") and (focus or unknown):
        per_all, overall_all, _ = rankings(weights, None, excl)  # 나라 질문은 지역으로 좁히지 않은 전체 순위로 답한다(7위/26 같은 자리)
        ans["나라_답"] = country_answer(focus + unknown, hs, intent, per_all, overall_all)
    if "score" in tools or intent in ("top3", "compare"):
        per3 = {k: v[:3] for k, v in per.items()}
        ans["품목별_TOP3"] = per3
        ans["종합_순위"] = overall[:5]
        if codes and all(not v for v in per3.values()):
            ans["주의"] = f"{region}에는 비교 조건(한국 수출 100만 달러·그 나라 수입 2,000만 달러 이상)을 넘는 나라가 없음"
        plain = not weights and not codes and not excl  # 기본 계산 그대로일 때만 검산 숫자가 그 답의 근거
        ans["검산"] = {"세트수": R["민감도_세트수"], "등장횟수": R["민감도_TOP3_등장횟수"], "해당": plain and len(hs) != 1}
        if len(hs) == 1 and per3:
            k0 = next(iter(per3)); ans["유망국가_TOP3"] = {"기준": k0 + cond, "나라": [c["country"] for c in per3[k0]]}
        else:
            ans["유망국가_TOP3"] = {"기준": "종합(현지 공장 나라 제외, 품목 2개 이상)" + cond, "나라": [t["country"] for t in overall[:3]]}
            if codes and len(overall) < 3:
                # 지역 안에서 종합 조건(품목 2개 이상)을 넘는 나라가 셋 미만 → 이유와 품목별 다음 후보를 같이 낸다
                M = R["나라별_지표"]
                in_top = {t["country"] for t in overall}
                cands = {}
                for k, v in per.items():
                    for i, r in enumerate(v):
                        if r["country"] in in_top or r["country"] in PLANT:
                            continue
                        cands.setdefault(r["country"], []).append(f"{k.split('(')[0]} {i+1}위")
                nxt = "; ".join(f"{c}({', '.join(x)})" for c, x in list(cands.items())[:3])
                ans["종합_셋미만_이유"] = (f"{region}에서 품목 2개 이상이 비교 조건(한국 수출 100만 달러·그 나라 수입 2,000만 달러)을 넘는 나라는 {len(overall)}곳({'·'.join(in_top)})뿐이라 종합 TOP3가 {len(overall)}곳입니다. "
                                      + (f"한 품목만 넘는 다음 후보는 품목별 순위로 봅니다: {nxt}." if nxt else "") + (" 벨기에는 롯데 현지 공장 나라라 뺐습니다." if region and "유럽" in region else ""))
        ans = {"유망국가_TOP3": ans.pop("유망국가_TOP3"), **ans}
    if "explain" in tools:
        want = set(focus) if focus else {c["country"] for v in ans.get("품목별_TOP3", {}).values() for c in v} or {c["country"] for v in R["품목별_TOP3_현지공장국가_제외"].values() for c in v}
        shown, hidden = [], 0
        for c in SENT.get("countries", []):
            if c["country"] not in want:
                continue
            for s in c.get("sentences", []):
                if hs and not any(any(i.split("-")[1] == h for h in hs) for i in s.get("row_ids", []) if i.count("-") >= 2):
                    continue  # 물은 품목의 문장만
                v = VER.get(s["text"], {})
                srcs = [EV[i]["source"] for i in s.get("row_ids", []) if i in EV]
                if str(v.get("판정", "")).startswith("표시"):
                    shown.append({"나라": c["country"], "문장": s["text"], "출처": srcs, "사람확인": "사람 확인" in str(v.get("판정", ""))})
                else:
                    hidden += 1
        ans["설명_문장"] = shown
        ans["숨긴_문장_수"] = hidden
        ans["설명_주의"] = "문장은 미리 생성해 검증해 둔 것(영국·네덜란드·미국·독일만 있음). 이 화면에서 새로 쓰지 않음. 검증기 v3 통과분만 표시."
        if not shown:
            ans["설명_주의"] += " 이 나라들은 미리 만든 문장이 없습니다."
    if "rising" in tools or intent == "rising":
        rs = R.get("올라오는_나라", [])
        if hs:
            rs = [x for x in rs if any(CMD_KEY.get(h) == x["cmd"] for h in hs)]
        if codes:
            rs = [x for x in rs if x["code"] in codes]
        rs = [x for x in rs if x["code"] not in excl]
        ans["올라오는_곳"] = [{"나라": x["country"], "품목": x["cmd"], "한국수출_2021→2025_백만달러": [round(x["kor_2021_usd"] / 1e6, 2), round(x["kor_2025_usd"] / 1e6, 2)],
                            "연증가": x["kgrow_2021base"], "2022기준": x["kgrow_2022base"], "그나라수입_연증가": x["import_growth"],
                            "시장_백만달러": round(x["그나라_수입시장_USD"] / 1e6), "K푸드전반_연증가": x["한국가공식품_연증가율"], "점유율": x["kor_share_2025"], "표시": x["주의"] or x["tag"]} for x in rs]
        ans["올라오는_곳_규칙"] = R.get("올라오는_나라_규칙")
        if not rs:
            ans["올라오는_곳_주의"] = "이 조건(품목·지역)에서는 규칙에 걸리는 나라가 없음(전체 4곳: " + ", ".join(x["country"] for x in R.get("올라오는_나라", [])) + ")"
    if "gaps" in tools or intent == "gaps":
        ans["모르는_것"] = R.get("자료_빈_곳", [])
    ans["한_줄_답"] = one_line(ans)
    if "fetch_trend" in tools:
        cs = next((s["args"].get("countries") for s in steps if s["tool"] == "fetch_trend"), None) or []
        have = {"영국", "네덜란드", "미국"}
        ans["트렌드_문장"] = {"있음": sorted(set(cs) & have), "없음(다음 출처: aT KATI·KOTRA)": sorted(set(cs) - have)}
    return ans


app = FastAPI(title="K-푸드 수출 유망국가 에이전트", docs_url=None, redoc_url=None, openapi_url=None)


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
    {"자료": "UN Comtrade(유엔 무역통계) 공개 API", "무엇": "나라별 품목 수입(금액·무게)·수출, 한국의 나라별 수출 — HS 1905·1806·1704·2105와 가공식품 16~21류, 2021~2025년 연간치", "범위": "원본 85개 파일(6단위 포함), 종합 순위 16개국·품목별 최대 26개국", "한계": "베트남·몽골·UAE는 2023년까지, 영국 2025년 무게 없음, 멕시코 무게 없음"},
    {"자료": "롯데웰푸드 IR 2025년 4분기·2026년 2분기", "무엇": "해외 공장 나라(제외 규칙), 주요 수출국·입점국(맞춰 보기), 수출 실적", "범위": "공개 자료", "한계": "제품별 수출액·신고 품목코드는 없음"},
    {"자료": "aT KATI 국가조사·시장동향 보고서", "무엇": "소비 트렌드 문장(쪽 번호와 함께)", "범위": "영국·네덜란드·미국 3개국, 직접 뽑음(지원서 예시용. 점수엔 아직 미반영)", "한계": "자동 추출 아직 없음, 다른 나라 없음"},
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
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "CSV 파일만 받습니다(.csv).")
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
    csv.field_size_limit(10_000)
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error as e:
        raise HTTPException(400, f"CSV를 읽지 못했습니다({str(e)[:60]}). 한 칸은 1만 자 이하여야 합니다.")
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
            fv = float(v); iy = int(y)
            import math
            if not math.isfinite(fv) or not (2000 <= iy <= 2030) or fv < 0 or fv > 1e12:
                bad += 1; continue
        except Exception:
            bad += 1; continue
        (countries if c in KNOWN else unknown).add(c); hs.add(h); years.add(y)
    return {"파일": file.filename, "행": len(rows), "못 읽은 행": bad, "아는 나라": sorted(countries), "모르는 나라(이름 확인 필요)": sorted(unknown)[:10],
            "품목코드": sorted(hs), "연도": sorted(years),
            "어디에 쓰이나": ["품목별 한국 전체 수출 대신 롯데 수출 증가율로 kgrow 지표를 바꿈", "품목 비중을 한국 전체 비중 대신 롯데 품목별 실적 비중으로", "제품군↔품목코드 연결표를 실제 신고 코드로 교체"],
            "지금 상태": "읽고 검사만 했습니다. 서버에 저장하지 않았고 점수도 바꾸지 않았습니다. 점수 반영은 롯데 실제 자료를 받는 다음 단계에서 붙입니다."}


@app.get("/status")
def status():
    with _lock:
        return {**_state, "daily_cap": DAILY_CAP, "total_cap": TOTAL_CAP}


@app.post("/ask")
def ask(a: Ask):
    q = (a.question or "").strip()
    if ACCESS_CODE and a.code != ACCESS_CODE:
        raise HTTPException(401, "접근 코드가 다릅니다.")
    if not q or len(q) > 300:
        raise HTTPException(400, "질문은 1~300자.")
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()  # 한국 시간 기준
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
        raise HTTPException(502, f"모델 호출 실패({type(e).__name__}). 잠시 뒤 다시 시도해 주세요.")
    with _lock:
        if usage:
            _state["tokens_in"] += usage.get("input") or 0; _state["tokens_out"] += usage.get("output") or 0
    errs = PT.check_plan(plan)
    rec = {"질문": q, "모델": model, "계획_초": secs, "토큰": usage, "검사": errs or "통과",
           "순서": [{"도구": s["tool"], "이유": s.get("why", ""), "인자": {k: v for k, v in (s.get("args") or {}).items() if v}} for s in plan["steps"]],
           "덧붙임": bool(plan.get("_모델_JSON_뒤_덧붙임")), "질문_이해": plan.get("question_understood")}
    if plan.get("_코드_보충"):
        rec["보충"] = plan["_코드_보충"]
    if not errs:
        rec["실행"] = PT.run_plan(plan) if plan["steps"] else []
        rec["답"] = answer_from_results(plan)
    rec["다음_질문_예시"] = next_questions(rec.get("답") or {}, q)
    rec["전체_초"] = round(time.time() - t0, 2)
    return JSONResponse(rec)


def next_questions(ans, q):
    """직전 답에 나온 나라·품목·빈 곳에서만 꼬리를 무는 질문을 만든다(아무거나 넣지 않음)."""
    it = ans.get("질문_종류")
    out = []
    def short(k):
        return (k or "").split("(")[0]
    if it == "off_topic":
        return ["K-푸드 수출 유망국가 TOP3는 어디인가"]
    if ans.get("나라_답"):
        for c in ans["나라_답"]:
            n = c["나라"]
            if c.get("종합순위_없는_이유") and not c["품목별"]:
                # 공장 나라·자료 없는 나라
                out.append("K-푸드 수출 유망국가 TOP3는 어디인가")
                continue
            top = c["품목별"][0]
            if it == "item_for_country":
                out.append(f"{short(top['품목'])}에서 {n}보다 순위가 높은 나라는?")
                if len(c["품목별"]) > 1:
                    out.append(f"{n}의 {short(c['품목별'][1]['품목'])}는 왜 {c['품목별'][1]['순위']}위야?")
            else:
                out.append(f"{n}에 먼저 보낼 품목은?")
                if top.get("비교"):
                    out.append(f"{J(n,'과','와')} {top['비교']} 중 {short(top['품목'])}는 어디가 나아?")
                    out.append(f"{J(top['비교'],'은','는')} 왜 {short(top['품목'])} {top['비교_순위']}위야?")
            if c.get("빈_곳"):
                out.append(f"{n}에서 모르는 자료는 뭐고 어디서 구해?")
        return [x for x in dict.fromkeys(out) if x != q][:5]
    if it == "rising":
        rs = ans.get("올라오는_곳") or []
        new = [x for x in rs if x["표시"] != "IR 주요 수출국"][:3]
        for x in new:
            out.append(f"{J(x['나라'],'은','는')} 왜 TOP3에 없어?")
        if new:
            out.append(f"{new[0]['나라']}에 테스트 물량을 넣으려면 뭘 더 알아야 해?")
        old = [x for x in rs if x["표시"] == "IR 주요 수출국"]
        if old:
            out.append(f"{old[0]['나라']} {J(short(old[0]['품목']),'은','는')} 지금 몇 위야?")
        out.append("K-푸드 수출 유망국가 TOP3는 어디인가")
        return [x for x in dict.fromkeys(out) if x != q][:5]
    if it == "gaps":
        for g in (ans.get("모르는_것") or [])[:4]:
            if g["country"] not in ("전체",):
                out.append(f"{J(g['country'],'은','는')} 자료가 비어 있는데 어떻게 판단했어?")
        out.append("K-푸드 수출 유망국가 TOP3는 어디인가")
        return [x for x in dict.fromkeys(out) if x != q][:5]
    t = ans.get("유망국가_TOP3") or {}
    names = t.get("나라") or []
    region = ans.get("지역") if ans.get("지역") not in (None, "전체") else None
    items = ans.get("품목") or []
    if names:
        out.append(f"{names[0]}에 먼저 보낼 품목과 그 이유는?")
        if len(names) > 1:
            out.append(f"왜 {names[1]}인가, 근거 숫자로 보여줘")
        if len(names) > 2:
            out.append(f"{J(names[2],'은','는')} 왜 3위야?")
    if ans.get("종합_셋미만_이유"):
        import re as _re
        m = _re.search(r"다음 후보는 품목별 순위로 봅니다: ([^(;]+)\(", ans["종합_셋미만_이유"])
        if m:
            out.append(f"{J(m.group(1).strip(),'은','는')} 왜 종합 순위에 없어?")
    if region:
        out.append(f"{region} 말고 다른 지역에서는 어디가 유망해?")
    if items and len(items) == 1:
        out.append(f"{short(items[0])} 말고 다른 품목은 어디가 유망해?")
    if ans.get("가중치"):
        out.append("가중치를 기본(각 25%)으로 돌리면 TOP3는?")
    if "올라오는_곳" not in ans:
        out.append("지금은 작지만 빠르게 올라오는 나라는 어디야?")
    if "모르는_것" not in ans:
        out.append("이 답에서 모르는 것과 더 필요한 자료는?")
    return [x for x in dict.fromkeys(out) if x != q][:5]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
