#!/usr/bin/env bash
# Rollback to a task checkpoint tag.
# Usage: rollback.sh <task_number>

set -euo pipefail

TASK_NUM="${1:?Usage: rollback.sh <task_number>}"
TAG="checkpoint-task-$(printf '%03d' "$TASK_NUM")"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_BRANCH="rollback-backup-${TIMESTAMP}"

echo "Checking for checkpoint tag: $TAG"

if ! git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ERROR: Tag $TAG not found. Available checkpoints:"
    git tag -l 'checkpoint-task-*'
    exit 1
fi

echo "Creating backup branch: $BACKUP_BRANCH"
git branch "$BACKUP_BRANCH"

echo "Resetting to $TAG..."
git reset --hard "$TAG"

echo ""
echo "Rollback complete."
echo "  Rolled back to: $TAG"
echo "  Backup branch:  $BACKUP_BRANCH"
echo ""
echo "To undo this rollback: git checkout $BACKUP_BRANCH"
