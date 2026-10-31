"""검증기 v2 ↔ v3 재측정(OpenAI 호출 없음, 2026-10-31).
(가) 저장된 모델 문장 72개(정답: 정답판정_원자료재계산.json 기준 틀림 22·맞음 50) + 화면용 16(전부 맞음)
(나) 심사 공격 문장 17개(결과/검증_공격문장_수작업.json, 전부 틀림)
(다) 코드로 만든 어려운 세트 50개(결과/검증_어려운세트.json, 전부 틀림) + 그 원문 36개(전부 맞음)
사용: python3 measure_verify.py → 결과/검증_v3_요약.json
"""
import json, pathlib, subprocess, time, sys
import verify_llm as v3
import verify_llm_v2_1030 as v2

HERE = pathlib.Path(__file__).parent
RES = HERE / "결과"

# 정답(틀림 22개)은 정답판정 파일 메모 + 틀림20 전부(11만 톤 제외) 기준으로 문장별로 적어 둔다
WRONG_TEXT_KEYS = {
    "모델문장_함정": ["28억 8,448만", "400만 4,74", "154만 5,342"],
    "모델문장_틀림20": "ALL_BUT:11만 톤",
}


def truth(setname, s):
    """맞음=True / 틀림=False (원자료 재계산 정답 파일 기준)."""
    k = WRONG_TEXT_KEYS.get(setname)
    if k is None:
        return True
    if isinstance(k, str):
        return k.split(":")[1] in s["text"]
    return not any(w in s["text"] for w in k)


def load_sets():
    out = []
    for name in ("모델문장_정상", "모델문장_함정", "모델문장_틀림20", "모델문장_맞음20", "모델문장_화면용"):
        d = json.load(open(RES / f"{name}.json", encoding="utf-8"))
        sents = [s for c in d["countries"] for s in c["sentences"]] if "countries" in d else d["sentences"]
        out += [(name, s, truth(name, s)) for s in sents]
    return out


def shown(verdict):
    return verdict.startswith("표시")


def measure(items, mod):
    """items: [(이름, 문장, 맞음?)] → 통계 + 틀린 판정 목록"""
    st = {"n": len(items), "맞는문장": 0, "틀린문장": 0, "틀린문장_숨김": 0, "틀린문장_통과(뚫림)": 0, "맞는문장_표시": 0, "맞는문장_숨김(오거부)": 0,
          "표시_판정종류": {}}
    miss, falsehide = [], []
    for name, s, ok in items:
        v, why = mod.check(s)
        st["표시_판정종류"][v] = st["표시_판정종류"].get(v, 0) + 1
        if ok:
            st["맞는문장"] += 1
            if shown(v):
                st["맞는문장_표시"] += 1
            else:
                st["맞는문장_숨김(오거부)"] += 1; falsehide.append({"세트": name, "text": s["text"], "이유": why})
        else:
            st["틀린문장"] += 1
            if shown(v):
                st["틀린문장_통과(뚫림)"] += 1; miss.append({"세트": name, "유형": s.get("유형", ""), "text": s["text"], "바뀐것": s.get("바뀐것", ""), "판정": v})
            else:
                st["틀린문장_숨김"] += 1
    return st, miss, falsehide


def by_type(items, mod):
    t = {}
    for name, s, ok in items:
        k = s.get("유형", name)
        t.setdefault(k, [0, 0])
        t[k][1] += 1
        if not shown(mod.check(s)[0]):
            t[k][0] += 1
    return {k: f"{a}/{b}" for k, (a, b) in t.items()}


def timing(n=3):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        subprocess.run([sys.executable, "analyze.py"], cwd=HERE, stdout=subprocess.DEVNULL, check=True)
        subprocess.run([sys.executable, "verify_llm.py"], cwd=HERE, stdout=subprocess.DEVNULL, check=True)
        ts.append(round(time.perf_counter() - t0, 3))
    return ts


if __name__ == "__main__":
    base = load_sets()
    base72 = [x for x in base if x[0] != "모델문장_화면용"]
    screen = [x for x in base if x[0] == "모델문장_화면용"]
    attack = [("공격", s, False) for s in json.load(open(RES / "검증_공격문장_수작업.json", encoding="utf-8"))["sentences"]]
    H = json.load(open(RES / "검증_어려운세트.json", encoding="utf-8"))
    hard = [("어려운세트", s, False) for s in H["sentences"]]
    hard_orig = [("어려운세트_원문", s, True) for s in H["originals"]]

    out = {"설명": "검증기 v2(verify_llm_v2_1030.py) ↔ v3(verify_llm.py) 재측정. OpenAI 호출 없음. 정답은 결과/정답판정_원자료재계산.json 기준. 2026-10-31",
           "허용오차_v3": {"자릿수": "표시 자릿수 반 칸(반올림) 또는 버림 한 칸(아래쪽만)", "상대오차": v3.REL_TOL, "약_상대오차": v3.REL_TOL_ABOUT,
                        "배수": "정수여도 소수 첫째 자리 기준(±0.05), 약 → ±5%"}}
    for label, mod in (("v2", v2), ("v3", v3)):
        st72, miss72, fh72 = measure(base72, mod)
        stS, _, fhS = measure(screen, mod)
        stA, missA, _ = measure(attack, mod)
        stH, missH, _ = measure(hard, mod)
        stO, _, fhO = measure(hard_orig, mod)
        out[label] = {
            "가_저장문장72": {**st72, "틀린판정_목록": {"뚫림": miss72, "오거부": fh72}},
            "가_화면용16": {**stS, "오거부": fhS},
            "나_공격17": {**stA, "유형별_숨김": by_type(attack, mod), "뚫림_목록": missA},
            "다_어려운세트50": {**stH, "유형별_숨김": by_type(hard, mod), "뚫림_목록": missH},
            "다_원문36": {**stO, "오거부": fhO},
        }
    # 상대오차를 3%로 하면(참고)
    v3.REL_TOL = 0.03
    st72b, _, fh72b = measure(base72, v3); stHb, _, _ = measure(hard, v3); stAb, _, _ = measure(attack, v3); stOb, _, fhOb = measure(hard_orig, v3)
    out["참고_v3_상대오차3%"] = {"가_72": {"오거부": st72b["맞는문장_숨김(오거부)"], "뚫림": st72b["틀린문장_통과(뚫림)"], "오거부_목록": fh72b},
                          "나_공격17_뚫림": stAb["틀린문장_통과(뚫림)"], "다_50_뚫림": stHb["틀린문장_통과(뚫림)"], "다_원문36_오거부": stOb["맞는문장_숨김(오거부)"]}
    v3.REL_TOL = 0.02
    out["실행시간_analyze+verify_초"] = timing()
    (RES / "검증_v3_요약.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for label in ("v2", "v3"):
        o = out[label]
        print(f"== {label}: 72개 틀림 {o['가_저장문장72']['틀린문장_숨김']}/{o['가_저장문장72']['틀린문장']} 숨김 · 맞음 {o['가_저장문장72']['맞는문장_표시']}/{o['가_저장문장72']['맞는문장']} 표시(오거부 {o['가_저장문장72']['맞는문장_숨김(오거부)']})"
              f" | 화면용 오거부 {o['가_화면용16']['맞는문장_숨김(오거부)']}/16 | 공격 뚫림 {o['나_공격17']['틀린문장_통과(뚫림)']}/17"
              f" | 어려운 50 숨김 {o['다_어려운세트50']['틀린문장_숨김']}/50 | 원문36 오거부 {o['다_원문36']['맞는문장_숨김(오거부)']}/36")
        print("   어려운세트 유형별 숨김:", o["다_어려운세트50"]["유형별_숨김"])
    print("참고 3%:", {k: v for k, v in out["참고_v3_상대오차3%"].items() if "목록" not in k and k != "가_72"}, out["참고_v3_상대오차3%"]["가_72"]["오거부"])
    print("실행시간:", out["실행시간_analyze+verify_초"])
