#!/bin/bash
# Ask Opto from anywhere (right-click Quick Actions use this too).
#   mac/ask-opto.sh "how does a jet engine work"     text
#   mac/ask-opto.sh --screen "what is this?"         + silent screenshot
#   mac/ask-opto.sh path/to/photo.jpg                image file(s)
#   echo "selected text" | mac/ask-opto.sh           stdin (text Quick Action)
# Needs the HUD running (mac/install.sh makes it a login item).
OPTO=${OPTO_URL:-http://127.0.0.1:8765}
HUD=${OPTO_HUD_URL:-http://127.0.0.1:8766}

urlq() { python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1"; }
upload() {  # file -> image_id
  python3 - "$1" "$OPTO" <<'PY'
import base64, json, sys, urllib.request
data = "data:image/jpeg;base64," + base64.b64encode(open(sys.argv[1], "rb").read()).decode()
req = urllib.request.Request(sys.argv[2] + "/api/upload", json.dumps({"image": data}).encode(),
                             {"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req, timeout=30))["image_id"])
PY
}
show() {  # question [image_id]
  local url="$OPTO/?mode=kimi&q=$(urlq "$1")"
  [ -n "$2" ] && url="$url&image_id=$2"
  curl -s -X POST "$HUD/show" -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json, sys; print(json.dumps({"url": sys.argv[1]}))' "$url")"
}

if [ "$1" = --screen ]; then
  shift; tmp=$(mktemp -t opto).png
  screencapture -x "$tmp" && show "${*:-What is on my screen?}" "$(upload "$tmp")"; rm -f "$tmp"
elif [ -f "$1" ]; then
  for img in "$@"; do show "What is this, and how does it work?" "$(upload "$img")"; done
else
  text="${*:-$(cat)}"; [ -n "$text" ] && show "Explain this: ${text:0:360}"
fi
