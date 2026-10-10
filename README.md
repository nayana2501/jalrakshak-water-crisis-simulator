# JalRakshak — Water Crisis Simulator

**Predict when a hostel, housing society, or campus could run out of water—and compare actions that may extend the supply.**

JalRakshak is a water-balance simulator for exploring shortage scenarios, estimating possible unexplained water loss, and comparing interventions such as fixing a leak, reducing non-essential use, reusing suitable greywater, and scheduling a tanker.

> **Important:** Results are estimates based on editable assumptions, not live measurements or guaranteed real-world predictions. Replace the defaults with site-specific readings before using the model for operational decisions.

## Features

- Adjust temperature, population, supply change, known leak rate, tank level and capacity, normal supply, tanker size, and per-person water use.
- Compare a “do nothing” forecast with selected conservation and recovery actions.
- View an illustrative 96-hour shortage-risk score and tank-level chart.
- Estimate a possible leak from two tank readings taken over a known time interval, provided no tanker delivery occurred between readings.
- See a simple 24-hour supply-versus-demand estimate and a plain-language explanation of the model's calculations.
- Includes a Python model and AWS SAM template for a serverless backend design.

## Project structure

```text
jalrakshak-water-crisis-simulator/
├── frontend/
│   ├── index.html          # Browser-based simulator
│   └── config.js           # Frontend configuration placeholder
├── src/
│   ├── model.py            # Water balance and risk model
│   ├── readings.py         # API Gateway/Lambda handlers
│   ├── risk_check.py       # Scheduled risk checks and SNS alerts
│   ├── store.py            # DynamoDB persistence helpers
│   └── requirements.txt    # Lambda runtime dependency (boto3)
├── tests/
│   └── test_backend.py     # Backend tests using mocked AWS services
├── template.yaml           # AWS SAM infrastructure template
├── seed_demo.py            # Helper to seed sample readings via the API
├── deploy.sh               # Optional deployment helper
├── .gitignore
└── README.md
```

## Run the simulator locally

The frontend can be used as a standalone browser simulator. No AWS account is required for this mode.

**Option A — open the file:** open `frontend/index.html` in a browser.

**Option B — run a local web server (recommended):** from the project root, run:

```powershell
py -3.12 -m http.server 8000
```

Then visit <http://localhost:8000/frontend/>.

## Run the backend tests

Python 3.12 is recommended. In PowerShell, from the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install pytest boto3 "moto[dynamodb,s3]"
.\.venv\Scripts\python.exe -m pytest -v
```

The test suite exercises model consistency and the API/alert handlers with mocked AWS services. It does not require deploying AWS resources. A passing run should show **2 passed**.

## Validate and build with AWS SAM

Install the AWS SAM CLI, then run from the project root:

```powershell
sam validate --template-file template.yaml --region us-east-1
sam validate --lint --template-file template.yaml --region us-east-1
sam build --template-file template.yaml
```

These commands validate and package build artifacts locally; they do **not** deploy the application. Docker is needed for SAM's local Lambda emulation commands, but not for the validation and build steps above.

## AWS architecture

The SAM template defines this intended serverless architecture:

- **Amazon S3 + CloudFront** — static frontend hosting.
- **API Gateway HTTP API** — HTTP endpoints for sites and readings.
- **AWS Lambda** — reading/site API handlers and scheduled risk checks.
- **Amazon DynamoDB** — site configuration, readings, and risk state.
- **Amazon EventBridge** — invokes the risk check hourly.
- **Amazon SNS** — email notifications for high or extreme water risk.

**Deployment status:** this repository includes an AWS SAM template and local validation/build instructions. Do not assume the cloud architecture is deployed; a live URL and email alerts require a successful AWS deployment and configuration.

### API routes defined by the backend

| Method | Route | Purpose |
|---|---|---|
| `PUT` | `/sites/{site_id}` | Create or update site settings; requires `x-api-key` |
| `POST` | `/readings` | Store a tank reading and return an assessment; requires `x-api-key` |
| `GET` | `/readings/{site_id}?hours=24` | Retrieve recent readings |
| `GET` | `/sites/{site_id}` | Retrieve site settings and the latest assessment |

The `ApiToken` parameter in `template.yaml` is a shared demo secret. Do not commit real secrets or place API tokens in public frontend code. A production system should use stronger identity and access controls.

## Model assumptions and limitations

Some model parameters are illustrative assumptions rather than measured facts, including:

- Baseline consumption: 135 litres per person per day by default.
- Non-essential use share and reducible fraction.
- Heat-related demand increase above 30°C.
- Fresh-water savings from suitable greywater reuse.
- A tanker lead time of six hours in the scenario model.

Leak estimation depends on the quality and timing of readings. A change in tank level may have causes other than a leak, including supply changes, unrecorded use, measurement error, or tanker delivery. Treat a leak signal as a prompt to investigate, not definitive proof.

The frontend simulator and Python backend model are separate pieces of the project. The UI's local scenario mode can be used without AWS; the cloud APIs and notifications require deployment and configuration before they are live.

## Built for Environmental Hacks 2026

JalRakshak addresses the **Heat and Water** track by helping users reason about shortages, leaks, and water conservation. The project aims to make assumptions visible and let people compare possible actions before a shortage occurs.
