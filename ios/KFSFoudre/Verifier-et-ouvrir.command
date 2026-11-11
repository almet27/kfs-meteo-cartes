#!/bin/bash
set -eu
cd "$(dirname "$0")"
if ! xcrun --find xcodebuild >/dev/null 2>&1; then
  printf '%s\n' "Installe Xcode depuis le Mac App Store, puis relance ce fichier."
  exit 1
fi
xcodebuild -project KFSFoudre.xcodeproj -scheme KFSFoudre -configuration Debug -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
open KFSFoudre.xcodeproj
printf '%s\n' "Dans Xcode : branche ton iPhone, sélectionne ton équipe Apple dans Signing & Capabilities, puis lance l’app."
