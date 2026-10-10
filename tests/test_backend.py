"""Local end-to-end test with moto (no AWS needed). Run: python3 tests/test_backend.py"""
import json
import os
import sys
import time

os.environ.update(AWS_DEFAULT_REGION="ap-south-1", AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                  TABLE_NAME="t", API_TOKEN="test-token-123456")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import boto3
from moto import mock_aws

import model


def test_model_matches_frontend():
    # Frontend defaults (42C, 400 people, -30% supply, 300 L/h leak, 45,000 L) -> JS gives ~31.3 h
    cfg = {**model.DEFAULTS}
    base, use, inflow, heat = model.demand(cfg)
    assert round(use) == 2655 and round(inflow) == 1517, (use, inflow)
    e = model.simulate(use, inflow, 300, 45000, 80000)
    assert abs(e - 31.3) < 0.2, e
    # No leak: ~39.5 h, Moderate
    assert abs(model.simulate(use, inflow, 0, 45000, 80000) - 39.5) < 0.2


def call(handler, route, body=None, path=None, headers=None, qs=None):
    ev = {"routeKey": route, "headers": headers if headers is not None else {"x-api-key": "test-token-123456"},
          "pathParameters": path, "queryStringParameters": qs,
          "body": json.dumps(body) if body is not None else None}
    r = handler(ev)
    return r["statusCode"], json.loads(r["body"])


@mock_aws
def test_api_and_alerts():
    ddb = boto3.resource("dynamodb")
    ddb.create_table(TableName="t", BillingMode="PAY_PER_REQUEST",
                     AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
                     KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
    sns = boto3.client("sns")
    arn = sns.create_topic(Name="alerts")["TopicArn"]
    sqs = boto3.client("sqs")
    q = sqs.create_queue(QueueName="q")["QueueUrl"]
    sns.subscribe(TopicArn=arn, Protocol="sqs",
                  Endpoint=sqs.get_queue_attributes(QueueUrl=q, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"])
    os.environ["TOPIC_ARN"] = arn

    import readings, risk_check
    h = readings.handler

    # auth + validation
    assert call(h, "POST /readings", {"site_id": "s1", "tank_level": 1}, headers={})[0] == 401
    assert call(h, "POST /readings", {"site_id": "s1", "tank_level": 1})[0] == 404       # unknown site
    assert call(h, "PUT /sites/{site_id}", {"people": -5}, {"site_id": "s1"})[0] == 400
    assert call(h, "PUT /sites/{site_id}", {"bogus": 1}, {"site_id": "s1"})[0] == 400
    assert call(h, "GET /sites/{site_id}", path={"site_id": "Bad_ID"})[0] == 400

    s, _ = call(h, "PUT /sites/{site_id}", {"name": "JIIT Hostel", "inspect_area": "Block C"}, {"site_id": "s1"})
    assert s == 200
    assert call(h, "POST /readings", {"site_id": "s1", "tank_level": 1, "timestamp": "2026-10-08T18:00:00"})[0] == 400  # no offset
    assert call(h, "POST /readings", {"site_id": "s1", "tank_level": "x"})[0] == 400

    # seed like seed_demo.py: drain = expected 1138 + 300 leak
    cfg = {**model.DEFAULTS}
    _, use, inflow, _ = model.demand(cfg)
    drain = use - inflow + 300
    now = int(time.time())
    for hrs in range(6, -1, -1):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - hrs * 3600))
        s, b = call(h, "POST /readings", {"site_id": "s1", "tank_level": round(45000 + drain * hrs), "timestamp": ts})
        assert s == 201, b
    a = b["assessment"]
    print(a["message"])
    assert abs(a["leak_lph"] - 300) < 15, a["leak_lph"]
    assert a["risk"] == "High" and a["leak_significant"] and 30 < a["hours_to_empty"] < 33
    assert "Block C" in a["message"] and "96-hour crisis score" in a["message"]

    s, b = call(h, "GET /readings/{site_id}", path={"site_id": "s1"}, qs={"hours": "24"}, headers={})
    assert s == 200 and len(b["readings"]) == 7

    # hourly check: first run alerts, second run within 6h is silent
    r1 = risk_check.handler()
    assert r1[0]["alert_sent"] is True, r1
    r2 = risk_check.handler()
    assert r2[0]["alert_sent"] is False, r2
    msgs = sqs.receive_message(QueueUrl=q, MaxNumberOfMessages=10).get("Messages", [])
    assert len(msgs) == 1 and "may run out" in msgs[0]["Body"]

    # tanker delivery (level jumps up) must not be read as a negative leak / crash
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now))
    call(h, "POST /readings", {"site_id": "s1", "tank_level": 60000, "timestamp": ts})
    a2 = call(h, "GET /sites/{site_id}", path={"site_id": "s1"}, headers={})[1]["assessment"]
    assert a2["measured_drain_lph"] is None or a2["leak_lph"] == 0 or a2["leak_lph"] >= 0


if __name__ == "__main__":
    test_model_matches_frontend()
    test_api_and_alerts()
    print("ALL OK")
