#!/bin/sh
# SPDX-License-Identifier: MIT
# Make the home-screen icons (icon-512.png, icon-192.png, icon-180.png) from icon.html with headless Chrome, and scale
# them with sips (macOS). CHROME names another Chrome or Chromium. Run it again after a change of the skin or the screen.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
CHROME=${CHROME:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --window-size=512,512 \
    --screenshot="$HERE/icon-512.png" "file://$HERE/icon.html"
for n in 192 180; do sips -s format png -z $n $n "$HERE/icon-512.png" --out "$HERE/icon-$n.png" >/dev/null; done
ls -l "$HERE"/icon-*.png
