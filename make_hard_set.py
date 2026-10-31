"""어려운 시험 세트 만들기(OpenAI 호출 없음, 2026-10-31).
결과/모델문장_맞음20.json(20)·모델문장_화면용.json(16)의 맞는 문장 36개를 규칙으로 바꿔 틀린 문장 50개를 만든다.
바꾸는 규칙 6가지: 방향 뒤집기 / 단위 10배(백만→천만 표기 포함) / 연도 바꾸기(두 연도 자리 맞바꿈, 값-연도 짝이 어긋남) /
배수 ±0.3 / 다른 행 숫자 섞기(그 행 id도 인용에 넣음) / 마지막 자릿수 한 칸 올림.
사용: python3 make_hard_set.py → 결과/검증_어려운세트.json
"""
import json, re, pathlib
import verify_llm as V

HERE = pathlib.Path(__file__).parent
ROWS = V.ROWS
TOK = re.compile(rf"^(약\s*)?({V.NUM_RE})\s*({V.SCALE_RE})?\s*(달러|kg|톤|%|배)$")


def originals():
    out = []
    for name in ("모델문장_맞음20", "모델문장_화면용"):
        d = json.load(open(HERE / "결과" / f"{name}.json", encoding="utf-8"))
        sents = [s for c in d["countries"] for s in c["sentences"]] if "countries" in d else d["sentences"]
        out += [{"세트": name, "text": s["text"], "row_ids": s["row_ids"]} for s in sents]
    return out


def fmt(num, dec):
    return f"{num:,.{dec}f}"


def simple_tokens(text, kinds):
    """한 덩어리짜리 숫자 토큰(「7.6억 달러」「895,292,550kg」「62.4%」「2.3배」)만."""
    res = []
    for x in V.extract(text):
        if x["kind"] not in kinds:
            continue
        m = TOK.match(x["raw"].strip())
        if m:
            res.append((x, m))
    return res


def rerender(x, m, new_val):
    """토큰 x(원문 raw)를 같은 표기 방식으로 new_val 로 다시 쓴다."""
    about, g, sc, unit = m.groups()
    dec = len(g.split(".")[1]) if "." in g else 0
    mul = V.SCALE[sc] if sc else 1.0
    if unit == "톤":
        mul *= 1000
    body = fmt(new_val / mul, dec)
    sep = x["raw"].strip()[len((about or "")) + len(g):]  # 숫자 뒤 원래 꼬리(공백·자릿수말·단위)
    return (about or "") + body + sep


def replace_span(text, x, new_raw):
    s, e = x["start"], x["end"]
    lead = len(x["raw"]) - len(x["raw"].lstrip())
    return text[:s + lead] + new_raw + text[e:]


UPWORDS = [("늘었다", "줄었다"), ("늘었고", "줄었고"), ("늘었지만", "줄었지만"), ("늘어", "줄어"), ("증가했다", "감소했다"), ("증가해", "감소해"),
           ("증가에 그쳤다", "감소에 그쳤다"), ("커졌다", "작아졌다"), ("확대됐다", "축소됐다"), ("급증했다", "급감했다")]


def t_direction(s):
    text = s["text"]
    m = re.search(r"에서.{1,45}?(?:으로|로)(?=\s)", text)
    if not m:
        return None
    tail = text[m.end():]
    for a, b in UPWORDS:
        if a in tail:
            new = text[:m.end()] + tail.replace(a, b, 1)
            return new, s["row_ids"], f"「{a}」→「{b}」"
    return None


def t_x10(s):
    toks = simple_tokens(s["text"], ("usd", "kg"))
    if not toks:
        return None
    x, m = toks[0]
    if m.group(3) == "백만":
        new_raw = x["raw"].strip().replace("백만", "천만", 1)
        how = "백만→천만 표기"
    else:
        new_raw = rerender(x, m, x["val"] * 10); how = "10배"
    return replace_span(s["text"], x, new_raw), s["row_ids"], f"{x['raw'].strip()} → {new_raw}({how})"


def t_year(s):
    text = s["text"]
    ys = [x for x in V.extract(text) if x["kind"] == "year"]
    if len(ys) >= 2 and ys[0]["val"] != ys[1]["val"]:
        a, b = ys[0], ys[1]
        new = text[:a["start"]] + text[b["start"]:b["end"]].replace(str(b["val"]), str(a["val"])) + text[a["end"]:b["start"]] \
            + text[a["start"]:a["end"]].replace(str(a["val"]), str(b["val"])) + text[b["end"]:]
        # 위 줄은 자리 바꿈이 꼬일 수 있어 단순 치환으로 다시
        new = text.replace(str(a["val"]), "@@").replace(str(b["val"]), str(a["val"]), 1).replace("@@", str(b["val"]), 1)
        return new, s["row_ids"], f"{a['val']}↔{b['val']} 자리 맞바꿈"
    if len(ys) == 1:
        others = sorted({int(y) for i in s["row_ids"] for y in ROWS[i]["values"]} - {ys[0]["val"]})
        if others:
            return text.replace(str(ys[0]["val"]), str(others[0]), 1), s["row_ids"], f"{ys[0]['val']}→{others[0]}(인용 행의 다른 연도)"
    return None


def t_ratio(s):
    toks = simple_tokens(s["text"], ("ratio",))
    if not toks:
        return None
    x, m = toks[0]
    d = 0.3 if x["val"] < 5 else -0.3
    new_raw = rerender(x, m, round(x["val"] + d, 1))
    return replace_span(s["text"], x, new_raw), s["row_ids"], f"{x['raw'].strip()} → {new_raw}"


def t_mix(s):
    toks = simple_tokens(s["text"], ("usd", "kg"))
    if not toks:
        return None
    x, m = toks[0]
    y = None
    before = s["text"][max(0, x["start"] - 8):x["start"]]
    my = re.search(r"(20\d\d)", before)
    cited = [ROWS[i] for i in s["row_ids"]]
    unit = "USD" if x["kind"] == "usd" else "kg"
    # 같은 단위·같은 연도 값이 있는 다른 행(인용 안 한 행) 중 값이 같은 자릿수인 것을 고름
    for r in ROWS.values():
        if r["id"] in s["row_ids"] or r["unit"] != unit:
            continue
        yr = my.group(1) if my else (sorted(r["values"])[0] if r["values"] else None)
        if yr not in r["values"]:
            continue
        v = r["values"][yr]
        if 0.2 <= v / x["val"] <= 5 and abs(v - x["val"]) / x["val"] > 0.05:
            new_raw = rerender(x, m, v)
            if new_raw == x["raw"].strip():
                continue
            return replace_span(s["text"], x, new_raw), s["row_ids"] + [r["id"]], f"{x['raw'].strip()} → {new_raw}({r['id']} {yr}년 값, 그 행도 인용)"
    return None


def t_lastdigit(s):
    toks = simple_tokens(s["text"], ("usd", "kg", "pct"))
    if not toks:
        return None
    x, m = toks[-1]
    new_raw = rerender(x, m, x["val"] + x["prec"])
    return replace_span(s["text"], x, new_raw), s["row_ids"], f"{x['raw'].strip()} → {new_raw}(마지막 자릿수 +1)"


TRANSFORMS = [("방향 뒤집기", t_direction), ("단위 10배·천만 표기", t_x10), ("연도 바꾸기", t_year), ("배수 ±0.3", t_ratio),
              ("다른 행 숫자 섞기(그 행도 인용)", t_mix), ("마지막 자릿수 한 칸", t_lastdigit)]

if __name__ == "__main__":
    O = originals()
    pools = {}
    for name, fn in TRANSFORMS:
        pools[name] = []
        for i, s in enumerate(O):
            r = fn(s)
            if r and r[0] != s["text"]:
                pools[name].append((i, r))
        if name.startswith("단위"):  # 백만→천만 표기와 10배를 번갈아
            a = [x for x in pools[name] if "천만" in x[1][2]]; b = [x for x in pools[name] if "천만" not in x[1][2]]
            pools[name] = [x for pair in zip(a, b) for x in pair] + a[len(b):] + b[len(a):]
    items, seen = [], set()
    while len(items) < 50 and any(pools.values()):
        for name, _ in TRANSFORMS:
            if pools[name] and len(items) < 50:
                i, (text, ids, how) = pools[name].pop(0)
                if text in seen:
                    continue
                seen.add(text)
                items.append({"n": len(items) + 1, "유형": name, "text": text, "row_ids": ids, "바뀐것": how,
                              "원문": O[i]["text"], "원문_row_ids": O[i]["row_ids"], "원문_세트": O[i]["세트"]})
    out = {"설명": "맞는 문장 36개(맞음20·화면용)를 규칙으로 바꿔 만든 틀린 문장. 전부 정답은 「숨김」. 생성: make_hard_set.py, 2026-10-31",
           "원문_수": len(O), "틀린문장_수": len(items), "유형별_수": {k: sum(1 for x in items if x["유형"] == k) for k, _ in TRANSFORMS},
           "sentences": items, "originals": O}
    (HERE / "결과" / "검증_어려운세트.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(out["유형별_수"], len(items))
    for x in items:
        print(x["n"], x["유형"], "|", x["바뀐것"], "|", x["text"][:70])
