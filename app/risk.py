import math
from dataclasses import dataclass

RULES = {
    "tab_switch":      {"base": 10, "fp": 0.20, "label": "Tab almashtirish"},
    "focus_lost":      {"base": 8,  "fp": 0.20, "label": "Fokus yo'qoldi"},
    "fullscreen_exit": {"base": 12, "fp": 0.10, "label": "Fullscreen'dan chiqdi"},
    "clipboard_use":   {"base": 5,  "fp": 0.10, "label": "Nusxa/qo'yish"},
    "fast_answer":     {"base": 5,  "fp": 0.30, "label": "Juda tez javob"},
}
LEVELS = [(25, "Past"), (50, "O'rta"), (75, "Yuqori"), (100, "Kritik")]


def level_of(score: int) -> str:
    return next((n for m, n in LEVELS if score <= m), "Kritik")


@dataclass
class RiskResult:
    scored: list[dict]
    total: int

    @property
    def level(self) -> str:
        return level_of(self.total)


def compute_risk(events: list[dict]) -> RiskResult:
    counts: dict[str, int] = {}
    scored = []
    for e in events:
        if e.get("fp"):
            scored.append({**e, "score": 0.0})
            continue
        r = RULES.get(e["type"])
        if not r:
            scored.append({**e, "score": 0.0})
            continue
        counts[e["type"]] = counts.get(e["type"], 0) + 1
        repeat = 1 + math.log2(counts[e["type"]])
        scored.append({**e, "score": r["base"] * e.get("conf", 1.0) * (1 - r["fp"]) * repeat})
    total = min(150, round(sum(e["score"] for e in scored if not e.get("fp"))))
    return RiskResult(scored=scored, total=total)
