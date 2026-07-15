#!/bin/bash
# Generates and loads the launchd plist for the LiteLLM Local Hub

PLIST_PATH="$HOME/Library/LaunchAgents/com.litellm.aios.plist"
REPO_DIR="/opt/Developer/SourceCode/infra/litellm"
WRAPPER_SCRIPT="$REPO_DIR/scripts/run_hub_launchd.sh"
LOG_PATH="/tmp/litellm.log"

if [ ! -x "$WRAPPER_SCRIPT" ]; then
    echo "Warning: Setting execute permission on $WRAPPER_SCRIPT"
    chmod +x "$WRAPPER_SCRIPT"
fi

# Ensure the LaunchAgents directory exists (critical on clean macOS setups)
mkdir -p "$(dirname "$PLIST_PATH")"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.litellm.aios</string>
    <key>ProgramArguments</key>
    <array>
        <string>$WRAPPER_SCRIPT</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_PATH</string>
    <key>StandardErrorPath</key>
    <string>$LOG_PATH</string>
    <key>WorkingDirectory</key>
    <string>$REPO_DIR</string>
</dict>
</plist>
EOF

echo "Created plist at $PLIST_PATH"

# Unload if it already exists to refresh
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# Load the new plist
launchctl load "$PLIST_PATH"

echo "LiteLLM Local Hub service loaded into launchd and started."
echo "Logs are available at $LOG_PATH"
