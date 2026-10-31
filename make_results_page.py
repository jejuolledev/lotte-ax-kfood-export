"""결과 페이지(정적 HTML) 생성 — 설치 없이 브라우저로 결과를 볼 수 있게.
입력: 결과/시범결과.json, 결과/모델문장_화면용.json(있으면), 결과/계획실행_*.json(있으면)
출력: docs/index.html  (GitHub Pages 용)
모델 호출 없음, 키 없음.
"""
import json, glob, html, pathlib, datetime

HERE = pathlib.Path(__file__).parent
OUT = HERE / "결과"
DOCS = HERE / "docs"
DOCS.mkdir(exist_ok=True)
E = html.escape
R = json.load(open(OUT / "시범결과.json", encoding="utf-8"))
sent_path = OUT / "모델문장_화면용.json"
SENT = json.load(open(sent_path, encoding="utf-8")) if sent_path.exists() else []
PLANS = [json.load(open(f, encoding="utf-8")) for f in sorted(glob.glob(str(OUT / "계획실행_*.json"))) if "_dry" not in f]


def usd(v):
    return "-" if v is None else f"{v/1e6:,.1f}백만$"


def pct(x):
    return "-" if x is None else f"{x*100:.0f}%"


css = """
body{font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#1b2a22;line-height:1.5}
h1{font-size:24px}h2{font-size:18px;margin-top:36px;border-left:4px solid #1f6f4a;padding-left:10px}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:8px 0}th,td{border-bottom:1px solid #e3e8e5;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f3f7f5;font-weight:600}
.chip{display:inline-block;background:#e8f3ec;color:#1f6f4a;border-radius:999px;padding:2px 10px;font-size:12px;margin-right:6px}.chip.red{background:#fdecec;color:#b42318}.chip.gold{background:#fff4d6;color:#8a5a00}
.card{border:1px solid #e3e8e5;border-radius:10px;padding:12px 14px;margin:8px 0;background:#fff}.muted{color:#6b7a72;font-size:12.5px}.top{display:flex;gap:12px;flex-wrap:wrap}.top .card{flex:1;min-width:220px}
.ok{color:#1f6f4a}.hide{color:#b42318}code{background:#f3f7f5;padding:1px 5px;border-radius:4px}
"""

top3 = R["TOP3_현지공장국가_제외"]
parts = [f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>K-푸드 수출 유망국가 — 결과 페이지</title><style>{css}</style></head><body>
<h1>K-푸드 수출 유망국가 에이전트 — 결과 페이지</h1>
<p class="muted">LOTTE AX CHALLENGE 2026 예선 · 배정길(모아허브) · 이 페이지는 저장소의 결과 파일로 만든 정적 화면입니다(모델 호출 없음). 기준: {E(R["기준"])} · 만든 날 {datetime.date.today()}</p>
<p><b>직접 질문해 보기:</b> <a href="https://kfood-agent-598315031037.asia-northeast3.run.app/">kfood-agent-598315031037.asia-northeast3.run.app</a> (비밀번호 lotte-kfood-2026 · 질문 1건 = 모델 호출 1번 · 하루 50번) · 코드·원자료: <a href="https://github.com/jejuolledev/lotte-ax-kfood-export">github.com/jejuolledev/lotte-ax-kfood-export</a> — <code>python3 analyze.py &amp;&amp; python3 verify_llm.py</code> 로 키 없이 같은 결과를 다시 얻을 수 있습니다.</p>

<h2>1. 지금 보낼 곳 — TOP3 (현지 공장 나라 제외, {R["대상_나라수"]}개국 비교)</h2>
<div class="top">"""]
for t in top3:
    items = " · ".join(f"{k.split('(')[0]} {v:.0f}" for k, v in t["품목점수"].items())
    parts.append(f'<div class="card"><div style="font-size:26px;font-weight:700">{E(t["country"])}</div><div class="muted">종합 {t["score"]} · {E(t["tag"])}</div><div class="muted">품목 점수: {E(items)}</div></div>')
parts.append("</div>")

parts.append("<h3>종합 상위 10</h3><table><tr><th>순위</th><th>나라</th><th>점수</th><th>IR 기준 표시</th></tr>")
for x in R["종합_상위10"]:
    parts.append(f'<tr><td>{x["rank"]}</td><td>{E(x["country"])}</td><td>{x["score"]}</td><td class="muted">{E(x["tag"])}</td></tr>')
parts.append("</table>")

parts.append("<h3>품목별 TOP3</h3><table><tr><th>품목</th><th>1</th><th>2</th><th>3</th></tr>")
for k, v in R["품목별_TOP3_현지공장국가_제외"].items():
    parts.append(f'<tr><td>{E(k)}</td>' + "".join(f'<td>{E(c["country"])} <span class="muted">{c["score"]}</span></td>' for c in v) + "</tr>")
parts.append("</table>")

parts.append(f'<h2>2. 기준을 바꿔도 남는가 — 검산 {R["민감도_세트수"]}번</h2><table><tr><th>기준</th><th>TOP3</th></tr>')
for k, v in R["민감도_TOP3"].items():
    parts.append(f'<tr><td>{E(k)}</td><td>{E(" · ".join(v))}</td></tr>')
parts.append(f'</table><p>등장 횟수: {E(", ".join(f"{k} {v}" for k, v in R["민감도_TOP3_등장횟수"].items()))}</p>')
if R.get("범위_넓힘_상위10"):
    parts.append(f'<p class="muted">범위를 {R["범위_넓힘_나라수"]}개국으로 넓힌 상위 10: {E(", ".join(f"{c} {s}" for c, s in R["범위_넓힘_상위10"]))}</p>')

parts.append("<h2>3. 올라오는 곳 — 작지만 빠른 나라(테스트 물량을 넣어 볼 곳)</h2>")
rule = R.get("올라오는_나라_규칙", {})
parts.append(f'<p class="muted">규칙(코드 고정): 한국 수출 2025년 {rule.get("한국수출_2025_최소USD",1e6)/1e6:.0f}백만$ 이상 · 2021→2025 연 {pct(rule.get("한국수출_연증가율_최소"))} 이상 · 그 나라 수입 연 {pct(rule.get("그나라수입_연증가율_최소"))} 이상 · 한국 점유율 {pct(rule.get("한국점유율_최대"))} 미만 · {E(rule.get("제외",""))}</p>')
parts.append("<table><tr><th>나라 · 품목</th><th>한국 수출 2021→2025</th><th>연증가</th><th>2022 기준</th><th>24→25</th><th>그 나라 수입 돈/양</th><th>시장</th><th>K-푸드 전반</th><th>점유율</th><th>표시</th></tr>")
for x in R.get("올라오는_나라", []):
    parts.append(f'<tr><td><b>{E(x["country"])}</b> {E(x["cmd"].split("(")[0])}</td><td>{usd(x["kor_2021_usd"])} → {usd(x["kor_2025_usd"])}</td><td><b>{pct(x["kgrow_2021base"])}</b></td><td>{pct(x["kgrow_2022base"])}</td><td>{pct(x["kor_2024to2025"])}</td><td>{pct(x["import_growth"])}{"" if x["import_wgrowth"] is None else " / "+pct(x["import_wgrowth"])}</td><td>{usd(x["그나라_수입시장_USD"])}</td><td>{pct(x["한국가공식품_연증가율"])}</td><td>{x["kor_share_2025"]*100:.1f}%</td><td class="muted">{E(x["주의"] or x["tag"])}</td></tr>')
parts.append("</table>")

parts.append("<h2>4. 모르는 것 — 자료 빈 곳과 다음 출처(코드가 자동으로 찾음)</h2><table><tr><th>어디</th><th>빈 곳</th><th>다음 출처</th></tr>")
for g in R.get("자료_빈_곳", []):
    parts.append(f'<tr><td>{E(g["country"])} <span class="muted">{E(g["cmd"].split("(")[0])}</span></td><td>{E(g["빈 곳"])}</td><td class="muted">{E(g["다음 출처"])}</td></tr>')
parts.append("</table>")

if SENT:
    VER = json.load(open(OUT / "검증_모델문장.json", encoding="utf-8")).get("모델문장_화면용", [])
    verdict = {v["text"]: v for v in VER}
    EV = {r["id"]: r for r in R["근거행"]}
    parts.append("<h2>5. 모델이 쓴 설명 문장 — 검증을 거친 것만 화면에</h2><p class='muted'>문장은 gpt-5.4-mini가 근거 행만 보고 썼고, 검증기가 숫자·연도·방향을 원자료와 대조했습니다. 「표시」만 보이고, 「숨김」은 이유와 함께 접어 둡니다.</p>")
    for c in SENT.get("countries", []):
        for s_ in c.get("sentences", []):
            v = verdict.get(s_["text"], {})
            srcs = " / ".join(EV[i]["source"] for i in s_.get("row_ids", []) if i in EV)
            if v.get("판정") == "표시":
                parts.append(f'<div class="card"><span class="chip">{E(c["country"])}</span> {E(s_["text"])}<div class="muted">↳ {E(srcs)}</div></div>')
            else:
                parts.append(f'<details class="card"><summary class="hide">숨김 · {E(c["country"])} · {E(v.get("이유", "검증 기록 없음"))}</summary><div class="muted">{E(s_["text"])}<br>↳ {E(srcs)}</div></details>')

if PLANS:
    parts.append("<h2>6. 계획 단계 — 질문을 받아 모델이 도구 순서를 정하고, 코드가 검사·실행</h2><p class='muted'>gpt-5.4-mini, Structured Outputs. 계획은 코드가 검사합니다(score 없음·explain 뒤 verify 없음·모르는 품목코드면 거부). 아래는 실제 호출 기록입니다.</p><table><tr><th>질문</th><th>모델이 정한 순서</th><th>검사</th><th>초</th><th>토큰(입력/출력)</th></tr>")
    for p_ in PLANS:
        u = p_.get("토큰") or {}
        extra = " <span class='chip red'>JSON 뒤 덧붙임 → 첫 JSON만 사용</span>" if p_["계획"].get("_모델_JSON_뒤_덧붙임") else ""
        parts.append(f'<tr><td>{E(p_["질문"])}</td><td>{E(" → ".join(s["tool"] for s in p_["계획"]["steps"]))}{extra}</td><td>{E(str(p_["검사"]))}</td><td>{p_["계획_초"]}</td><td>{u.get("input","-")}/{u.get("output","-")}</td></tr>')
    parts.append("</table>")

parts.append(f"""<h2>한계</h2><ul>
<li>검증기는 숫자 베껴 쓰기 오류를 거를 뿐, 추천이 옳은지는 보장하지 않습니다. 추천은 담당자가 확인하기 전까지 「초안」입니다.</li>
<li>소비 트렌드 문장은 영국·네덜란드·미국 3개국만 직접 뽑았고, 자동 추출은 아직 없습니다.</li>
<li>올라오는 곳은 시작값이 작아 증가율이 크게 보입니다. 바로 보낼 곳이 아니라 테스트 물량을 넣어 볼 곳입니다.</li>
<li>빼빼로의 실제 신고 품목코드는 HS 1905로 가정했습니다. 롯데 자료를 받으면 바꿉니다.</li>
</ul>
<p class="muted">출처: UN Comtrade 공개 API(2026-10-30 내려받음) · 롯데웰푸드 IR 2025년 4분기·2026년 2분기 · aT KATI 보고서 · 농림축산식품부 보도자료(2026-01-12)</p>
</body></html>""")
(DOCS / "index.html").write_text("".join(parts), encoding="utf-8")
print("wrote", DOCS / "index.html", len("".join(parts)), "bytes")
