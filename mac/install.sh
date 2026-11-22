#!/bin/bash
# Install Opto on macOS: menu bar HUD as a login item + right-click Quick Actions.
#   mac/install.sh            install / update
#   mac/install.sh --remove   uninstall
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=com.opto.hud
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SERVICES="$HOME/Library/Services"
UV="$(command -v uv)"

if [ "${1:-}" = --remove ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"; rm -rf "$SERVICES/Ask Opto.workflow" "$SERVICES/Ask Opto (Image).workflow"
  echo "Opto removed."; exit 0
fi

(cd "$ROOT" && "$UV" sync)
mkdir -p "$ROOT/out" "$(dirname "$PLIST")"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$UV</string><string>run</string><string>--directory</string><string>$ROOT</string>
    <string>python</string><string>$ROOT/mac/opto_hud.py</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(dirname "$UV"):/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$ROOT/out/hud.log</string>
  <key>StandardErrorPath</key><string>$ROOT/out/hud.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

python3 "$ROOT/mac/quick_actions.py" "$ROOT/mac/ask-opto.sh"
/System/Library/CoreServices/pbs -update
echo "Opto installed: cube in the menu bar, right-click > Services > Ask Opto."
