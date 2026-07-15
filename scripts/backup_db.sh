#!/bin/bash
# Backup litellm Postgres database

# Exit immediately if a command exits with a non-zero status, and ensure
# pipeline failures (like pg_dump failing before gzip) are caught.
set -eo pipefail

BACKUP_DIR="${HOME}/.litellm_backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/litellm_db_$TIMESTAMP.sql.gz"
TEMP_BACKUP_FILE="${BACKUP_FILE}.tmp"

# Clean up temp file if the script exits or is interrupted before completion
trap 'rm -f "$TEMP_BACKUP_FILE"' EXIT

# Load .env file safely
REPO_DIR="/opt/Developer/SourceCode/infra/litellm"
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

echo "Backing up litellm Postgres database to $BACKUP_FILE..."
if [ -n "$DATABASE_URL" ]; then
    pg_dump "$DATABASE_URL" | gzip > "$TEMP_BACKUP_FILE"
else
    pg_dump litellm | gzip > "$TEMP_BACKUP_FILE"
fi

mv "$TEMP_BACKUP_FILE" "$BACKUP_FILE"

# Cancel the trap since we completed successfully
trap - EXIT

echo "Pruning backups older than 7 versions..."
# Gather backups matches the ISO date format (which sorts naturally)
# Disable globbing expansion issues if no files match
shopt -s nullglob
files=( "$BACKUP_DIR"/litellm_db_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9].sql.gz )
shopt -u nullglob

num_files=${#files[@]}
if [ "$num_files" -gt 7 ]; then
    num_to_delete=$((num_files - 7))
    echo "Removing $num_to_delete older backup(s)..."
    for ((i=0; i<num_to_delete; i++)); do
        rm -f "${files[i]}"
    done
fi

echo "Backup complete!"
echo ""
echo "To automate this backup, add a cron job using 'crontab -e'."
echo "For example, to run daily at 2:00 AM, add the following line:"
echo "0 2 * * * /opt/Developer/SourceCode/infra/litellm/scripts/backup_db.sh >> /tmp/litellm_backup.log 2>&1"

