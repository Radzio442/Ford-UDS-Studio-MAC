#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="Ford UDS Studio"
VERSION="$(cat VERSION 2>/dev/null || echo 2.11.1)"
DMG_NAME="Ford_UDS_Studio_${VERSION}_macOS.dmg"

PYTHON_BIN="${PYTHON_BIN:-python3}"

printf '\n[1/6] Sprawdzanie macOS...\n'
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "BŁĄD: .app i .dmg muszą być budowane na macOS."
  exit 1
fi

printf '\n[2/6] Instalowanie zależności...\n'
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements.txt pyinstaller

printf '\n[3/6] Czyszczenie poprzedniego buildu...\n'
rm -rf build dist "${APP_NAME}.spec.bak" dmg_stage "$DMG_NAME"

printf '\n[4/6] Budowanie aplikacji...\n'
"$PYTHON_BIN" -m PyInstaller --clean --noconfirm "Ford UDS Studio.spec"

APP_PATH="dist/${APP_NAME}.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "BŁĄD: Nie utworzono $APP_PATH"
  exit 1
fi

printf '\n[5/6] Podpis ad-hoc i test pakietu...\n'
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

printf '\n[6/6] Tworzenie DMG...\n'
rm -rf dmg_stage
mkdir -p dmg_stage
cp -R "$APP_PATH" dmg_stage/
ln -s /Applications dmg_stage/Applications
if [[ -f README.md ]]; then
  cp README.md dmg_stage/README.txt
elif [[ -f docs/SECURITY_ACCESS.md ]]; then
  cp docs/SECURITY_ACCESS.md dmg_stage/README.txt
fi

hdiutil create \
  -volname "Ford UDS Studio ${VERSION}" \
  -srcfolder dmg_stage \
  -ov \
  -format UDZO \
  "$DMG_NAME"

rm -rf dmg_stage

printf '\n========================================\n'
printf 'GOTOWE:\n'
printf '  APP: %s\n' "$APP_PATH"
printf '  DMG: %s\n' "$(pwd)/$DMG_NAME"
printf '========================================\n\n'

printf 'Test uruchomienia z terminala:\n'
printf '  "%s/Contents/MacOS/%s"\n' "$APP_PATH" "$APP_NAME"
