"""DynamoDB access. Single table, pk/sk.

SITE#<id> | CONFIG          site parameters
SITE#<id> | R#<epoch:012d>   one tank reading (TTL 30 days)
SITE#<id> | RISK             latest hourly assessment + alert state
"""
import os
import time
from decimal import Decimal
from functools import lru_cache

import boto3
from boto3.dynamodb.conditions import Attr, Key

import model

READING_TTL_S = 30 * 86400


@lru_cache(maxsize=1)
def table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _to_ddb(v):
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _to_ddb(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_to_ddb(x) for x in v]
    return v


def clean(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return v


def _pk(site):
    return f"SITE#{site}"


def get_config(site):
    item = table().get_item(Key={"pk": _pk(site), "sk": "CONFIG"}).get("Item")
    if not item:
        return None
    cfg = {**model.DEFAULTS, **clean(item)}
    return {k: v for k, v in cfg.items() if k not in ("pk", "sk")}


def put_config(site, cfg):
    table().put_item(Item=_to_ddb({"pk": _pk(site), "sk": "CONFIG", **cfg}))


def list_site_ids():
    ids, kwargs = [], {"FilterExpression": Attr("sk").eq("CONFIG")}
    while True:  # MVP scale: a scan over a handful of sites is fine
        r = table().scan(**kwargs)
        ids += [i["pk"].split("#", 1)[1] for i in r["Items"]]
        if "LastEvaluatedKey" not in r:
            return ids
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def put_reading(site, ts, level):
    table().put_item(Item=_to_ddb({
        "pk": _pk(site), "sk": f"R#{int(ts):012d}", "ts": int(ts), "level": level,
        "ttl": int(time.time()) + READING_TTL_S}))


def get_readings(site, since_ts, until_ts=None, limit=2000):
    until_ts = until_ts if until_ts is not None else int(time.time()) + 600
    out, kwargs = [], {
        "KeyConditionExpression": Key("pk").eq(_pk(site)) &
        Key("sk").between(f"R#{int(since_ts):012d}", f"R#{int(until_ts):012d}")}
    while len(out) < limit:
        r = table().query(**kwargs)
        out += [(int(i["ts"]), clean(i["level"])) for i in r["Items"]]
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return out[:limit]


def latest_reading(site):
    r = table().query(KeyConditionExpression=Key("pk").eq(_pk(site)) & Key("sk").begins_with("R#"),
                      ScanIndexForward=False, Limit=1)
    return [(int(i["ts"]), clean(i["level"])) for i in r["Items"]]


def get_risk(site):
    item = table().get_item(Key={"pk": _pk(site), "sk": "RISK"}).get("Item")
    return clean(item) if item else None


def put_risk(site, assessment, alert_rank, alert_ts, now_ts):
    table().put_item(Item=_to_ddb({
        "pk": _pk(site), "sk": "RISK", "assessment": assessment,
        "alert_rank": alert_rank, "alert_ts": alert_ts, "checked_ts": int(now_ts)}))


def assess_site(site, cfg, now_ts):
    """Assessment from stored readings, or None if the site has no readings."""
    window = get_readings(site, now_ts - model.WINDOW_H * 3600, now_ts + 600)
    if not window:
        window = latest_reading(site)
    if not window:
        return None
    return model.assess(cfg, window, now_ts)
