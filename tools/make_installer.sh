#!/bin/bash
# Builds the self-contained app + the DMG installer.
#   dist/installer/ComfyUI MixMedia.app  - app with the whole project inside
#   dist/ComfyUI MixMedia.dmg            - drag-to-Applications installer
#
# The payload is a copy of the project (ComfyUI + .venv + nodes + workflows), without
# generated images, the unused insightface models and the API key.
#   --reuse  - keep the existing payload, rebuild only the launcher/plist and the DMG
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$PROJECT/dist/installer"
APP="$BUILD/ComfyUI MixMedia.app"
PAYLOAD="$APP/Contents/Resources/app"
DMG="$PROJECT/dist/ComfyUI MixMedia.dmg"

if [ "${1:-}" != "--reuse" ]; then
  echo "== payload"
  rm -rf "$BUILD"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$PAYLOAD"

  rsync -a \
    --exclude 'comfyui/output/' \
    --exclude 'comfyui/models/insightface/' \
    --exclude 'comfyui/custom_nodes/comfyui-faceswap/' \
    --exclude 'comfyui/user/default/comfy.settings.json' \
    --exclude 'dist/' \
    --exclude '.git/' \
    --exclude '.mixmedia_key' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude 'tools/e2e/.*' \
    "$PROJECT/" "$PAYLOAD/"
  mkdir -p "$PAYLOAD/comfyui/output"

  echo "== icon"
  ICONSET="$BUILD/icon.iconset"
  mkdir -p "$ICONSET"
  "$PROJECT/.venv/bin/python" "$PROJECT/tools/make_app_icon.py" "$ICONSET/icon_512x512.png"
  for spec in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" "64 icon_32x32@2x" \
              "128 icon_128x128" "256 icon_128x128@2x" "256 icon_256x256" \
              "512 icon_256x256@2x" "1024 icon_512x512@2x"; do
    size=${spec%% *}; name=${spec##* }
    sips -z "$size" "$size" "$ICONSET/icon_512x512.png" --out "$ICONSET/$name.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/app.icns"
  rm -rf "$ICONSET"
fi

echo "== launcher + plist"
cat > "$APP/Contents/MacOS/launcher" <<'SH'
#!/bin/bash
# ComfyUI MixMedia — всё внутри приложения: сервер, ноды, воркфлоу.
# Сервер поднимается через launchd, поэтому живёт после закрытия окна и не умирает
# вместе с процессом приложения.
CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="$CONTENTS/Resources/app"
URL="http://127.0.0.1:8188"
LOG="$HOME/Library/Logs/ComfyUI Mix Media.log"
LABEL="local.mixmedia.comfyui"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_N="$(id -u)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$HOME/Library/Application Support/ComfyUI Mix Media/Chrome"

up() { curl -s -o /dev/null --max-time 2 "$URL"; }

mkdir -p "$(dirname "$LOG")" "$(dirname "$PROFILE")" "$(dirname "$PLIST")"

# ключ MixMedia: в бандле, в домашней папке или из прошлой установки
key_ok=0
[ -s "$PROJECT/.mixmedia_key" ] && key_ok=1
[ -s "$HOME/.mixmedia_key" ] && key_ok=1
if [ $key_ok -eq 0 ]; then
  osascript -e 'display dialog "Ключ MixMedia не найден.\n\nПоложи его в ~/.mixmedia_key (одна строка), иначе ноды MixMedia будут ругаться. Остальной ComfyUI запустится." buttons {"Понятно"} default button 1 with icon caution' >/dev/null 2>&1 || true
fi

if ! up; then
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PROJECT/.venv/bin/python</string>
    <string>comfyui/main.py</string>
    <string>--listen</string><string>127.0.0.1</string>
    <string>--port</string><string>8188</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>RunAtLoad</key><false/>
  <key>KeepAlive</key><false/>
</dict>
</plist>
EOF
  if ! launchctl print "gui/$UID_N/$LABEL" >/dev/null 2>&1; then
    launchctl bootstrap "gui/$UID_N" "$PLIST" >/dev/null 2>&1 || launchctl load -w "$PLIST" >/dev/null 2>&1 || true
  fi
  launchctl kickstart -k "gui/$UID_N/$LABEL" >/dev/null 2>&1 || true

  for _ in $(seq 1 90); do
    up && break
    sleep 1
  done

  # если launchd недоступен — обычный фоновый запуск
  if ! up; then
    ( cd "$PROJECT" && nohup "$PROJECT/.venv/bin/python" comfyui/main.py \
        --listen 127.0.0.1 --port 8188 >>"$LOG" 2>&1 & )
    for _ in $(seq 1 90); do up && break; sleep 1; done
  fi
fi

if [ -x "$CHROME" ]; then
  "$CHROME" --app="$URL" --user-data-dir="$PROFILE" \
    --no-first-run --no-default-browser-check --disable-features=Translate \
    >/dev/null 2>&1 &
else
  open "$URL"
fi
SH
chmod +x "$APP/Contents/MacOS/launcher"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>ComfyUI MixMedia</string>
  <key>CFBundleDisplayName</key><string>ComfyUI MixMedia</string>
  <key>CFBundleIdentifier</key><string>local.mixmedia.comfyui.app</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>app</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>2.1</string>
  <key>CFBundleShortVersionString</key><string>2.1</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.graphics-design</string>
</dict>
</plist>
PLIST

echo "== app: $(du -sh "$APP" | cut -f1)"

echo "== dmg"
"$PROJECT/.venv/bin/python" "$PROJECT/tools/make_dmg.py" "$APP" "$DMG"
echo "== done: $DMG ($(du -sh "$DMG" | cut -f1))"
