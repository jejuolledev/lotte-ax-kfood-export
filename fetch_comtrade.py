"""UN Comtrade 공개 API(무료 preview, 키 없음)에서 예선 시범 계산용 원자료를 내려받는다.

받는 것
  1) 한국(410)의 품목별 수출 — 상대국 전체, 2021~2025
  2) 각국의 품목별 수입(상대국 = World 0) — 2021~2025 (보고국 전체)
품목(HS 4단위)
  1905 빵·비스킷·과자류(빼빼로·칸쵸 등 비스킷류가 속함)
  1806 초콜릿·코코아 조제품(가나 등)
  1704 설탕 과자(캔디·껌, 코코아 없는 것)
  2105 아이스크림(빙과)
원본 JSON은 data/raw/ 에 받은 날짜와 함께 그대로 둔다(나중에 다시 계산·대조용).
사용: python3 fetch_comtrade.py
"""
import json, time, urllib.request, pathlib, datetime

RAW = pathlib.Path(__file__).parent / "데이터" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
BASE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
CMDS = ["1905", "1806", "1704", "2105"]
YEARS = [2021, 2022, 2023, 2024, 2025]
TODAY = datetime.date.today().isoformat()


def get(q, name):
    path = RAW / name
    if path.exists():
        return
    url = f"{BASE}?{q}"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.load(r)
            if d.get("error"):
                raise RuntimeError(d["error"])
            d["_fetched"] = TODAY
            d["_url"] = url
            path.write_text(json.dumps(d, ensure_ascii=False))
            print(name, len(d.get("data") or []))
            time.sleep(1.5)
            return
        except Exception as e:  # 공개 preview는 요청 간격 제한이 있어 잠시 쉬고 다시
            print("retry", name, e)
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"실패: {name}")


for c in CMDS:
    for y in YEARS:
        get(f"reporterCode=410&period={y}&cmdCode={c}&flowCode=X", f"kor_export_{c}_{y}.json")
        get(f"period={y}&cmdCode={c}&flowCode=M&partnerCode=0", f"world_import_{c}_{y}.json")

# --- 1차 심사 뒤 추가(2026-10-30 밤) ---
# K-가공식품 전체 수요: 한국의 HS 16~21류(가공식품) 나라별 수출 2021·2025
# (공개 preview는 한 번에 500행까지라 류별로 나눠 받는다)
for y in (2021, 2025):
    for ch in ("16", "17", "18", "19", "20", "21"):
        get(f"reporterCode=410&period={y}&cmdCode={ch}&flowCode=X", f"kor_export_ch{ch}_{y}.json")
# 재수출 확인: 네덜란드·영국·독일의 비스킷·아이스크림 수출(상대국 World) 2025
for c in ("1905", "2105"):
    get(f"reporterCode=528,826,276&period=2025&cmdCode={c}&flowCode=X&partnerCode=0", f"hub_export_{c}_2025.json")
