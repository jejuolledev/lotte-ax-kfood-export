"""검증 단계 v3 (2026-10-31) — 모델이 자유롭게 쓴 문장의 숫자를, 문장이 인용한 근거 행에서 다시 계산한 값과 대조한다.
v2(verify_llm_v2_1030.py)에 AI 전문가 심사(QA_1031/B 1-1)가 든 구멍을 막은 판.

규칙
- 인용한 근거 행 id가 없거나 존재하지 않으면 → 숨김
- 문장 속 숫자를 뽑는다. 단위: 달러·USD·$·dollars / kg·톤 / % / %p / 배 / 연도(「년」이 없어도 20xx는 연도).
  자릿수 말: 조·십억·억·천만·백만·십만·만·천·백, billion·million·thousand·bn·mn·B·M·K.
  숫자가 있는데 단위를 못 읽으면 통과가 아니라 「숨김(단위 불명)」. 「A(자릿수만)에서 B(단위)로」 꼴이면 A는 B의 단위를 따른다.
- 값 하나하나가 인용 행의 값·차이·배수·증가율·연평균·점유율 중 하나와 맞아야 한다. 맞는다 = 다음 둘 다
  (1) 표시 자릿수 반 칸 안(반올림) 또는 자릿수 아래를 버린 것(한 칸 아래쪽만)   (2) 상대오차 2% 안. 「약」이 붙으면 (2)만 5%.
  배수는 「3배」처럼 정수여도 소수 첫째 자리 반올림 기준(2.95~3.05)으로 본다. 「약 3배」는 ±5%.
- 무게(kg) 행에서 나온 증가율·배수는 문장에 「무게/중량/kg/톤」이 있을 때만 후보로 쓴다(금액 문장에 무게 증가율을 쓰면 숨김).
- 문장에 「2021년 7.61억 달러」처럼 (연도, 값) 짝이 있으면 그 연도의 값이어야 한다(인용 행 안의 다른 연도 값과 맞아도 숨김).
  문장에 연도가 하나뿐이면(「2025년 … 점유율은 0.6%」) 연도가 붙는 값(행 값·점유율·같은 해 차이)은 그 연도 것이어야 한다.
- 문장에 「X에서 Y로 늘었다/줄었다」가 있으면 Y−X 부호가 말과 맞아야 한다(「않」이 있으면 안 봄).
- 문장 속 나라·품목 이름이 인용 행에 없으면 숨김. 여러 행을 인용했으면 값은 문장에 이름이 나온 나라·품목의 행에서만 찾는다.
- 연도는 인용 행에 있는 연도여야 한다.
- 숫자가 없는 문장은 「표시(사람 확인)」. 숫자는 맞는데 「…일 수 있어」「…해야 한다」 같은 판단이 붙은 문장은 「표시(해석은 사람 확인)」.
사용: python3 verify_llm.py  → 결과/검증_모델문장.json
"""
import json, re, pathlib, itertools

HERE = pathlib.Path(__file__).parent
R = json.load(open(HERE / "결과" / "시범결과.json", encoding="utf-8"))
ROWS = {e["id"]: e for e in R["근거행"]}

REL_TOL = 0.02        # 상대오차(「약」 없을 때)
REL_TOL_ABOUT = 0.05  # 「약」이 붙었을 때

SCALE = {"조": 1e12, "십억": 1e9, "억": 1e8, "천만": 1e7, "백만": 1e6, "십만": 1e5, "만": 1e4, "천": 1e3, "백": 1e2,
         "billion": 1e9, "million": 1e6, "thousand": 1e3, "bn": 1e9, "mn": 1e6, "B": 1e9, "M": 1e6, "K": 1e3}
SCALE_RE = r"(?:십억|천만|백만|십만|조|억|만|천|백|billion|million|thousand|bn|mn|B|M|K)"
NUM_RE = r"\d[\d,]*(?:\.\d+)?"
# 「12억 3,614만」「7.61억」「70,130천」「9.9 billion」「761.3백만」 : (숫자 자릿수말)+ 끝에 숫자만 올 수도 있음
AMOUNT_RE = rf"(?:{NUM_RE}\s*{SCALE_RE}\s*)+(?:{NUM_RE}(?![\d.,]))?|{NUM_RE}"
CUR_AFTER = r"(?:달러|dollars?|USD)"
CUR_BEFORE = r"(?:USD|US\$|\$)"
WEIGHT = r"(?:kg|킬로그램|톤|t(?![a-zA-Z]))"

BAD_COMMA = re.compile(r"\d,(?!\d{3}(?!\d))")
UP = ("늘", "증가", "성장", "커", "확대", "급증", "상승", "올랐", "상회", "웃돌")
DOWN = ("줄", "감소", "하락", "축소", "떨어", "내렸", "하회", "밑돌", "작아", "급감")
JUDGE = ("일 수 있", "수 있어", "해야 한다", "봐야 한다", "때문", "가능성", "보기는 어렵", "으로 보인다", "것으로 보")

PRODUCT = {"1704": ("캔디", "껌", "사탕"), "1905": ("비스킷", "과자"), "1806": ("초콜릿",), "2105": ("아이스크림", "빙과"), "16-21": ("가공식품",)}
COUNTRIES = {r["country"] for r in ROWS.values()} | {"프랑스", "일본", "중국", "베트남", "스페인", "폴란드", "이탈리아", "캐나다", "호주", "대만", "태국",
                                                       "싱가포르", "홍콩", "멕시코", "인도네시아", "말레이시아", "필리핀", "인도", "몽골", "러시아", "벨기에", "스위스"}


def parse_amount(s):
    """「12억 3,614만」「7.61억」「70,130천」「9.9 billion」「3,614」 → (값, 표시 자릿수 한 칸의 크기). 못 읽으면 (None, None)."""
    s = s.strip()
    total, prec, pos = 0.0, None, 0
    for m in re.finditer(rf"({NUM_RE})\s*({SCALE_RE})?\s*", s):
        if m.start() != pos:
            return None, None
        pos = m.end()
        g, sc = m.group(1), m.group(2)
        v = float(g.replace(",", ""))
        mul = SCALE[sc] if sc else 1.0
        total += v * mul
        d = len(g.split(".")[1]) if "." in g else 0
        p = mul * 10 ** -d
        prec = p if prec is None else min(prec, p)
    if pos != len(s) or prec is None:
        return None, None
    return total, prec


def _dec(g):
    return len(g.split(".")[1]) if "." in g else 0


def extract(text):
    """문장 속 숫자 → dict(kind, val, prec, about, raw, start, end) 목록. 종류: usd, kg, pct, pctp, ratio, year, bad, unknown."""
    out, used = [], []

    def take(kind, val, prec, about, m, s=None, e=None):
        s = m.start() if s is None else s; e = m.end() if e is None else e
        if any(not (e <= a or s >= b) for a, b in used):
            return
        used.append((s, e))
        out.append(dict(kind=kind, val=val, prec=prec, about=about, raw=text[s:e], start=s, end=e))

    for m in BAD_COMMA.finditer(text):
        take("bad", 0, 0, False, m, max(0, m.start() - 6), m.end() + 4)
    t = re.sub(r"\b\d{3}-\d{4}-[A-Z]\b|\b\d{3}-KF\b|HS\s*\d{4}", lambda m: " " * len(m.group(0)), text)  # 근거 행 id·HS 코드는 숫자 아님
    # 금액: 「약 7.61억 달러」「USD 9.9 billion」「$58.6 million」「9.9 billion USD」
    for m in re.finditer(rf"(약\s*)?({AMOUNT_RE})\s*{CUR_AFTER}", t):
        v, p = parse_amount(m.group(2))
        if v is not None:
            take("usd", v, p, bool(m.group(1)), m)
    for m in re.finditer(rf"(약\s*)?{CUR_BEFORE}\s*({AMOUNT_RE})", t):
        v, p = parse_amount(m.group(2))
        if v is not None:
            take("usd", v, p, bool(m.group(1)), m)
    # 무게
    for m in re.finditer(rf"(약\s*)?({AMOUNT_RE})\s*({WEIGHT})", t):
        v, p = parse_amount(m.group(2))
        if v is not None:
            mul = 1000 if m.group(3).startswith("톤") or m.group(3) == "t" else 1
            take("kg", v * mul, p * mul, bool(m.group(1)), m)
    # %p, %, 배
    for m in re.finditer(r"(약\s*)?(-?\d+(?:\.\d+)?)\s*%p", t):
        take("pctp", float(m.group(2)), 10 ** -_dec(m.group(2)), bool(m.group(1)), m)
    for m in re.finditer(r"(약\s*)?(-?\d+(?:\.\d+)?)\s*%(?!p)", t):
        take("pct", float(m.group(2)), 10 ** -_dec(m.group(2)), bool(m.group(1)), m)
    for m in re.finditer(r"(약\s*)?(\d+(?:\.\d+)?)\s*배", t):
        g = m.group(2)
        take("ratio", float(g), 10 ** -max(1, _dec(g)), bool(m.group(1)), m)  # 정수 배수도 소수 첫째 자리 기준
    # 연도(「년」 없어도 20xx)
    for m in re.finditer(r"(?<![\d.,])(20\d\d)(?![\d.,])\s*년?", t):
        take("year", int(m.group(1)), 0, False, m)
    # 「A(자릿수만)에서 B(단위)로」 — A는 B 단위를 따름
    for m in re.finditer(rf"(약\s*)?({AMOUNT_RE})\s*에서", t):
        if any(not (m.end() <= a or m.start() >= b) for a, b in used):
            continue
        nxt = [x for x in out if x["start"] > m.end() and x["kind"] in ("usd", "kg")]
        if nxt and re.search(r"(으로|로)", t[m.end():nxt[0]["end"] + 8]):
            v, p = parse_amount(m.group(2))
            if v is not None:
                mul = 1000 if nxt[0]["kind"] == "kg" and "톤" in nxt[0]["raw"] else 1
                take(nxt[0]["kind"], v * mul, p * mul, bool(m.group(1)), m, m.start(), m.start(2) + len(m.group(2)))
    # 남은 숫자(단위를 못 읽음)
    for m in re.finditer(NUM_RE, t):
        if any(not (m.end() <= a or m.start() >= b) for a, b in used):
            continue
        take("unknown", 0, 0, False, m, max(0, m.start() - 4), min(len(t), m.end() + 6))
    out.sort(key=lambda x: x["start"])
    return out


def candidates(ids):
    """인용 행에서 만들 수 있는 값들. 각 후보 = (kind, 값, 출처 행 집합, 연도 또는 None)."""
    C = []
    rs = [ROWS[i] for i in ids]
    for r in rs:
        u = "usd" if r["unit"] == "USD" else "kg"
        ys = sorted(r["values"])
        for y in ys:
            C.append((u, r["values"][y], {r["id"]}, int(y)))
        if "cagr" in r:
            C.append(("pct", r["cagr"] * 100, {r["id"]}, None))
        if "share_2025" in r:
            C.append(("pct", r["share_2025"] * 100, {r["id"]}, 2025))
        if len(ys) == 2:
            a, b = r["values"][ys[0]], r["values"][ys[1]]
            C.append(("pct", (b / a - 1) * 100, {r["id"]}, None))
            C.append(("ratio", b / a, {r["id"]}, None))
            C.append((u, b - a, {r["id"]}, None))
    for r1, r2 in itertools.permutations(rs, 2):
        if r1["unit"] != r2["unit"]:
            continue
        u = "usd" if r1["unit"] == "USD" else "kg"
        for y in set(r1["values"]) & set(r2["values"]):
            a, b = r1["values"][y], r2["values"][y]
            if b:
                C.append(("ratio", a / b, {r1["id"], r2["id"]}, int(y)))
                C.append(("pct", a / b * 100, {r1["id"], r2["id"]}, int(y)))
            C.append((u, abs(a - b), {r1["id"], r2["id"]}, int(y)))
    pcts = [c for c in C if c[0] == "pct"]
    for c1, c2 in itertools.permutations(pcts, 2):
        C.append(("pctp", c1[1] - c2[1], c1[2] | c2[2], None))
    return C


def close(shown, actual, prec, about, kind):
    """표시값 shown 이 실제값 actual 과 맞는가. (1) 반올림 반 칸 또는 버림 한 칸(아래쪽만) (2) 상대오차 2%(「약」 5%)."""
    diff = actual - shown
    eps = 1e-9 * max(1.0, abs(actual))
    digit_ok = abs(diff) <= prec / 2 + eps or (-eps <= diff < prec - eps)
    if about:
        digit_ok = True
    rel = abs(diff) / abs(actual) if actual else abs(diff)
    rel_ok = rel <= (REL_TOL_ABOUT if about else REL_TOL) + 1e-12
    if kind == "ratio" and not about:
        digit_ok = abs(diff) <= 0.05 + eps if prec >= 0.1 else abs(diff) <= prec / 2 + eps
    return digit_ok and rel_ok


def mentioned(text):
    cs = {c for c in COUNTRIES if c in text}
    ps = {cmd for cmd, kws in PRODUCT.items() if any(k in text for k in kws)}
    return cs, ps


def check(sent):
    ids = sent.get("row_ids") or []
    if not ids:
        return "숨김", "근거 행 없음"
    bad = [i for i in ids if i not in ROWS]
    if bad:
        return "숨김", f"없는 근거 행 {bad}"
    text = sent["text"]
    nums = extract(text)
    if not nums:
        return "표시(사람 확인)", "숫자 없음"
    for x in nums:
        if x["kind"] == "bad":
            return "숨김", f"숫자 형식 오류 「{x['raw'].strip()}」"
        if x["kind"] == "unknown":
            return "숨김", f"단위 불명 「{x['raw'].strip()}」"
    # 나라·품목 이름 대조
    rs = [ROWS[i] for i in ids]
    cs, ps = mentioned(text)
    row_cs = {r["country"] for r in rs}
    row_ps = {r["cmd"] for r in rs}
    if cs - row_cs:
        return "숨김", f"인용 행에 없는 나라 {sorted(cs - row_cs)}"
    if ps - row_ps:
        return "숨김", f"인용 행에 없는 품목 {sorted(ps - row_ps)}"
    ok_rows = {r["id"] for r in rs if (not cs or r["country"] in cs) and (not ps or r["cmd"] in ps)}
    weight_word = bool(re.search(r"무게|중량|kg|톤", text))
    years = {int(y) for r in rs for y in r["values"]}
    C = [c for c in candidates(ids) if c[2] <= ok_rows]
    if not weight_word:
        kg_rows = {r["id"] for r in rs if r["unit"] != "USD"}
        C = [c for c in C if c[0] in ("usd", "kg") or not (c[2] & kg_rows)]

    # (연도, 값) 짝
    def paired_year(x):
        before = text[max(0, x["start"] - 8):x["start"]]
        m = re.search(r"(20\d\d)\s*년?\s*(?:에는|에|의|말)?\s*$", before)
        return int(m.group(1)) if m else None

    sent_years = {x["val"] for x in nums if x["kind"] == "year"}
    only_year = next(iter(sent_years)) if len(sent_years) == 1 else None  # 문장에 연도가 하나뿐이면 연도 붙은 값은 그 연도 것이어야 함
    for x in nums:
        if x["kind"] == "year":
            if x["val"] not in years:
                return "숨김", f"연도 {x['raw'].strip()} 가 인용 행에 없음"
            continue
        y = paired_year(x) if x["kind"] in ("usd", "kg") else None
        cands = [c for c in C if c[0] == x["kind"] and (y is None or c[3] == y) and (only_year is None or c[3] in (None, only_year))]
        if not any(close(x["val"], c[1], x["prec"], x["about"], x["kind"]) for c in cands):
            near = min(cands, key=lambda c: abs(c[1] - x["val"])) if cands else None
            tag = f"{y}년 값으로 " if y else ""
            return "숨김", (f"{x['raw'].strip()} {tag}불일치(가장 가까운 값 {near[1]:,.2f})" if near else f"{x['raw'].strip()} {tag}비교할 값 없음")
    # 방향: 「X에서 Y로 … 늘었다/줄었다」
    for i, x in enumerate(nums):
        if x["kind"] not in ("usd", "kg", "pct", "ratio"):
            continue
        after = text[x["end"]:x["end"] + 3]
        if not after.lstrip().startswith("에서"):
            continue
        ys_ = [z for z in nums[i + 1:] if z["kind"] == x["kind"]]
        if not ys_:
            continue
        z = ys_[0]
        if not re.match(r"\s*(으로|로)", text[z["end"]:]):
            continue
        clause = re.split(r",|(?<!\d)\.|\.(?!\d)|(?<=고)\s", text[z["end"]:], 1)[0]
        if "않" in clause or x["val"] == z["val"]:
            continue
        hits = sorted([(clause.find(w), "up", w) for w in UP if w in clause] + [(clause.find(w), "down", w) for w in DOWN if w in clause])
        said = hits[0][1] if hits else None; up = dn = hits[0][2] if hits else None  # 「로」 뒤 가장 먼저 나오는 방향 말
        if said and said != ("up" if z["val"] > x["val"] else "down"):
            return "숨김", f"방향 불일치: {x['raw'].strip()}→{z['raw'].strip()} 인데 「{up or dn}」"
    if any(w in text for w in JUDGE):
        return "표시(해석은 사람 확인)", "숫자 통과·해석 문구 있음"
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
        print("==", k, {x: sum(1 for r in v if r["판정"] == x) for x in ("표시", "표시(해석은 사람 확인)", "표시(사람 확인)", "숨김")})
        for r in v:
            print(" ", r["판정"], "|", r["이유"], "|", r.get("모델표시_틀림", ""), "|", r["text"][:90])
