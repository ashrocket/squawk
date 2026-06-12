#!/bin/bash
# Build Squawk.app (developer build, ad-hoc signed — no App Store, no notarization).
set -euo pipefail
cd "$(dirname "$0")"

swift build -c release

APP=Squawk.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/release/Squawk "$APP/Contents/MacOS/Squawk"
[ -f Icon.icns ] || { swift make_icon.swift && iconutil -c icns Squawk.iconset -o Icon.icns; }
cp Icon.icns "$APP/Contents/Resources/Icon.icns"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>            <string>Squawk</string>
    <key>CFBundleDisplayName</key>     <string>Squawk</string>
    <key>CFBundleIdentifier</key>      <string>sh.squawk.settings</string>
    <key>CFBundleVersion</key>         <string>1</string>
    <key>CFBundleShortVersionString</key> <string>0.1</string>
    <key>CFBundleExecutable</key>      <string>Squawk</string>
    <key>CFBundleIconFile</key>        <string>Icon</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>LSMinimumSystemVersion</key>  <string>14.0</string>
    <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
PLIST
codesign --force -s - "$APP"
echo "Built $PWD/$APP"
