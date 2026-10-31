# K-푸드 수출 유망국가 시범 계산 · 검증 (LOTTE AX CHALLENGE 2026 예선 제출용)

LOTTE AX CHALLENGE 2026 예선 제출용 시범 코드입니다. 배정길(모아허브).

**English (3 lines)**
- Picks promising export countries for Korean snacks (biscuits, chocolate, candy, ice cream) from UN Comtrade public data, with every number traceable to a source row.
- An LLM writes the explanation sentences; a rule-based verifier recomputes every number in each sentence from the cited rows and hides any sentence that does not match.
- Run `python3 analyze.py && python3 verify_llm.py` (no API key needed) to reproduce the scores and the verification from the files in this repo.

## 심사위원이 바로 보는 법 (3분)

- **직접 질문해 보기(실행 화면)**: https://kfood-agent-598315031037.asia-northeast3.run.app/. 질문을 넣으면 모델이 도구 순서를 정하고 코드가 검사·실행해 유망국가 TOP3를 맨 위에 냅니다. 예시 질문 6개 버튼과 이미 돌린 기록 6건이 화면에 있고, 「분석한 자료」와 「더 정확해지려면 필요한 자료(역제안)」도 보입니다. 하루 50번·총 300번 한도(인스턴스 메모리 기준이라 재시작하면 0부터, 날짜는 한국 시간). 질문에 「~는 빼고」「가중치 70%」처럼 쓰면 제외·가중치를 반영해 다시 계산합니다. 코드는 `live/`.
- **설치 없이 결과 보기**: https://jejuolledev.github.io/lotte-ax-kfood-export/ — 저장소의 결과 파일로 만든 정적 페이지(TOP3·검산 10번·올라오는 곳·자료 빈 곳·검증 거친 설명 문장·계획 단계 실행 기록). `python3 make_results_page.py` 로 다시 만듭니다.
- **키 없이 다시 계산**: `git clone` 후 `python3 analyze.py && python3 verify_llm.py` (표준 라이브러리만, 약 0.1초). 받아 둔 UN Comtrade 원자료 85개 파일이 `데이터/raw/` 에 있습니다.
- **키로 계획 단계 돌리기**: `OPENAI_API_KEY=... python3 plan_tools.py "빼빼로 다음 유럽 나라는 어디인가"` — 모델이 도구 호출 순서를 JSON 으로 정하고, 코드가 계획을 검사(score 없음·explain 뒤 verify 없음·모르는 품목코드면 거부)한 뒤 실행합니다. 키 없이 실행기만 보려면 `python3 plan_tools.py --dry "질문"`. `openai` 패키지가 필요합니다(`pip install openai` 또는 `uv run --with openai python3 plan_tools.py ...`). 실제 호출 기록 6건은 `결과/계획실행_1031_*.json` 에 있습니다(질문·모델이 정한 순서·검사 결과·초·토큰). 첫 8번 호출 중 3번은 모델이 JSON을 둘 보내 첫 JSON 객체만 썼습니다(지금 공개된 6건은 0건).

## 무엇을 하는 코드인가

롯데웰푸드 제품군(비스킷·과자류 HS 1905, 초콜릿 HS 1806, 캔디·껌 HS 1704, 아이스크림 HS 2105)을 어느 나라에 더 팔면 좋을지, 공개 무역 통계로 점수를 매기고 TOP3 를 뽑습니다. 그 다음 AI 모델이 추천 이유 문장을 쓰고, 검증기가 문장 속 숫자를 전부 원자료에서 다시 계산해 맞는 문장만 화면에 내보냅니다. 핵심은 「AI가 쓴 문장은 숫자가 맞아야만 보인다」입니다.

지표 4개(각 25%, 비교 나라 안 백분위)
- size: 그 나라의 수입액(상대국 World, 최근 연도)
- growth: 그 나라 수입액 연평균 증가율(2021 → 2023~2025 중 최근)
- kgrow: 한국의 그 나라 같은 품목 수출 연평균 증가율 2021 → 2025
- kfood: 한국의 그 나라 가공식품(HS 16~21류) 수출 연평균 증가율 2021 → 2025

대상: 한국 수출 2025년 100만 달러 이상, 그 나라 수입 2,000만 달러 이상, 품목 2개 이상. TOP3 는 롯데웰푸드 IR 기준 현지 공장이 있는 나라를 뺀 결과입니다. 현재 결과 TOP3: 영국·네덜란드·미국(민감도 10세트 중 영국 10·네덜란드 10·미국 7번 등장. 9번째는 비교 범위를 26개국으로 넓힌 것(이때 멕시코 1위), 10번째는 그 나라 수입을 빵 뺀 6단위(HS 190531 달콤한 비스킷 + 190532 와플·웨이퍼)로 바꾼 것(한국 수출은 1905 그대로 — 한국 1905 수출의 94%가 1905.90 기타로 신고돼 6단위로 쪼개면 한국 쪽 숫자가 사라짐). 이때도 영국 1위·TOP3 같음). 같은 코드가 「올라오는 나라」(지금 TOP3 밖, 한국 수출 100만 달러 이상·2021→2025 연 20% 이상·그 나라 수입 연 10% 이상·한국 점유율 3% 미만: 말레이시아 캔디·아르헨티나 과자·호주 빙과·멕시코 과자)와 「자료 빈 곳」(무게 없음·수출이 수입의 절반 초과·신고 코드 미확인 등 + 다음 출처)도 함께 출력합니다.

## 실행 순서

```bash
# 1) 점수 계산 + 검증 (키 필요 없음, 받아 둔 원자료와 저장된 모델 문장으로 약 0.1초)
python3 analyze.py && python3 verify_llm.py

# 2) 검증기 v2 ↔ v3 재측정, 어려운 시험 세트 생성 (키 필요 없음)
python3 make_hard_set.py
python3 measure_verify.py

# 3) (선택) 원자료 다시 받기 — UN Comtrade 공개 preview API, 키 없음
python3 fetch_comtrade.py      # 데이터/raw/ 에 이미 파일이 있으면 건너뜀

# 4) (선택) 모델 문장 새로 생성 — OpenAI 키가 필요한 유일한 단계
OPENAI_API_KEY=... python3 llm_explain.py   # 키는 환경변수로만 읽음, 파일에 저장하지 않음
```

Python 3.10 이상, 표준 라이브러리만 사용합니다(설치할 패키지 없음).

### 키 없이 재검증되는 것
`결과/모델문장_*.json`(모델이 이미 쓴 문장 72개 + 화면용 16개)이 저장돼 있으므로, `verify_llm.py`·`make_hard_set.py`·`measure_verify.py`는 OpenAI 키 없이 그대로 다시 돌릴 수 있습니다. 숫자 계산(`analyze.py`)도 `데이터/raw/`의 원자료만 읽습니다.

### 검증기 v3 는 계속 고치는 중
`verify_llm.py`(v3)는 심사 지적을 반영해 지금도 고치는 중입니다. 이 저장소의 판은 2026-10-31 현재 판이며, 고친 뒤 다시 올립니다. 직전 판은 `verify_llm_v2_1030.py`로 같이 두었습니다.

## 파일 설명

| 파일 | 하는 일 |
|---|---|
| `fetch_comtrade.py` | UN Comtrade 공개 API에서 원자료 JSON 내려받기 |
| `analyze.py` | 점수 계산 v2 → `결과/시범결과.json`·`지표_품목x나라.csv`·`종합순위.csv` (근거행 35개 포함) |
| `llm_explain.py` | OpenAI Responses API(Structured Outputs)로 추천 이유 문장 생성 → `결과/모델문장_*.json` |
| `verify_llm.py` | 검증기 v3 — 문장 속 숫자를 인용 근거행에서 다시 계산해 표시/숨김 판정 → `결과/검증_모델문장.json` |
| `verify_llm_v2_1030.py` | 검증기 v2(직전 판, 비교용) |
| `make_hard_set.py` | 맞는 문장 36개를 규칙 6가지로 비틀어 틀린 문장 50개 생성 → `결과/검증_어려운세트.json` |
| `measure_verify.py` | v2 ↔ v3 를 같은 문장으로 재측정 → `결과/검증_v3_요약.json` |
| `analyze_v1_1차심사전.py` · `verify_claims_v1_1차심사전.py` | 1차 독립 심사 전 v1 코드(결과는 `결과/v1_1차심사전/`) |
| `근거_출처.md` | 지원서·포트폴리오에 쓴 숫자마다 출처 위치 |

### 결과 파일 (`결과/`)
- `시범결과.json` — 기준·가중치·종합 상위 10·TOP3·품목별 TOP3·민감도 10세트·범위 넓힘 상위 10·비스킷 빵뺀 TOP5·한국 1905 6단위 구성·나라별 지표·올라오는 나라(규칙 포함)·자료 빈 곳(다음 출처 포함)·재수출 확인·근거행 35개(행마다 출처)
- `지표_품목x나라.csv` · `종합순위.csv` — 나라×품목 지표 표, 종합 순위
- `모델문장_정상.json`(16) · `모델문장_함정.json`(16, 일부 숫자를 일부러 틀리게) · `모델문장_틀림20.json`(20) · `모델문장_맞음20.json`(20) — 모델이 쓴 문장 72개, 문장마다 인용 근거행 id
- `모델문장_화면용.json`(16) — 실제 화면에 쓰는 문장
- `검증_모델문장.json` — 위 문장들의 검증기 판정(표시 / 숨김 / 표시(사람 확인))
- `정답판정_원자료재계산.json` — 문장 72개의 사람 쪽 정답(원자료 재계산 기준, 틀림 22·맞음 50)과 검증기 판정 대조
- `검증_공격문장_수작업.json` — 심사에서 든 공격 문장 17개(전부 틀림)
- `검증_어려운세트.json` — 코드로 만든 틀린 문장 50개 + 원문 36개
- `검증_v3_요약.json` — v2 ↔ v3 재측정 요약. v3: 저장 문장 72개 틀림 22/22 숨김·맞음 47/50 표시, 화면용 오거부 0/16, 공격 17개 뚫림 0/17, 어려운 50개 숨김 50/50(v2는 공격 17개 전부 뚫림)
- `검증_시험.json` — v1 검증 시험(맞는 문장 16/16 통과, 규칙으로 만든 틀린 문장 74/74 걸러짐)
- `v1_1차심사전/` — 1차 독립 심사 전 결과

- `plan_tools.py` — 계획 단계(모델이 도구 순서를 정함, 코드가 검사·실행) · `make_results_page.py` — 정적 결과 페이지(docs/index.html) 생성
- `결과/계획실행_*.json` — 계획 단계 실제 호출 기록

## 데이터 출처

- **UN Comtrade 공개 API**(preview, 키 없음) — `데이터/raw/*.json` 85개 + 참조표 2개(`partners.json`·`reporters.json`), 2026-10-30 내려받음. 한국(410)의 품목별 수출(상대국 전체, 2021~2025), 각국의 품목별 수입(상대국 World, 2021~2025), 한국의 HS 16~21류 수출, 영국·네덜란드·독일 등의 같은 품목 수출(재수출 확인용). 공개 데이터라 원본 그대로 둡니다.
- **롯데웰푸드 IR 자료** — 저작권 때문에 파일은 올리지 않고 링크만: [2025년 4분기 실적설명](https://www.lottewellfood.com/download/ir/259/238901) · [2026년 2분기 실적설명](https://www.lottewellfood.com/download/ir/269/245641)
- **농림축산식품부 보도자료 2026-01-12(2025 K-푸드+ 수출 실적)** — 링크만: https://www.mafra.go.kr/bbs/home/792/576527/artclView.do
- 숫자별 출처 위치는 `근거_출처.md`에 있습니다.

## 라이선스

MIT — `LICENSE` 참고. UN Comtrade 데이터의 이용 조건은 UN Comtrade 쪽 약관을 따릅니다.
