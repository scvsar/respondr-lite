#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: $0 <resource-group> <storage-account-name> <function-app-name> [location]" >&2
  exit 1
fi

RG=$1
SA_NAME=$2
FUNC_NAME=$3
LOCATION=${4:-"eastus"}

az deployment group create \
  --resource-group "$RG" \
  --template-file "$(dirname "$0")/main.bicep" \
  --parameters saName="$SA_NAME" functionAppName="$FUNC_NAME" location="$LOCATION"
