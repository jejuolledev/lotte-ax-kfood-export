"""검증 단계 시험 — 근거 문장의 숫자를 원자료(Comtrade 원본 JSON)에서 다시 꺼내 대조한다.

- 문장에 출처 칸이 없으면 탈락(화면에 안 보임)
- 출처 칸이 가리키는 원자료 행을 직접 읽어, 문장 속 금액(백만 달러)·연도·증가율을 다시 계산해 맞는지 본다
- 일부러 틀리게 만든 문장(금액 바꿈 / 연도 바꿈 / 나라 바꿈 / 증가율 바꿈 / 출처 지움)도 같이 넣어 몇 개를 잡는지 센다
결과: 결과/검증_시험.json
"""
import json, re, pathlib, random

HERE = pathlib.Path(__file__).parent
RAW = HERE / "데이터" / "raw"
res = json.load(open(HERE / "결과" / "시범결과.json"))
claims = res["근거문장"]


def val(kind, cmd, year, reporter, partner):
    d = json.load(open(RAW / f"{kind}_{cmd}_{year}.json"))["data"]
    for r in d:
        if r["reporterCode"] == reporter and r["partnerCode"] == partner and r["customsCode"] == "C00" and r["motCode"] == 0 and r["partner2Code"] == 0:
            return r["primaryValue"]
    return None


def parse_source(src):
    # 예: "UN Comtrade, 보고국 영국(826), HS 1905, 수입, 상대국 World, 2021·2025년"
    m2 = re.search(r"보고국 [^()]+\((\d+)\), 상대국 [^()]+\((\d+)\), HS (\d{4}), (수출), (\d{4})·(\d{4})년", src)
    if m2:
        rep, par, cmd, flow, y1, y2 = m2.groups()
        return dict(kind="kor_export", reporter=int(rep), partner=int(par), cmd=cmd, y1=int(y1), y2=int(y2))
    m3 = re.search(r"보고국 [^()]+\((\d+)\), HS (\d{4}), (수입), 상대국 World, (\d{4})·(\d{4})년", src)
    if m3:
        rep, cmd, flow, y1, y2 = m3.groups()
        return dict(kind="world_import", reporter=int(rep), partner=0, cmd=cmd, y1=int(y1), y2=int(y2))
    return None


def check(cl):
    if not cl.get("source"):
        return False, "출처 없음"
    s = parse_source(cl["source"])
    if not s:
        return False, "출처 형식 해석 불가"
    v1 = val(s["kind"], s["cmd"], s["y1"], s["reporter"], s["partner"])
    v2 = val(s["kind"], s["cmd"], s["y2"], s["reporter"], s["partner"])
    if v1 is None or v2 is None:
        return False, "원자료 행 없음"
    t = cl["text"]
    years = [int(y) for y in re.findall(r"(\d{4})년", t)]
    if years[:2] != [s["y1"], s["y2"]]:
        return False, f"연도 불일치 {years[:2]} vs {[s['y1'], s['y2']]}"
    amts = [float(a.replace(",", "")) for a in re.findall(r"([\d,]+\.\d)백만 달러", t)]
    if len(amts) < 2 or abs(amts[0] - round(v1 / 1e6, 1)) > 0.05 or abs(amts[1] - round(v2 / 1e6, 1)) > 0.05:
        return False, f"금액 불일치 {amts} vs {[round(v1/1e6,1), round(v2/1e6,1)]}"
    g = re.search(r"연평균 (-?[\d.]+)%", t)
    cagr = ((v2 / v1) ** (1 / (s["y2"] - s["y1"])) - 1) * 100
    if not g or abs(float(g.group(1)) - round(cagr, 1)) > 0.05:
        return False, f"증가율 불일치 {g.group(1) if g else None} vs {cagr:.1f}"
    name = cl["country"]
    if name not in t:
        return False, "나라 이름 불일치"
    return True, "통과"


random.seed(7)
bad = []
for cl in claims:
    t = cl["text"]
    # 금액 바꿈
    m = re.search(r"([\d,]+\.\d)백만 달러", t)
    if m:
        x = float(m.group(1).replace(",", ""))
        nt = t.replace(m.group(1), f"{x*1.12:,.1f}", 1)
        if nt != t:
            bad.append(dict(cl, text=nt, _mut="금액 12% 부풀림"))
    # 연도 바꿈
    y = re.search(r"(\d{4})년", t).group(1)
    bad.append(dict(cl, text=t.replace(y + "년", str(int(y) - 1) + "년", 1), _mut="시작 연도 한 해 당김"))
    # 증가율 바꿈
    g = re.search(r"연평균 ([\d.]+)%", t)
    if g:
        bad.append(dict(cl, text=t.replace(g.group(0), f"연평균 {float(g.group(1))+5:.1f}%"), _mut="증가율 +5%p"))
    # 출처 지움
    bad.append(dict(cl, source="", _mut="출처 지움"))
# 나라 바꿈: 문장은 그대로 두고 출처를 다른 나라 행으로
for i, cl in enumerate(claims):
    other = claims[(i + 4) % len(claims)]
    if other["country"] != cl["country"]:
        bad.append(dict(cl, source=other["source"], _mut="다른 나라·품목 출처를 붙임"))

# (금액을 바꿨는데 반올림 때문에 글자가 그대로인 문장은 틀린 문장이 아니므로 만들지 않는다)
ok_true = [check(c) for c in claims]
caught = [not check(c)[0] for c in bad]
by_mut = {}
for c, k in zip(bad, caught):
    a = by_mut.setdefault(c["_mut"], [0, 0])
    a[0] += k
    a[1] += 1
out = {
    "맞는_문장_통과": f"{sum(o for o, _ in ok_true)}/{len(claims)}",
    "틀린_문장_걸러짐": f"{sum(caught)}/{len(bad)}",
    "유형별": {k: f"{v[0]}/{v[1]}" for k, v in by_mut.items()},
    "통과못한_맞는문장": [c["text"] for c, (o, _) in zip(claims, ok_true) if not o],
    "놓친_틀린문장": [(c["_mut"], c["text"]) for c, k in zip(bad, caught) if not k],
}
(HERE / "결과" / "검증_시험.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1))
