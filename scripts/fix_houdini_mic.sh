#!/bin/bash
# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
# fix_houdini_mic.sh
# Patches Houdini Apprentice to enable microphone access on macOS.
#
# macOS requires TWO things for the mic permission dialog to appear:
#   1. NSMicrophoneUsageDescription in the app's Info.plist
#   2. com.apple.security.device.audio-input entitlement in the code signature
#
# Houdini ships with neither — so macOS silently blocks mic access.
#
# Usage (run from Terminal.app):
#   bash ~/Downloads/HoudiniMind\ -\ Copy\ \(2\)/scripts/fix_houdini_mic.sh

set -e

HOUDINI_APP="/Applications/Houdini/Houdini21.0.559/Houdini Apprentice 21.0.559.app"
INFO_PLIST="$HOUDINI_APP/Contents/Info.plist"
ENTITLEMENTS="$(cd "$(dirname "$0")" && pwd)/houdini_mic_entitlements.plist"

echo "============================================"
echo " Houdini Microphone Permission Fix"
echo "============================================"
echo ""

# Check Houdini is not running
if pgrep -f happrentice > /dev/null 2>&1; then
    echo "ERROR: Houdini is still running. Please quit Houdini first."
    exit 1
fi

if [ ! -d "$HOUDINI_APP" ]; then
    echo "ERROR: Houdini app not found at: $HOUDINI_APP"
    exit 1
fi

if [ ! -f "$ENTITLEMENTS" ]; then
    echo "ERROR: Entitlements file not found at: $ENTITLEMENTS"
    exit 1
fi

echo "Step 1/3: Adding NSMicrophoneUsageDescription to Info.plist..."
# Check if already present
if /usr/libexec/PlistBuddy -c "Print :NSMicrophoneUsageDescription" "$INFO_PLIST" 2>/dev/null; then
    echo "  -> Already present, skipping."
else
    sudo /usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'HoudiniMind uses the microphone for speech-to-text input.'" "$INFO_PLIST"
    echo "  -> Added successfully."
fi

echo ""
echo "Step 2/3: Re-signing Houdini with audio-input entitlement..."
sudo codesign --force --sign - \
    --entitlements "$ENTITLEMENTS" \
    --deep \
    "$HOUDINI_APP"
echo "  -> Signed successfully."

echo ""
echo "Step 3/3: Resetting TCC microphone permission..."
tccutil reset Microphone com.sidefx.HoudiniApprentice
echo "  -> TCC reset."

echo ""
echo "============================================"
echo " Verifying..."
echo "============================================"
echo ""
echo "Info.plist NSMicrophoneUsageDescription:"
/usr/libexec/PlistBuddy -c "Print :NSMicrophoneUsageDescription" "$INFO_PLIST" 2>&1 || echo "  MISSING!"
echo ""
echo "Entitlement com.apple.security.device.audio-input:"
codesign -d --entitlements - "$HOUDINI_APP" 2>&1 | grep "audio-input" && echo "  -> Present" || echo "  MISSING!"

echo ""
echo "============================================"
echo " SUCCESS!"
echo "============================================"
echo ""
echo " Now:"
echo "   1. Open Houdini Apprentice"
echo "   2. Start speech-to-text → macOS will prompt for microphone access"
echo "   3. Click 'Allow'"
echo ""
