#!/bin/bash
# Generates and loads the launchd plist for automated LiteLLM database backups

PLIST_PATH="$HOME/Library/LaunchAgents/com.litellm.aios.backup.plist"
REPO_DIR="/opt/Developer/SourceCode/infra/litellm"
BACKUP_SCRIPT="$REPO_DIR/scripts/backup_db.sh"
LOG_PATH="/tmp/litellm_backup.log"

if [ ! -x "$BACKUP_SCRIPT" ]; then
    echo "Warning: Setting execute permission on $BACKUP_SCRIPT"
    chmod +x "$BACKUP_SCRIPT"
fi

# Ensure the LaunchAgents directory exists
mkdir -p "$(dirname "$PLIST_PATH")"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.litellm.aios.backup</string>
    <key>ProgramArguments</key>
    <array>
        <string>$BACKUP_SCRIPT</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>2</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_PATH</string>
    <key>StandardErrorPath</key>
    <string>$LOG_PATH</string>
    <key>WorkingDirectory</key>
    <string>$REPO_DIR</string>
</dict>
</plist>
EOF

echo "Created backup plist at $PLIST_PATH"

# Unload if it already exists to refresh
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# Load the new plist
launchctl load "$PLIST_PATH"

echo "LiteLLM automated backup service loaded into launchd (runs daily at 2:00 AM)."
echo "Logs will be available at $LOG_PATH"
