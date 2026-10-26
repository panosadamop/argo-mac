#!/bin/bash
# Installs Argo: builds Argo.app, starts it at login, and (re)starts it now. Run it again after any change.
set -e; cd "$(dirname "$0")"
VERSION=$(tr -d '\n' < VERSION)
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid VERSION: $VERSION"; exit 1; }
IFS=. read -r VERSION_MAJOR VERSION_MINOR VERSION_PATCH <<< "$VERSION"
(( VERSION_MINOR < 1000 && VERSION_PATCH < 1000 )) || { echo "VERSION components must be below 1000"; exit 1; }
BUILD=$((VERSION_MAJOR * 1000000 + VERSION_MINOR * 1000 + VERSION_PATCH))
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ] || { echo "Argo needs macOS 26 or later (it uses Apple's new on-device speech)."; exit 1; }
xcode-select -p >/dev/null 2>&1 || { echo "Needs Apple's command line tools. Run: xcode-select --install   then run ./build.sh again."; exit 1; }
command -v python3 >/dev/null || { echo "Argo needs Python 3. Install it, then run ./build.sh again."; exit 1; }
command -v claude >/dev/null || [ -x ~/.local/bin/claude ] || echo "Note: Claude Code is not installed yet. Argo's setup window can install it, or you can pick Devin or Pi."
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
# A compiler error must leave the installed app and its resources alone.
swiftc -O -module-name Argo -target "$(uname -m)-apple-macos26.0" Argo.swift -o "$STAGE/Argo"
APP=~/Applications/Argo.app   # in Applications so System Settings can list it for permissions
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/ui"
cp argo.py "$APP/Contents/Resources/"
cp ui/*.html ui/*.js "$APP/Contents/Resources/ui/"
cp ui/AppIcon.icns "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.argo.app</string>
<key>CFBundleName</key><string>Argo</string>
<key>CFBundleExecutable</key><string>Argo</string>
<key>CFBundleVersion</key><string>$BUILD</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>ArgoSource</key><string>$(pwd)</string>
<key>LSUIElement</key><true/>
<key>NSMicrophoneUsageDescription</key><string>Argo listens when you use its shortcut or microphone button.</string>
<key>NSAppleEventsUsageDescription</key><string>Argo controls apps like Finder, Chrome and Music when you ask it to.</string>
<key>NSCalendarsFullAccessUsageDescription</key><string>Argo reads your calendar, adds events you request, and asks before moving or deleting existing events. Calendar details are sent to your chosen AI model.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Argo turns your words into text on this Mac.</string>
</dict></plist>
P
mv "$STAGE/Argo" "$APP/Contents/MacOS/Argo"
# With a code-signing identity named "Argo Local Signing" in the keychain, macOS keeps permissions across
# rebuilds and auto-updates; ad hoc signing would ask for every permission again after each one. So make it once.
ID=$(security find-identity -p codesigning | awk '/Argo Local Signing/{print $2; exit}')
if [ -z "$ID" ]; then
  K=$(mktemp -d)
  /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 7300 -subj "/CN=Argo Local Signing" -addext "extendedKeyUsage=critical,codeSigning" \
    -addext "keyUsage=critical,digitalSignature" -keyout "$K/k.pem" -out "$K/c.pem" 2>/dev/null &&
  /usr/bin/openssl pkcs12 -export -inkey "$K/k.pem" -in "$K/c.pem" -out "$K/a.p12" -passout pass:argo 2>/dev/null &&
  security import "$K/a.p12" -P argo -T /usr/bin/codesign >/dev/null 2>&1 || true   # fails quietly: ad hoc still works
  rm -rf "$K"
  ID=$(security find-identity -p codesigning | awk '/Argo Local Signing/{print $2; exit}')
fi
codesign -s "${ID:--}" --force "$APP"
# register with macOS, or System Settings can't list it for permissions
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
# Installed before as Atticus: stop that copy and its login item, and copy its data over once (the old folder stays).
OLD=~/Library/LaunchAgents/com.atticus.app.plist
if [ -f "$OLD" ]; then launchctl bootout gui/$(id -u)/com.atticus.app 2>/dev/null || true; rm -f "$OLD"; fi
pkill -f "Atticus.app/Contents/MacOS/Atticus$" 2>/dev/null || true
if [ -d ~/.config/atticus ] && [ ! -e ~/.config/argo ]; then cp -Rp ~/.config/atticus ~/.config/argo; fi
AGENT=~/Library/LaunchAgents/com.argo.app.plist   # starts at login, restarts if it crashes (Quit stays quit)
mkdir -p ~/Library/LaunchAgents ~/.config/argo
cat > "$AGENT" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.argo.app</string>
<key>ProgramArguments</key><array><string>$APP/Contents/MacOS/Argo</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
<key>StandardErrorPath</key><string>$HOME/.config/argo/app.err</string>
</dict></plist>
P
[ -n "$ARGO_NO_RESTART" ] && exit 0   # the app's own updater restarts it when idle
# Reload the job so launchd refreshes its executable signing requirement after a rebuild.
launchctl bootout gui/$(id -u)/com.argo.app 2>/dev/null || true
pkill -f "$APP/Contents/MacOS/Argo$" 2>/dev/null && sleep 1   # stop a copy opened by hand too
# bootout can return before the job has finished unloading.
launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || { sleep 1; launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || {
  echo "Could not add Argo to Login Items; opening it directly instead."
  open "$APP"
}; }
echo "Argo is running. Hold Control+Option+Space and talk."
