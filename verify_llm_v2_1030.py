"""검증 단계 v2 — 모델이 자유롭게 쓴 문장의 숫자를, 문장이 인용한 근거 행에서 다시 계산한 값과 대조한다.

규칙
- 인용한 근거 행 id가 없거나 존재하지 않으면 → 숨김
- 문장 속 숫자(달러·kg·톤·%·배·연도)를 뽑아 단위를 맞춘 뒤, 인용 행의 값·연평균 증가율·전체 증가율·배수·차이·점유율 중 하나와
  표시 자릿수 한 칸 안(반올림·버림 모두 허용, 「약」이 붙으면 5%까지)에서 맞아야 통과. 쉼표 자리가 틀린 숫자(예: 4,74)는 숨김 → 하나라도 안 맞으면 숨김
- 숫자가 없는 문장은 통과시키되 「숫자 없음 — 사람 확인」 표시
사용: python3 verify_llm.py  → 결과/검증_모델문장.json
"""
import json, re, pathlib, itertools

HERE = pathlib.Path(__file__).parent
R = json.load(open(HERE / "결과" / "시범결과.json", encoding="utf-8"))
ROWS = {e["id"]: e for e in R["근거행"]}

NUM = r"(\d[\d,]*(?:\.\d+)?)"


def korean_amount(s):
    """「12억 3,614만」「1억2,103만」「5,834만 5,463」「7.61억」 → 숫자. 소수 자릿수(정밀도용)도 돌려줌."""
    s = s.replace(" ", "")
    total, prec = 0.0, None
    m = re.fullmatch(r"(?:(\d[\d,]*(?:\.\d+)?)억)?(?:(\d[\d,]*(?:\.\d+)?)만)?(\d[\d,]*(?:\.\d+)?)?", s)
    if not m or not any(m.groups()):
        return None, None
    for g, mul in zip(m.groups(), (1e8, 1e4, 1)):
        if g:
            v = float(g.replace(",", ""))
            total += v * mul
            d = len(g.split(".")[1]) if "." in g else 0
            p = mul * 10 ** -d
            prec = p if prec is None else min(prec, p)
    return total, prec


BAD_COMMA = re.compile(r"\d,(?!\d{3}(?!\d))")


def extract(text):
    """(종류, 값, 허용오차, 원문) 목록. 쉼표 자리가 틀린 숫자는 ("bad", …)"""
    out = []
    for m in BAD_COMMA.finditer(text):
        out.append(("bad", 0, 0, text[max(0, m.start() - 6):m.end() + 4]))
    t = text
    # 금액: …억 …만 … 달러 / …백만 달러
    for m in re.finditer(r"(약\s*)?((?:\d[\d,]*(?:\.\d+)?\s*억\s*)?(?:\d[\d,]*(?:\.\d+)?\s*만\s*)?(?:\d[\d,]*(?:\.\d+)?)?)\s*(백만\s*)?달러", t):
        body = m.group(2).strip()
        if not body:
            continue
        if m.group(3):
            v = float(body.replace(",", "")); d = len(body.split(".")[1]) if "." in body else 0
            val, prec = v * 1e6, 1e6 * 10 ** -d
        else:
            val, prec = korean_amount(body)
        if val is None:
            continue
        out.append(("usd", val, max(prec, (0.05 * val) if m.group(1) else 0), m.group(0)))
    for m in re.finditer(r"(약\s*)?((?:\d[\d,]*(?:\.\d+)?\s*억\s*)?(?:\d[\d,]*(?:\.\d+)?\s*만\s*)?(?:\d[\d,]*(?:\.\d+)?)?)\s*(kg|톤)", t):
        body = m.group(2).strip()
        if not body:
            continue
        val, prec = korean_amount(body)
        if val is None:
            continue
        mul = 1000 if m.group(3) == "톤" else 1
        out.append(("kg", val * mul, max(prec * mul, (0.05 * val * mul) if m.group(1) else 0), m.group(0)))
    for m in re.finditer(r"(약\s*)?(-?\d+(?:\.\d+)?)\s*%", t):
        v = float(m.group(2)); d = len(m.group(2).split(".")[1]) if "." in m.group(2) else 0
        out.append(("pct", v, max(10 ** -d, abs(v) * 0.05 if m.group(1) else 0), m.group(0)))
    for m in re.finditer(r"(약\s*)?(\d+(?:\.\d+)?)\s*배", t):
        v = float(m.group(2)); d = len(m.group(2).split(".")[1]) if "." in m.group(2) else 0
        out.append(("ratio", v, max(10 ** -d, v * 0.05 if m.group(1) else 0), m.group(0)))
    for m in re.finditer(r"(20\d\d)\s*년", t):
        out.append(("year", int(m.group(1)), 0, m.group(0)))
    return out


def allowed(ids):
    vals = {"usd": [], "kg": [], "pct": [], "ratio": [], "year": set()}
    rs = [ROWS[i] for i in ids]
    for r in rs:
        u = "usd" if r["unit"] == "USD" else "kg"
        vs = list(r["values"].values())
        vals[u] += vs
        vals["year"] |= {int(y) for y in r["values"]}
        if "cagr" in r:
            vals["pct"].append(r["cagr"] * 100)
        if "share_2025" in r:
            vals["pct"].append(r["share_2025"] * 100)
        if len(vs) == 2:
            a, b = vs
            vals["pct"].append((b / a - 1) * 100)
            vals["ratio"].append(b / a)
            vals[u].append(b - a)
    # 같은 단위 행끼리 비교(차이·배수·비율) — 인용한 행 안에서만
    for r1, r2 in itertools.permutations(rs, 2):
        if r1["unit"] != r2["unit"]:
            continue
        for y in set(r1["values"]) & set(r2["values"]):
            a, b = r1["values"][y], r2["values"][y]
            if b:
                vals["ratio"].append(a / b)
                vals["pct"].append(a / b * 100)
            vals["usd" if r1["unit"] == "USD" else "kg"].append(abs(a - b))
    return vals


def check(sent):
    ids = sent.get("row_ids") or []
    if not ids:
        return "숨김", "근거 행 없음"
    bad = [i for i in ids if i not in ROWS]
    if bad:
        return "숨김", f"없는 근거 행 {bad}"
    nums = extract(sent["text"])
    if not nums:
        return "표시(사람 확인)", "숫자 없음"
    A = allowed(ids)
    for kind, v, tol, raw in nums:
        if kind == "bad":
            return "숨김", f"숫자 형식 오류 「{raw}」"
        if kind == "year":
            if v not in A["year"]:
                return "숨김", f"연도 {raw} 가 인용 행에 없음"
            continue
        cands = A[kind]
        if not any(abs(v - c) <= tol + 1e-9 for c in cands):
            near = min(cands, key=lambda c: abs(c - v)) if cands else None
            return "숨김", f"{raw} 불일치(가장 가까운 값 {near:,.2f})" if near is not None else f"{raw} 비교할 값 없음"
    return "표시", "통과"


def run(path, label_key=None):
    d = json.load(open(path, encoding="utf-8"))
    sents = [s for c in d["countries"] for s in c["sentences"]] if "countries" in d else d["sentences"]
    res = []
    for s in sents:
        verdict, why = check(s)
        res.append({"text": s["text"], "row_ids": s["row_ids"], "판정": verdict, "이유": why,
                    **({"모델표시_틀림": s[label_key], "모델설명": s.get("what_changed", "")} if label_key else {})})
    return res


if __name__ == "__main__":
    out = {}
    for name, label in (("모델문장_정상", None), ("모델문장_함정", "is_wrong"), ("모델문장_틀림20", "is_wrong"), ("모델문장_맞음20", "is_wrong"), ("모델문장_화면용", None)):
        p = HERE / "결과" / f"{name}.json"
        if p.exists():
            out[name] = run(p, label)
    (HERE / "결과" / "검증_모델문장.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for k, v in out.items():
        print("==", k, {x: sum(1 for r in v if r["판정"] == x) for x in ("표시", "표시(사람 확인)", "숨김")})
        for r in v:
            print(" ", r["판정"], "|", r["이유"], "|", r.get("모델표시_틀림", ""), "|", r["text"][:90])
