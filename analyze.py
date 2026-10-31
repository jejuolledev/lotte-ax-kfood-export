"""예선용 시범 계산 v2 — K-푸드(롯데웰푸드 제품군) 수출 유망국가 점수표.

입력: 데이터/raw/ 의 UN Comtrade 원본(fetch_comtrade.py 로 받음)
출력: 결과/ 의 CSV·JSON·근거 행(행마다 출처 칸)

v1(결과/v1_1차심사전/)에서 1차 독립 심사 지적으로 바꾼 것(2026-10-30 밤)
- 한국 수출 기준연도를 수입과 같은 2021로 맞춤(v1은 2022)
- 「남은 점유율」 지표를 기본 점수에서 뺌(나라들 점유율이 0~1%대에 몰려 변별력이 거의 없음, 민감도 세트에는 남김)
- 「K-가공식품 수요」 지표 추가: 한국의 HS 16~21류(가공식품) 그 나라 수출 연평균 증가율 2021→2025 — 과자 밖의 K-푸드가 그 나라에서 얼마나 늘고 있나(소비 트렌드의 대리 지표)
- 민감도에 「무게 기준 성장」 추가(가격 효과 제거), 재수출 확인(그 나라 같은 품목 수출) 추가

지표(모두 Comtrade, 비교 나라 안 백분위 0~100)
  size   : 그 나라 수입액(상대국 World, 최근 연도) — 로그
  growth : 그 나라 수입액 연평균 증가율(2021 또는 2022 → 2023~2025 중 최근)
  kgrow  : 한국의 그 나라 같은 품목 수출 연평균 증가율 2021→2025
  kfood  : 한국의 그 나라 가공식품(HS 16~21) 수출 연평균 증가율 2021→2025
기본 가중치 각 25%. 대상: 한국 수출 2025년 100만 달러 이상, 그 나라 수입 2,000만 달러 이상, 품목 2개 이상.
TOP3: 롯데웰푸드 IR에 현지 공장이 있는 6개국 제외.
"""
import json, math, csv, pathlib, statistics

HERE = pathlib.Path(__file__).parent
RAW = HERE / "데이터" / "raw"
OUT = HERE / "결과"
OUT.mkdir(exist_ok=True)

CMDS = {"1905": "비스킷·과자류(빼빼로·칸쵸 등)", "1806": "초콜릿(가나 등)", "1704": "캔디·껌(설탕 과자)", "2105": "아이스크림(빙과)"}
P = {p["PartnerCode"]: p["PartnerDesc"] for p in json.load(open(RAW / "partners.json"))["results"]}
KO = {842: "미국", 156: "중국", 124: "캐나다", 392: "일본", 36: "호주", 608: "필리핀", 344: "홍콩", 704: "베트남", 496: "몽골",
      643: "러시아", 458: "말레이시아", 826: "영국", 528: "네덜란드", 702: "싱가포르", 764: "태국", 276: "독일", 360: "인도네시아",
      682: "사우디아라비아", 784: "아랍에미리트", 554: "뉴질랜드", 250: "프랑스", 410: "한국", 398: "카자흐스탄", 699: "인도",
      586: "파키스탄", 56: "벨기에", 104: "미얀마", 116: "캄보디아", 418: "라오스", 860: "우즈베키스탄", 417: "키르기스스탄",
      376: "이스라엘", 414: "쿠웨이트", 634: "카타르", 512: "오만", 48: "바레인", 400: "요르단", 818: "이집트", 484: "멕시코",
      76: "브라질", 152: "칠레", 604: "페루", 170: "콜롬비아", 724: "스페인", 380: "이탈리아", 616: "폴란드", 752: "스웨덴",
      208: "덴마크", 246: "핀란드", 578: "노르웨이", 40: "오스트리아", 757: "스위스", 372: "아일랜드", 203: "체코", 348: "헝가리",
      642: "루마니아", 300: "그리스", 620: "포르투갈", 792: "튀르키예", 804: "우크라이나", 112: "벨라루스", 268: "조지아",
      51: "아르메니아", 31: "아제르바이잔", 496.0: "몽골", 50: "방글라데시", 144: "스리랑카", 524: "네팔", 710: "남아프리카공화국",
      566: "나이지리아", 404: "케냐", 458.0: "말레이시아", 96: "브루나이", 446: "마카오", 90: "솔로몬제도", 242: "피지",
      316: "괌", 840: "미국령", 591: "파나마", 188: "코스타리카", 320: "과테말라", 214: "도미니카공화국", 32: "아르헨티나",
      218: "에콰도르", 858: "우루과이", 600: "파라과이", 68: "볼리비아", 862: "베네수엘라", 470: "몰타", 196: "키프로스",
      440: "리투아니아", 428: "라트비아", 233: "에스토니아", 705: "슬로베니아", 191: "크로아티아", 703: "슬로바키아",
      100: "불가리아", 688: "세르비아", 498: "몰도바", 762: "타지키스탄", 795: "투르크메니스탄", 364: "이란", 368: "이라크",
      422: "레바논", 788: "튀니지", 504: "모로코", 12: "알제리", 434: "리비아", 729: "수단", 231: "에티오피아", 288: "가나",
      384: "코트디부아르", 686: "세네갈", 834: "탄자니아", 800: "우간다", 894: "잠비아", 716: "짐바브웨", 508: "모잠비크",
      480: "모리셔스", 690: "세이셸", 462: "몰디브", 4: "아프가니스탄", 132: "카보베르데", 251: "프랑스", 579: "노르웨이",
      699.0: "인도", 490: "기타 아시아(대만 포함)"}
# 롯데웰푸드 IR 2025년 4분기(2026-02-06) 10·29쪽, 2026년 2분기(2026-08-07) 10쪽
PLANT = {398: "카자흐스탄 공장 3", 586: "파키스탄 공장 7", 56: "벨기에 공장 1", 699: "인도 공장 6(건과3·빙과3)",
         643: "러시아 공장 1", 104: "미얀마 공장 3"}
SALES_SUB = {702: "싱가포르 판매법인"}
KEY_EXPORT = {842: "미국", 764: "태국", 704: "베트남", 608: "필리핀", 36: "호주", 124: "캐나다"}
# IR 2026년 2분기 10쪽 「유럽 주요 체인 빼빼로 입점 → 독일 REWE, 네덜란드 Albert Heijn」
IR_ENTRY = {276: "IR 입점 나라(독일 REWE)", 528: "IR 입점 나라(네덜란드 Albert Heijn)"}


def tag_of(p):
    return PLANT.get(p) or IR_ENTRY.get(p) or SALES_SUB.get(p) or ("IR 주요 수출국" if p in KEY_EXPORT else "IR에 나라 이름 없음")


def name(c):
    return KO.get(c) or P.get(c, str(c))


def load(kind, cmd, year, field="primaryValue"):
    f = RAW / f"{kind}_{cmd}_{year}.json"
    d = json.load(open(f))
    key = "partnerCode" if kind == "kor_export" else "reporterCode"
    return {r[key]: r[field] for r in d["data"] if r["customsCode"] == "C00" and r["motCode"] == 0 and r["partner2Code"] == 0}


def pct_rank(vals):
    """값 목록 → 백분위(0~100). 같은 값은 평균 순위."""
    s = sorted(vals)
    n = len(s)
    out = []
    for v in vals:
        lo = sum(1 for x in s if x < v)
        eq = sum(1 for x in s if x == v)
        out.append(100.0 * (lo + (eq - 1) / 2) / (n - 1) if n > 1 else 50.0)
    return out


DATA = {}
for c in CMDS:
    DATA[c] = {
        "kx": {y: load("kor_export", c, y) for y in range(2021, 2026)},
        "wm": {y: load("world_import", c, y) for y in range(2021, 2026)},
        "ww": {y: load("world_import", c, y, "netWgt") for y in range(2021, 2026)},
    }

# 한국 가공식품(HS 16~21류) 나라별 수출 합계 2021·2025
KFOOD = {}
_kf = {y: {} for y in (2021, 2025)}
for y in (2021, 2025):
    for ch in ("16", "17", "18", "19", "20", "21"):
        for p, v in load("kor_export", "ch" + ch, y).items():
            _kf[y][p] = _kf[y].get(p, 0) + v
for p in _kf[2025]:
    if _kf[2021].get(p, 0) > 0 and p not in (0, 490):
        KFOOD[p] = (_kf[2021][p], _kf[2025][p])

# 재수출 확인용: 그 나라의 같은 품목 수출(상대국 World) 2025
HUB = {}
for c in ("1905", "2105"):
    for r in json.load(open(RAW / f"hub_export_{c}_2025.json"))["data"]:
        HUB[(r["reporterCode"], c)] = r["primaryValue"]

def build_rows(bases=(2021, 2022), kbase=2021):
  rows = []
  for c, d in DATA.items():
    for p, kx25 in d["kx"][2025].items():
        if p in (0, 490) or kx25 < 1e6:
            continue
        base = next((y for y in bases if p in d["wm"][y]), None)
        last = next((y for y in (2025, 2024, 2023) if p in d["wm"][y]), None)
        kxb = d["kx"][kbase].get(p)
        if base is None or last is None or not kxb or last - base < 2 or p not in KFOOD:
            continue
        m_last, m_base = d["wm"][last][p], d["wm"][base][p]
        if m_last < 2e7:
            continue
        # 무게는 칸이 빈 해가 있어, 무게가 있는 해끼리(2021~2023 중 가장 이른 해 → 2025~2023 중 가장 늦은 해, 2년 이상) 계산
        wb = next((y for y in (2021, 2022, 2023) if (d["ww"][y].get(p) or 0) > 0), None)
        wl = next((y for y in (2025, 2024, 2023) if (d["ww"][y].get(p) or 0) > 0), None)
        if wb and wl and wl - wb >= 2:
            w_base, w_last = d["ww"][wb][p], d["ww"][wl][p]
        else:
            wb = wl = w_base = w_last = None
        k_last = d["kx"][last].get(p, 0)
        rows.append({
            "cmd": c, "code": p, "country": name(p),
            "import_base_year": base, "import_last_year": last,
            "import_base_usd": m_base, "import_last_usd": m_last,
            "growth": (m_last / m_base) ** (1 / (last - base)) - 1,
            "import_base_kg": w_base, "import_last_kg": w_last,
            "w_base_year": wb, "w_last_year": wl,
            "wgrowth": ((w_last / w_base) ** (1 / (wl - wb)) - 1) if w_base and w_last else None,
            "kor_base_year": kbase, "kor_base_usd": kxb, "kor_2025_usd": kx25,
            "kgrow": (kx25 / kxb) ** (1 / (2025 - kbase)) - 1,
            "kor_share": k_last / m_last,
            "kfood_2021_usd": KFOOD[p][0], "kfood_2025_usd": KFOOD[p][1],
            "kfood": (KFOOD[p][1] / KFOOD[p][0]) ** (1 / 4) - 1,
        })
  return rows


ROWS = build_rows()

W0 = {"size": .25, "growth": .25, "kgrow": .25, "kfood": .25}
WSETS = {"기본(각 25%)": W0,
         "시장 성장 중시": {"size": .2, "growth": .4, "kgrow": .2, "kfood": .2},
         "K-수요 중시": {"size": .2, "growth": .2, "kgrow": .3, "kfood": .3},
         "규모 중시": {"size": .4, "growth": .2, "kgrow": .2, "kfood": .2},
         "남은 점유율 넣기(v1 지표)": {"size": .2, "growth": .2, "kgrow": .2, "kfood": .2, "room": .2},
         "무게 기준 성장(가격 효과 뺌)": {"size": .25, "wgrowth": .25, "kgrow": .25, "kfood": .25},
         "작은 시작값 상한(2021년 한국 수출 100만 달러 미만은 증가율 백분위 50까지)": {"size": .25, "growth": .25, "kgrow_cap": .25, "kfood": .25}}
KOR_TOTAL = {c: sum(v for k, v in DATA[c]["kx"][2025].items() if k != 0) for c in CMDS}


def score(W, ROWS=None):
    ROWS = ROWS if ROWS is not None else globals()["ROWS"]
    by = {}
    for c in CMDS:
        rs = [r for r in ROWS if r["cmd"] == c]
        if not rs:
            continue
        f = {"size": pct_rank([math.log(r["import_last_usd"]) for r in rs]),
             "growth": pct_rank([r["growth"] for r in rs]),
             "wgrowth": pct_rank([r["wgrowth"] if r["wgrowth"] is not None else r["growth"] for r in rs]),
             "kgrow": pct_rank([r["kgrow"] for r in rs]),
             "kgrow_cap": [min(v, 50.0) if r["kor_base_usd"] < 1e6 else v for v, r in zip(pct_rank([r["kgrow"] for r in rs]), rs)],
             "kfood": pct_rank([r["kfood"] for r in rs]),
             "room": pct_rank([1 - r["kor_share"] for r in rs])}
        for i, r in enumerate(rs):
            s = sum(W[k] * f[k][i] for k in W)
            by.setdefault(r["code"], {})[c] = (s, {k: f[k][i] for k in W})
    overall = {}
    for p, g in by.items():
        if len(g) < 2:
            continue
        wsum = sum(KOR_TOTAL[c] for c in g)
        overall[p] = sum(g[c][0] * KOR_TOTAL[c] for c in g) / wsum
    return by, overall


by, overall = score(W0)
rank = sorted(overall, key=lambda p: -overall[p])
cand = [p for p in rank if p not in PLANT]
top3 = cand[:3]

sens = {}
for wn, W in WSETS.items():
    _, ov = score(W)
    r = [p for p in sorted(ov, key=lambda p: -ov[p]) if p not in PLANT][:3]
    sens[wn] = [name(p) for p in r]
_, ov22 = score(W0, build_rows(bases=(2022,), kbase=2022))
sens["기준연도 2022(브렉시트 직후 2021 제외)"] = [name(p) for p in [p for p in sorted(ov22, key=lambda p: -ov22[p]) if p not in PLANT][:3]]
count = {}
for v in sens.values():
    for n in v:
        count[n] = count.get(n, 0) + 1

# 품목별 TOP3(현지 공장 국가 제외)
per_cmd = {}
for c in CMDS:
    items = sorted([(by[p][c][0], p) for p in by if c in by[p] and p not in PLANT], reverse=True)[:3]
    per_cmd[c] = [{"country": name(p), "score": round(s, 1)} for s, p in items]

# CSV
with open(OUT / "지표_품목x나라.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["행ID", "품목HS", "품목", "나라", "수입_기준연도", "수입_최근연도", "수입_기준(USD)", "수입_최근(USD)", "수입_연평균증가율",
                "수입무게_기준(kg)", "수입무게_최근(kg)", "수입무게_연평균증가율", "한국수출_2021(USD)", "한국수출_2025(USD)", "한국수출_연평균증가율",
                "한국점유율", "한국가공식품수출_2021(USD)", "한국가공식품수출_2025(USD)", "한국가공식품_연평균증가율", "품목점수", "출처"])
    for r in sorted(ROWS, key=lambda r: (r["cmd"], -by[r["code"]][r["cmd"]][0])):
        w.writerow([f"{r['code']}-{r['cmd']}", r["cmd"], CMDS[r["cmd"]], r["country"], r["import_base_year"], r["import_last_year"],
                    round(r["import_base_usd"]), round(r["import_last_usd"]), f"{r['growth']:.4f}",
                    r["import_base_kg"] or "", r["import_last_kg"] or "", f"{r['wgrowth']:.4f}" if r["wgrowth"] is not None else "",
                    round(r["kor_base_usd"]), round(r["kor_2025_usd"]), f"{r['kgrow']:.4f}", f"{r['kor_share']:.5f}",
                    round(r["kfood_2021_usd"]), round(r["kfood_2025_usd"]), f"{r['kfood']:.4f}",
                    f"{by[r['code']][r['cmd']][0]:.1f}",
                    f"UN Comtrade HS{r['cmd']} {r['country']} 수입(←World) / 한국 수출(410→{r['code']}) / 한국 HS16~21 수출"])

with open(OUT / "종합순위.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["순위", "나라", "종합점수", "대상품목수", "롯데웰푸드IR표시"])
    for i, p in enumerate(rank, 1):
        w.writerow([i, name(p), f"{overall[p]:.1f}", len(by[p]), tag_of(p)])


def pshare(x):
    return f"{x*100:.2f}" if x < 0.01 else f"{x*100:.1f}"


def fmt_usd(v):
    return f"{v/1e6:,.1f}백만 달러"


# 근거 행 — 에이전트(모델)가 문장을 쓸 때 인용하는 단위. 행마다 출처 칸이 붙는다.
evidence = []
for p in top3 + [276]:
    for c in sorted(by.get(p, {}), key=lambda c: -by[p][c][0]):
        r = next(r for r in ROWS if r["code"] == p and r["cmd"] == c)
        rid = f"{p}-{c}"
        evidence.append({"id": rid + "-M", "country": name(p), "cmd": c, "what": f"{name(p)}의 {CMDS[c].split('(')[0]} 수입액(상대국 World)",
                         "values": {str(r["import_base_year"]): r["import_base_usd"], str(r["import_last_year"]): r["import_last_usd"]}, "unit": "USD",
                         "cagr": r["growth"], "source": f"UN Comtrade, 보고국 {name(p)}({p}), HS {c}, 수입, 상대국 World, {r['import_base_year']}·{r['import_last_year']}년"})
        if r["wgrowth"] is not None:
            evidence.append({"id": rid + "-W", "country": name(p), "cmd": c, "what": f"{name(p)}의 {CMDS[c].split('(')[0]} 수입 무게",
                             "values": {str(r["w_base_year"]): r["import_base_kg"], str(r["w_last_year"]): r["import_last_kg"]}, "unit": "kg",
                             "cagr": r["wgrowth"], "source": f"UN Comtrade, 보고국 {name(p)}({p}), HS {c}, 수입 무게(netWgt), 상대국 World, {r['w_base_year']}·{r['w_last_year']}년"})
        evidence.append({"id": rid + "-K", "country": name(p), "cmd": c, "what": f"한국의 {name(p)} {CMDS[c].split('(')[0]} 수출액",
                         "values": {"2021": r["kor_base_usd"], "2025": r["kor_2025_usd"]}, "unit": "USD", "cagr": r["kgrow"],
                         "share_2025": r["kor_share"],
                         "source": f"UN Comtrade, 보고국 한국(410), 상대국 {name(p)}({p}), HS {c}, 수출, 2021·2025년"})
        if (p, c) in HUB:
            evidence.append({"id": rid + "-X", "country": name(p), "cmd": c, "what": f"{name(p)}의 {CMDS[c].split('(')[0]} 수출액(상대국 World, 재수출 포함)",
                             "values": {"2025": HUB[(p, c)]}, "unit": "USD",
                             "source": f"UN Comtrade, 보고국 {name(p)}({p}), HS {c}, 수출, 상대국 World, 2025년"})
    if p in KFOOD:
        evidence.append({"id": f"{p}-KF", "country": name(p), "cmd": "16-21", "what": f"한국의 {name(p)} 가공식품(HS 16~21류) 수출액",
                         "values": {"2021": KFOOD[p][0], "2025": KFOOD[p][1]}, "unit": "USD", "cagr": (KFOOD[p][1] / KFOOD[p][0]) ** .25 - 1,
                         "source": f"UN Comtrade, 보고국 한국(410), 상대국 {name(p)}({p}), HS 16·17·18·19·20·21류 합계, 수출, 2021·2025년"})

# 재수출 확인 표(비스킷·아이스크림): 수입 - 수출
hub = []
for (p, c), x in sorted(HUB.items()):
    r = next((r for r in ROWS if r["code"] == p and r["cmd"] == c), None)
    m = r["import_last_usd"] if r and r["import_last_year"] == 2025 else DATA[c]["wm"][2025].get(p)
    hub.append({"country": name(p), "cmd": c, "import_2025": m, "export_2025": x, "net_import_2025": (m - x) if m else None})

result = {
    "기준": "UN Comtrade 공개 API(preview), 내려받은 날 " + json.load(open(RAW / "kor_export_1905_2025.json"))["_fetched"],
    "가중치_기본": W0,
    "대상_나라수": len(overall),
    "종합_상위10": [{"rank": i + 1, "country": name(p), "score": round(overall[p], 1), "tag": tag_of(p)} for i, p in enumerate(rank[:10])],
    "TOP3_현지공장국가_제외": [{"country": name(p), "code": p, "score": round(overall[p], 1),
                          "품목점수": {CMDS[c]: round(by[p][c][0], 1) for c in by[p]},
                          "지표백분위": {CMDS[c]: {k: round(v) for k, v in by[p][c][1].items()} for c in by[p]},
                          "tag": tag_of(p)} for p in top3],
    "품목별_TOP3_현지공장국가_제외": {CMDS[c]: v for c, v in per_cmd.items()},
    "민감도_TOP3": sens,
    "민감도_TOP3_등장횟수": dict(sorted(count.items(), key=lambda x: -x[1])),
    "민감도_세트수": len(sens),
    "재수출_확인": hub,
    "무게_자료_없는_행": [f"{r['country']} HS{r['cmd']}" for r in ROWS if r["wgrowth"] is None],
    "무게_기준_TOP3후보": {f"{r['country']} HS{r['cmd']}": {"금액_연": round(r["growth"] * 100, 1), "무게_연": round(r["wgrowth"] * 100, 1) if r["wgrowth"] is not None else None, "무게_연도": f"{r['w_base_year']}→{r['w_last_year']}"} for r in ROWS if r["code"] in top3},
    "근거행": evidence,
}
(OUT / "시범결과.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
print(json.dumps({k: result[k] for k in result if k not in ("근거행",)}, ensure_ascii=False, indent=1))
