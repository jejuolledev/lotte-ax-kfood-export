"""예선용 시범 계산 — K-푸드(롯데웰푸드 제품군) 수출 유망국가 점수표.

입력: 데이터/raw/ 의 UN Comtrade 원본(fetch_comtrade.py 로 받음)
출력: 결과/ 의 CSV·JSON·근거문장(문장마다 출처 칸)

규칙(결과를 보기 전에 정함)
- 품목 4개: 1905 비스킷·과자류 / 1806 초콜릿 / 1704 캔디·껌 / 2105 아이스크림
- 나라별 지표 4개(모두 Comtrade)
  size   : 그 나라 수입액(상대국 World, 최근 연도) — 로그
  growth : 그 나라 수입액 연평균 증가율(2021 또는 2022 → 2023~2025 중 가장 최근 연도)
  kgrow  : 한국의 그 나라 수출 연평균 증가율 2022→2025(한국 신고 자료) — K-푸드 수요 흐름의 대리 지표
  room   : 1 - 한국 점유율(한국 수출 ÷ 그 나라 수입, 같은 연도) — 아직 남은 자리
- 대상: 한국 수출 2025년 100만 달러 이상, 그 나라 수입 2,000만 달러 이상(작은 값의 증가율 튐 방지)
- 품목 점수 = 0.25*size + 0.30*growth + 0.30*kgrow + 0.15*room (각 지표는 대상 나라 안 백분위 0~100)
- 종합 점수 = 대상인 품목들의 품목 점수를 한국 2025 품목별 수출액으로 가중 평균(2개 품목 이상 대상인 나라만)
- TOP3: 롯데웰푸드 IR(2025.4Q·2026.2Q)에 현지 공장이 있다고 나온 나라는 빼고(현지 생산으로 공급) 종합 점수 순
- 민감도: 가중치 6세트로 다시 돌려 TOP3에 몇 번 드는지 센다
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


def name(c):
    return KO.get(c) or P.get(c, str(c))


def load(kind, cmd, year):
    f = RAW / f"{kind}_{cmd}_{year}.json"
    d = json.load(open(f))
    key = "partnerCode" if kind == "kor_export" else "reporterCode"
    return {r[key]: r["primaryValue"] for r in d["data"] if r["customsCode"] == "C00" and r["motCode"] == 0 and r["partner2Code"] == 0}


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
    }

def build_rows(bases=(2021, 2022)):
  rows = []
  for c, d in DATA.items():
    for p, kx25 in d["kx"][2025].items():
        if p in (0, 490) or kx25 < 1e6:
            continue
        base = next((y for y in bases if p in d["wm"][y]), None)
        last = next((y for y in (2025, 2024, 2023) if p in d["wm"][y]), None)
        kx22 = d["kx"][2022].get(p)
        if base is None or last is None or not kx22 or last - base < 2:
            continue
        m_last, m_base = d["wm"][last][p], d["wm"][base][p]
        if m_last < 2e7:
            continue
        k_last = d["kx"][last].get(p, 0)
        rows.append({
            "cmd": c, "code": p, "country": name(p),
            "import_base_year": base, "import_last_year": last,
            "import_base_usd": m_base, "import_last_usd": m_last,
            "growth": (m_last / m_base) ** (1 / (last - base)) - 1,
            "kor_2022_usd": kx22, "kor_2025_usd": kx25,
            "kgrow": (kx25 / kx22) ** (1 / 3) - 1,
            "kor_share": k_last / m_last,
        })
  return rows


ROWS = build_rows()

W0 = {"size": .25, "growth": .30, "kgrow": .30, "room": .15}
WSETS = {"기본": W0,
         "같은 비중": {"size": .25, "growth": .25, "kgrow": .25, "room": .25},
         "시장 성장 중시": {"size": .2, "growth": .5, "kgrow": .2, "room": .1},
         "K-수요 중시": {"size": .2, "growth": .2, "kgrow": .5, "room": .1},
         "규모 중시": {"size": .5, "growth": .2, "kgrow": .2, "room": .1},
         "남은 자리 중시": {"size": .2, "growth": .25, "kgrow": .25, "room": .3}}
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
             "kgrow": pct_rank([r["kgrow"] for r in rs]),
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
_, ov22 = score(W0, build_rows(bases=(2022,)))
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
    w.writerow(["품목HS", "품목", "나라", "수입_기준연도", "수입_최근연도", "수입_기준(USD)", "수입_최근(USD)", "수입_연평균증가율",
                "한국수출_2022(USD)", "한국수출_2025(USD)", "한국수출_연평균증가율", "한국점유율", "품목점수", "출처"])
    for r in sorted(ROWS, key=lambda r: (r["cmd"], -by[r["code"]][r["cmd"]][0])):
        w.writerow([r["cmd"], CMDS[r["cmd"]], r["country"], r["import_base_year"], r["import_last_year"],
                    round(r["import_base_usd"]), round(r["import_last_usd"]), f"{r['growth']:.3f}",
                    round(r["kor_2022_usd"]), round(r["kor_2025_usd"]), f"{r['kgrow']:.3f}", f"{r['kor_share']:.4f}",
                    f"{by[r['code']][r['cmd']][0]:.1f}",
                    f"UN Comtrade HS{r['cmd']} 한국 수출(410→{r['code']}) / {r['country']} 수입(←World)"])

with open(OUT / "종합순위.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["순위", "나라", "종합점수", "대상품목수", "롯데웰푸드IR표시"])
    for i, p in enumerate(rank, 1):
        tag = PLANT.get(p) or SALES_SUB.get(p) or ("주요 수출국" if p in KEY_EXPORT else "")
        w.writerow([i, name(p), f"{overall[p]:.1f}", len(by[p]), tag])


def pshare(x):
    return f"{x*100:.2f}" if x < 0.01 else f"{x*100:.1f}"


def fmt_usd(v):
    return f"{v/1e6:,.1f}백만 달러"


# 근거 문장 — 문장마다 숫자와 출처 칸이 붙는다(검증 단계의 입력)
claims = []
for p in top3:
    for c in sorted(by[p], key=lambda c: -by[p][c][0]):
        r = next(r for r in ROWS if r["code"] == p and r["cmd"] == c)
        claims.append({
            "country": name(p), "cmd": c,
            "text": f"{name(p)}의 {CMDS[c].split('(')[0]} 수입은 {r['import_base_year']}년 {fmt_usd(r['import_base_usd'])}에서 "
                    f"{r['import_last_year']}년 {fmt_usd(r['import_last_usd'])}로 연평균 {r['growth']*100:.1f}% 늘었다.",
            "numbers": [r["import_base_usd"], r["import_last_usd"]],
            "source": f"UN Comtrade, 보고국 {name(p)}({p}), HS {c}, 수입, 상대국 World, {r['import_base_year']}·{r['import_last_year']}년",
        })
        claims.append({
            "country": name(p), "cmd": c,
            "text": f"같은 품목 한국의 {name(p)} 수출은 2022년 {fmt_usd(r['kor_2022_usd'])}에서 2025년 {fmt_usd(r['kor_2025_usd'])}로 "
                    f"연평균 {r['kgrow']*100:.1f}% 늘었다(한국 점유율 {pshare(r['kor_share'])}%).",
            "numbers": [r["kor_2022_usd"], r["kor_2025_usd"]],
            "source": f"UN Comtrade, 보고국 한국(410), 상대국 {name(p)}({p}), HS {c}, 수출, 2022·2025년",
        })

result = {
    "기준": "UN Comtrade 공개 API(preview), 내려받은 날 " + json.load(open(RAW / "kor_export_1905_2025.json"))["_fetched"],
    "가중치_기본": W0,
    "대상_나라수": len(overall),
    "종합_상위10": [{"rank": i + 1, "country": name(p), "score": round(overall[p], 1),
                  "tag": PLANT.get(p) or SALES_SUB.get(p) or ("IR 주요 수출국" if p in KEY_EXPORT else "")} for i, p in enumerate(rank[:10])],
    "TOP3_현지공장국가_제외": [{"country": name(p), "score": round(overall[p], 1),
                          "품목점수": {CMDS[c]: round(by[p][c][0], 1) for c in by[p]},
                          "지표백분위": {CMDS[c]: {k: round(v) for k, v in by[p][c][1].items()} for c in by[p]},
                          "tag": SALES_SUB.get(p) or ("IR 주요 수출국" if p in KEY_EXPORT else "IR 표시 없음")} for p in top3],
    "품목별_TOP3_현지공장국가_제외": {CMDS[c]: v for c, v in per_cmd.items()},
    "민감도_7세트_TOP3": sens,
    "민감도_TOP3_등장횟수": dict(sorted(count.items(), key=lambda x: -x[1])),
    "근거문장": claims,
}
(OUT / "시범결과.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
print(json.dumps({k: result[k] for k in result if k != "근거문장"}, ensure_ascii=False, indent=1))
for cl in claims:
    print("-", cl["text"], "|", cl["source"])
