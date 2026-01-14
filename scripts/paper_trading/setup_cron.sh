#!/bin/bash
# Setup script for EVA Finance Paper Trading cron jobs

set -e

echo "Setting up EVA Finance Paper Trading cron jobs..."

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

# Create logs directory if it doesn't exist
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
echo "✓ Created logs directory: $LOG_DIR"

# Make scripts executable
chmod +x "$SCRIPT_DIR/paper_trade_entry.py"
chmod +x "$SCRIPT_DIR/paper_trade_updater.py"
echo "✓ Made scripts executable"

# Check if cron jobs are already installed
if crontab -l 2>/dev/null | grep -q "paper_trading_updater.py"; then
    echo "⚠️  Paper trading cron jobs already installed"
    echo ""
    echo "Current cron jobs:"
    crontab -l | grep paper_trading
    echo ""
    read -p "Do you want to reinstall? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Skipping cron installation"
        exit 0
    fi

    # Remove existing paper trading cron jobs
    crontab -l | grep -v paper_trading | crontab -
    echo "✓ Removed existing cron jobs"
fi

# Install cron jobs
CRON_FILE="$SCRIPT_DIR/crontab_paper_trading"

# Append to existing crontab
(crontab -l 2>/dev/null; cat "$CRON_FILE") | crontab -

echo "✓ Installed cron jobs:"
echo ""
cat "$CRON_FILE" | grep -v "^#" | grep -v "^$"
echo ""

echo "✅ Setup complete!"
echo ""
echo "Cron schedule:"
echo "  - Daily updater: Weekdays at 4:30 PM ET (21:30 UTC)"
echo "  - Entry checker: Saturdays at 10:00 AM ET (15:00 UTC)"
echo ""
echo "Logs will be written to:"
echo "  - $LOG_DIR/paper_trading_updater.log"
echo "  - $LOG_DIR/paper_trading_entry.log"
echo ""
echo "To view installed cron jobs: crontab -l"
echo "To remove cron jobs: crontab -e (then delete the paper trading lines)"
