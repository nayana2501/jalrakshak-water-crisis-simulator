#!/usr/bin/env bash
# Usage: ./deploy.sh you@example.com 'a-long-secret-token'
# Needs: AWS CLI configured (aws configure), AWS SAM CLI. Run from the jalrakshak/ folder.
set -euo pipefail
EMAIL="${1:?usage: ./deploy.sh <alert-email> <api-token (12+ chars)>}"
TOKEN="${2:?usage: ./deploy.sh <alert-email> <api-token (12+ chars)>}"
STACK="${STACK:-jalrakshak}"

sam build
sam deploy --stack-name "$STACK" --resolve-s3 --capabilities CAPABILITY_IAM \
  --no-confirm-changeset --no-fail-on-empty-changeset \
  --parameter-overrides "AlertEmail=$EMAIL" "ApiToken=$TOKEN"

out() { aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
API="$(out ApiUrl)"; SITE="$(out SiteUrl)"; BUCKET="$(out BucketName)"

# Point the page at the API (config.js holds only the public API URL, never the token)
echo "window.JAL_API=\"$API\";" > frontend/config.js
aws s3 sync frontend/ "s3://$BUCKET/" --delete

echo
echo "Site:  $SITE"
echo "API:   $API"
echo "1) Click the SNS confirmation link sent to $EMAIL"
echo "2) python3 seed_demo.py $API '$TOKEN'"
