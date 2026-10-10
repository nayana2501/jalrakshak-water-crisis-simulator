# JalRakshak: AWS backend

```text
S3 + CloudFront (frontend/) -> API Gateway (HTTP API) -> Lambda: readings.py  -> DynamoDB
                                                           EventBridge (hourly) -> Lambda: risk_check.py -> SNS email
```

Water model (`src/model.py`) is a Python port of the simulator. Same constants, same maths.
Assumptions that stay labelled in the UI: 135 L/person/day, 35% non-essential, 40% cut, 10% greywater, 1.5%/degC heat, consumption splits. The crisis score is a **96-hour crisis score**, an illustrative index.

## API

| Route | Auth | Purpose |
|---|---|---|
| `PUT /sites/{site_id}` | `x-api-key` | create/update site settings (fields merge) |
| `POST /readings` | `x-api-key` | `{"site_id","tank_level","timestamp"}`; returns a fresh assessment |
| `GET /readings/{site_id}?hours=24` | none | recent readings |
| `GET /sites/{site_id}` | none | settings + live assessment (the simulator loads this) |

Leak estimate: from readings in the last 6 h with no tanker delivery (a rise in level restarts the window), unexplained loss = measured drain minus the model's expected drain. It counts as a leak when above 10% of expected use.

Alerts: hourly check emails via SNS when risk is High/Extreme (hours to empty < 36). It re-alerts when risk worsens or after 6 h, and resets when risk drops below High.

## Deploy (about 10 minutes)

Needs AWS CLI (`aws configure`) and SAM CLI.

```bash
cd jalrakshak
./deploy.sh you@example.com 'pick-a-long-secret'
# click the SNS confirmation link in your email, then:
python3 seed_demo.py <ApiUrl> 'pick-a-long-secret'
```

Open the printed Site URL. The page auto-loads `jiit-hostel`.
Force an alert now (don't wait for the hour): `aws lambda invoke --function-name <RiskFunctionName> /dev/stdout`.
Local test, no AWS: `pip install moto boto3 && python3 tests/test_backend.py`.
Tear down: `sam delete --stack-name jalrakshak` (empty the S3 bucket first).

## Known limitations

- Readings are submitted by a person or script (a sensor can call the same endpoint). There is no IoT hardware.
- No alert if readings stop arriving (the UI flags data older than 3 h as stale).
- One shared API token; use Amazon Cognito for production authentication.
- Temperature and supply change are site settings you update, not live feeds.
