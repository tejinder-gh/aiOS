#!/bin/bash
# Script to generate a virtual key in LiteLLM for per-app budgets and tracking

# Resolve paths regardless of where the script is run from
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ENV_FILE="$DIR/../.env"

# Safely extract the master key from .env without sourcing or polluting the environment
MASTER_KEY="sk-1234"
if [ -f "$ENV_FILE" ]; then
    LITELLM_MASTER_KEY=$(grep -E "^[[:space:]]*LITELLM_MASTER_KEY[[:space:]]*=" "$ENV_FILE" | cut -d= -f2- | cut -d'#' -f1 | xargs)
    LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY#\"}"
    LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY%\"}"
    LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY#\'}"
    LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY%\'}"
    if [ -n "$LITELLM_MASTER_KEY" ]; then
        MASTER_KEY="$LITELLM_MASTER_KEY"
    fi
fi

# Ask for an application name
read -p "Enter the application name (e.g., 'my-chat-app'): " APP_NAME
if [ -z "$APP_NAME" ]; then
    echo "Error: Application name is required!"
    exit 1
fi

# Ask for a budget and validate it
read -p "Enter a budget (e.g., 5.0 for $5, leave blank for none): " BUDGET

# Validate budget is either empty or a valid positive number (integer or float)
if [ -n "$BUDGET" ]; then
    if ! [[ "$BUDGET" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
        echo "Error: Budget must be a positive number (e.g., 5 or 5.0). Got: '$BUDGET'"
        exit 1
    fi
fi

# Construct payload
PAYLOAD="{\"models\": [\"*\"], \"key_alias\": \"${APP_NAME}\""
if [ -n "$BUDGET" ]; then
    PAYLOAD="${PAYLOAD}, \"max_budget\": ${BUDGET}"
fi
PAYLOAD="${PAYLOAD}}"

echo "Sending request to http://localhost:4000/key/generate..."

# Execute curl, capturing output and HTTP status code
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST 'http://localhost:4000/key/generate' \
--header "Authorization: Bearer $MASTER_KEY" \
--header 'Content-Type: application/json' \
--data-raw "$PAYLOAD")

CURL_EXIT_CODE=$?
if [ $CURL_EXIT_CODE -ne 0 ]; then
    echo "Error: Failed to connect to the LiteLLM proxy (curl exit code: $CURL_EXIT_CODE)."
    echo "Please ensure the proxy is running on http://localhost:4000"
    exit 1
fi

# Extract body and status code (and strip carriage returns)
HTTP_BODY=$(echo "$RESPONSE" | sed -e '$ d' | tr -d '\r')
HTTP_STATUS=$(echo "$RESPONSE" | tail -n 1 | tr -d '\r')

if [ "$HTTP_STATUS" != "200" ]; then
    echo "Error: Server returned HTTP status $HTTP_STATUS."
    echo "Response: $HTTP_BODY"
    exit 1
fi

echo ""
# Check if jq is available for pretty printing
if command -v jq &> /dev/null; then
    GENERATED_KEY=$(echo "$HTTP_BODY" | jq -r '.key' 2>/dev/null)
    if [ -n "$GENERATED_KEY" ] && [ "$GENERATED_KEY" != "null" ]; then
        echo "✅ Success! Your new virtual API Key is:"
        echo ""
        echo "    $GENERATED_KEY"
        echo ""
        echo "Point your apps to http://localhost:4000/v1 and use this key."
        exit 0
    fi
fi

# Fallback print if jq is missing or fails to parse key
echo "✅ Success! Generated Key Info:"
echo "$HTTP_BODY"
echo ""
echo "Use the 'key' field returned above as your API Key."
