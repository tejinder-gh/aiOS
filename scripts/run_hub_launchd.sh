#!/bin/bash
# Wrapper to start the LiteLLM proxy via launchd

cd /opt/Developer/SourceCode/infra/litellm

# Safely parse and load .env file variables without execution risks
if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # Ignore comments and lines without assignments
        if [[ ! "$line" =~ ^[[:space:]]*# ]] && [[ "$line" =~ = ]]; then
            key=$(echo "$line" | cut -d= -f1 | xargs)
            value=$(echo "$line" | cut -d= -f2- | xargs)
            # Strip quotes
            value="${value#\"}"
            value="${value%\"}"
            value="${value#\'}"
            value="${value%\'}"
            export "$key"="$value"
        fi
    done < .env
fi

# Wait for critical services to be ready before starting proxy
echo "Waiting for Postgres on 5432..."
while ! nc -z localhost 5432; do
  sleep 1
done

echo "Waiting for Redis on 6379..."
while ! nc -z localhost 6379; do
  sleep 1
done

# Rotate log file to prevent unbounded growth
if [ -f /tmp/litellm.log ]; then
    echo "Rotating /tmp/litellm.log..."
    mv /tmp/litellm.log "/tmp/litellm.log.$(date +%F-%H%M%S)"
    # Keep only the last 5 logs
    ls -tp /tmp/litellm.log.* | grep -v '/$' | tail -n +6 | xargs -I {} rm -- {} 2>/dev/null || true
fi

# Enable service control and start proxy
export LITELLM_ENABLE_SERVICE_CONTROL=true
exec uv run python litellm/proxy/proxy_cli.py --config local_hub_config.yaml --use_v2_migration_resolver

