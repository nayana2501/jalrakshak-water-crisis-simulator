"""Hourly risk check (EventBridge -> Lambda -> SNS).

For every site: assess, store the result, and publish an SNS alert when risk is High or
Extreme. An alert is sent when risk first reaches that level, when it gets worse, or when the
last alert is more than REALERT_H hours old. Alert state resets once risk drops below High.
"""
import os
import time

import boto3

import store

REALERT_H = 6
ALERT_RANK = 2  # High


def _sns():
    return boto3.client("sns")


def handler(event=None, context=None):
    now = int(time.time())
    summary = []
    for site in store.list_site_ids():
        cfg = store.get_config(site)
        a = store.assess_site(site, cfg, now)
        if a is None:
            summary.append({"site_id": site, "status": "no readings"})
            continue
        prev = store.get_risk(site) or {}
        alert_rank, alert_ts = prev.get("alert_rank", 0), prev.get("alert_ts", 0)
        sent = False
        if a["risk_rank"] >= ALERT_RANK:
            worse = a["risk_rank"] > alert_rank
            due = now - alert_ts > REALERT_H * 3600
            if worse or due:
                _sns().publish(
                    TopicArn=os.environ["TOPIC_ARN"],
                    Subject=f"JalRakshak: {a['risk']} water risk at {a['site_name'] or site}"[:100],
                    Message=a["message"])
                alert_rank, alert_ts, sent = a["risk_rank"], now, True
        else:
            alert_rank, alert_ts = 0, 0
        store.put_risk(site, a, alert_rank, alert_ts, now)
        summary.append({"site_id": site, "risk": a["risk"],
                        "hours_to_empty": a["hours_to_empty"], "alert_sent": sent})
    print(summary)
    return summary
