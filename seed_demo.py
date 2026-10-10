"""Create the demo site and post 7 hourly readings through the real API.

Usage: python3 seed_demo.py <api-url> <api-token>

Scenario (all numbers are assumptions you can change in SITE below): a hostel of 400 people,
42 C heat, municipal supply down 30%, and a hidden 300 L/h leak. The readings drain at exactly the
rate the model expects PLUS the leak, so the hourly check should find ~300 L/h unexplained loss.
"""
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
import model  # noqa: E402

SITE_ID = "jiit-hostel"
SITE = {"name": "JIIT Hostel", "people": 400, "temperature_c": 42, "supply_change_pct": -30,
        "normal_supply_lpd": 52000, "tank_capacity_l": 80000, "tanker_size_l": 8000,
        "lpcd": 135, "inspect_area": "Block C pipes and overhead tank"}
HIDDEN_LEAK_LPH = 300
LEVEL_NOW = 45000
HOURS = 6


def call(api, token, method, path, body=None):
    req = urllib.request.Request(api.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", "x-api-key": token})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> {e.code}: {e.read().decode()}")


def main(api, token):
    cfg = {**model.DEFAULTS, **SITE}
    _, use, inflow, _ = model.demand(cfg)
    drain = use - inflow + HIDDEN_LEAK_LPH
    call(api, token, "PUT", f"/sites/{SITE_ID}", SITE)
    rnd = random.Random(7)
    now = datetime.now(timezone.utc)
    for h in range(HOURS, -1, -1):
        level = round(LEVEL_NOW + drain * h + rnd.uniform(-60, 60))
        ts = (now - timedelta(hours=h)).replace(microsecond=0).isoformat()
        r = call(api, token, "POST", "/readings", {"site_id": SITE_ID, "tank_level": level, "timestamp": ts})
        print(f"t-{h}h  {level:>6} L")
    a = r["assessment"]
    print("\nAssessment:\n" + a["message"])
    print(f"\nExpected drain {a['expected_drain_lph']} L/h, measured {a['measured_drain_lph']} L/h")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
