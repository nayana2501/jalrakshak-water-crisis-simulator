"""Readings + site API (API Gateway HTTP API -> Lambda).

POST /readings            (needs x-api-key)  store a tank reading, returns fresh assessment
GET  /readings/{site_id}                     recent readings (?hours=24, max 168)
PUT  /sites/{site_id}     (needs x-api-key)  create/update site config (fields merge)
GET  /sites/{site_id}                        config + latest reading + live assessment
"""
import base64
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone

import model
import store

SITE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class ApiError(Exception):
    def __init__(self, status, msg):
        self.status, self.msg = status, msg


def _resp(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(body)}


def _auth(event):
    token = os.environ.get("API_TOKEN", "")
    supplied = (event.get("headers") or {}).get("x-api-key", "")
    if not token or not hmac.compare_digest(supplied.encode(), token.encode()):
        raise ApiError(401, "missing or wrong x-api-key")


def _body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        b = json.loads(raw)
    except ValueError:
        raise ApiError(400, "body must be JSON")
    if not isinstance(b, dict):
        raise ApiError(400, "body must be a JSON object")
    return b


def _site(v):
    if not isinstance(v, str) or not SITE_RE.match(v):
        raise ApiError(400, "site_id must be lowercase letters, digits and dashes (max 40)")
    return v


def _number(v, name, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ApiError(400, f"{name} must be a number between {lo} and {hi}")
    return v


def _timestamp(v, now):
    if v is None:
        return int(now)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(400, "timestamp must be ISO 8601, e.g. 2026-10-08T18:00:00+05:30")
    if dt.tzinfo is None:
        raise ApiError(400, "timestamp must include a UTC offset")
    ts = int(dt.timestamp())
    if ts > now + 300:
        raise ApiError(400, "timestamp is in the future")
    if ts < now - 7 * 86400:
        raise ApiError(400, "timestamp is older than 7 days")
    return ts


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def post_reading(event, now):
    _auth(event)
    b = _body(event)
    site = _site(b.get("site_id"))
    level = _number(b.get("tank_level"), "tank_level", 0, 100_000_000)
    ts = _timestamp(b.get("timestamp"), now)
    cfg = store.get_config(site)
    if cfg is None:
        raise ApiError(404, f"unknown site '{site}'. Create it first with PUT /sites/{site}")
    store.put_reading(site, ts, level)
    return 201, {"stored": {"site_id": site, "tank_level": level, "timestamp": _iso(ts)},
                 "assessment": store.assess_site(site, cfg, now)}


def get_readings(event, now):
    site = _site(event["pathParameters"]["site_id"])
    try:
        hours = min(168, max(1, int((event.get("queryStringParameters") or {}).get("hours", 24))))
    except ValueError:
        raise ApiError(400, "hours must be an integer")
    rows = store.get_readings(site, now - hours * 3600, now + 600)
    return 200, {"site_id": site, "readings": [{"timestamp": _iso(t), "tank_level": v} for t, v in rows]}


def put_site(event, now):
    _auth(event)
    site = _site(event["pathParameters"]["site_id"])
    b = _body(event)
    unknown = set(b) - set(model.DEFAULTS)
    if unknown:
        raise ApiError(400, f"unknown fields: {sorted(unknown)}")
    cfg = store.get_config(site) or dict(model.DEFAULTS)
    for k, v in b.items():
        if k in model.BOUNDS:
            _number(v, k, *model.BOUNDS[k])
        elif not isinstance(v, str) or len(v) > 120:
            raise ApiError(400, f"{k} must be a string up to 120 characters")
        cfg[k] = v
    store.put_config(site, cfg)
    return 200, {"site_id": site, "config": cfg}


def get_site(event, now):
    site = _site(event["pathParameters"]["site_id"])
    cfg = store.get_config(site)
    if cfg is None:
        raise ApiError(404, f"unknown site '{site}'")
    return 200, {"site_id": site, "config": cfg, "assessment": store.assess_site(site, cfg, now)}


ROUTES = {"POST /readings": post_reading, "GET /readings/{site_id}": get_readings,
          "PUT /sites/{site_id}": put_site, "GET /sites/{site_id}": get_site}


def handler(event, context=None):
    fn = ROUTES.get(event.get("routeKey"))
    if fn is None:
        return _resp(404, {"error": "not found"})
    try:
        status, body = fn(event, int(time.time()))
        return _resp(status, body)
    except ApiError as e:
        return _resp(e.status, {"error": e.msg})
