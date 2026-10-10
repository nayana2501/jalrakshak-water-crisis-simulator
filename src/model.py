"""JalRakshak water-balance model.

A direct port of the simulator in the frontend. Keep the constants and logic in sync with
index.html. Hourly: level = level + supply - use - leak.

ALL of NE, CUT, HEAT, GW are ASSUMPTIONS (illustrative), not measured values.
"""
import math

NE = 0.35      # share of use that is non-essential (assumption)
CUT = 0.40     # share of non-essential use that can be cut (assumption)
HEAT = 0.015   # +1.5% demand per degC above 30 (assumption)
GW = 0.10      # fresh-water saving from greywater reuse (illustrative assumption)
LEAD = 6       # tanker arrives this many hours before predicted empty
HORIZON = 120  # simulation horizon, hours

# Leak calibration from real readings
WINDOW_H = 6        # look at readings from the last N hours
MIN_SPAN_H = 1.0    # need at least this much time between first and last reading
LEAK_SIGNIFICANT = 0.10  # gap must exceed 10% of expected use to count as a leak

DEFAULTS = {
    "name": "",
    "people": 400,
    "temperature_c": 42,
    "supply_change_pct": -30,
    "normal_supply_lpd": 52000,
    "tank_capacity_l": 80000,
    "tanker_size_l": 8000,
    "lpcd": 135,
    "known_leak_lph": 0,
    "inspect_area": "",
}

# field -> (min, max)
BOUNDS = {
    "people": (1, 100000),
    "temperature_c": (0, 60),
    "supply_change_pct": (-100, 100),
    "normal_supply_lpd": (0, 50_000_000),
    "tank_capacity_l": (100, 50_000_000),
    "tanker_size_l": (0, 1_000_000),
    "lpcd": (20, 1000),
    "known_leak_lph": (0, 100_000),
}

RISKS = ["Low", "Moderate", "High", "Extreme"]


def demand(cfg):
    """Return (base, use, inflow, heat) in L/h."""
    heat = max(0.0, cfg["temperature_c"] - 30) * HEAT
    base = cfg["people"] * cfg["lpcd"] / 24
    use = base * (1 + heat)
    inflow = cfg["normal_supply_lpd"] * (1 + cfg["supply_change_pct"] / 100) / 24
    return base, use, inflow, heat


def simulate(use, inflow, leak, level, cap, tanker_l=0, tanker_at=0):
    """Hours until the tank is empty, or None if it lasts the whole horizon."""
    lvl = level
    for h in range(1, HORIZON + 1):
        prev = lvl
        lvl += inflow - use - leak
        if tanker_l and h == tanker_at:
            lvl += tanker_l
        lvl = min(lvl, cap)
        if lvl <= 0:
            return (h - 1) + prev / ((prev - lvl) or 1)
    return None


def _scenario(m, flags):
    use = m["use"] * (1 - (NE * CUT if flags.get("cut") else 0) - (GW if flags.get("gw") else 0))
    leak = 0 if flags.get("leak") else m["leak"]
    e = simulate(use, m["inflow"], leak, m["level"], m["cap"])
    at = 0
    if flags.get("tk") and m["tanker"] > 0 and e is not None:
        at = max(1, math.floor(e - LEAD))
        e = simulate(use, m["inflow"], leak, m["level"], m["cap"], m["tanker"], at)
    return e, at


def _hrs(e):
    return HORIZON if e is None else e


def risk_for(e):
    if e is None:
        return 0
    if e < 12:
        return 3
    if e < 36:
        return 2
    if e < 72:
        return 1
    return 0


def estimate_leak(readings, use, inflow, cap, now_ts):
    """Unexplained loss from the latest tanker-free stretch of readings.

    readings: [(epoch_seconds, level_l)] ascending. A rise in level (tanker delivery)
    restarts the stretch. Returns dict or None when there is not enough clean data.
    """
    recent = [r for r in readings if r[0] >= now_ts - WINDOW_H * 3600]
    rise_tol = 0.005 * cap
    start = 0
    for i in range(1, len(recent)):
        if recent[i][1] > recent[i - 1][1] + rise_tol:
            start = i
    seg = recent[start:]
    if len(seg) < 2:
        return None
    span_h = (seg[-1][0] - seg[0][0]) / 3600
    if span_h < MIN_SPAN_H:
        return None
    if seg[0][1] >= 0.98 * cap or seg[-1][1] <= 0:
        return None  # tank full (overflow caps level) or already empty: drain not measurable
    measured = (seg[0][1] - seg[-1][1]) / span_h
    expected = use - inflow
    return {"measured": measured, "expected": expected, "gap": measured - expected}


def assess(cfg, readings, now_ts):
    """Full risk assessment for one site. readings must be non-empty and ascending."""
    base, use, inflow, heat = demand(cfg)
    cap = cfg["tank_capacity_l"]
    latest_ts, latest_level = readings[-1]
    level = min(latest_level, cap)

    est = estimate_leak(readings, use, inflow, cap, now_ts)
    if est is not None:
        significant = est["gap"] > LEAK_SIGNIFICANT * use
        leak = est["gap"] if significant else 0.0
        leak_source = "readings"
    else:
        leak = float(cfg.get("known_leak_lph", 0))
        leak_source = "site config" if leak > 0 else "none"
    leak_significant = leak > LEAK_SIGNIFICANT * use

    m = {"use": use, "inflow": inflow, "leak": leak, "level": level, "cap": cap,
         "tanker": cfg["tanker_size_l"]}
    e0 = simulate(use, inflow, leak, level, cap)
    rank = risk_for(e0)
    score = 0 if e0 is None else round(100 * (1 - min(e0, 96) / 96))

    # Same default actions the frontend ticks: fix leak, cut non-essential use, schedule tanker.
    flags, prev, last, actions, last_at = {}, _hrs(e0), (e0, 0), [], 0
    for key, name in (("leak", "Fix leak"), ("cut", "Reduce non-essential use"),
                      ("tk", "Schedule tanker")):
        if key == "leak" and leak <= 0:
            continue
        flags = {**flags, key: True}
        e, at = _scenario(m, flags)
        actions.append({"key": key, "name": name, "hours_gained": round(_hrs(e) - prev, 1)})
        prev, last, last_at = _hrs(e), (e, at), at
    e3 = last[0]

    area = cfg.get("inspect_area") or "pipes, taps and the overhead tank"
    site = cfg.get("name") or "the site"
    recs = []
    if leak_significant:
        recs.append(f"inspect {area}")
    # Alert deadline is based on the current (do-nothing) drain, so it is never later than reality.
    tanker_by = max(1, math.floor(e0 - LEAD)) if (e0 is not None and cfg["tanker_size_l"] > 0) else None
    if tanker_by:
        recs.append(f"schedule a {cfg['tanker_size_l']:,.0f} L tanker to arrive within {tanker_by} h")
    recs.append("cut non-essential use")
    recs.append(f"keep {cfg['people'] * 3:,.0f} L reserved for drinking")
    if e0 is None:
        message = f"Water at {site} should last beyond {HORIZON} hours at current rates."
    else:
        loss = f"\nPossible unexplained loss: {leak:,.0f} L/h." if leak_significant else ""
        message = (f"Water at {site} may run out in ~{e0:.0f} hours.{loss}\n"
                   f"Recommended: {'; '.join(recs)}.\n"
                   f"96-hour crisis score: {score}/100 (illustrative index, not a scientific risk score).")

    age_h = max(0.0, (now_ts - latest_ts) / 3600)
    return {
        "site_name": cfg.get("name", ""),
        "level_l": round(level),
        "reading_ts": int(latest_ts),
        "data_age_h": round(age_h, 1),
        "stale": age_h > 3,
        "hours_to_empty": None if e0 is None else round(e0, 1),
        "risk": RISKS[rank],
        "risk_rank": rank,
        "crisis_score_96h": score,
        "leak_lph": round(leak),
        "leak_significant": leak_significant,
        "leak_source": leak_source,
        "measured_drain_lph": None if est is None else round(est["measured"]),
        "expected_drain_lph": round(use - inflow),
        "actions": actions,
        "hours_to_empty_after_actions": None if e3 is None else round(e3, 1),
        "tanker_by_h": tanker_by,
        "message": message,
    }
