#!/bin/sh
# Generate the launcher for this folder's location and link it into the app menu.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cat > "$DIR/my-custom-setting.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=My Custom Setting
Comment=Battery, charging and touchscreen settings
Exec=$DIR/my_custom_setting.py
Icon=$DIR/icon.svg
Terminal=false
Categories=Utility;System;Settings;
StartupWMClass=io.github.keayvan.MyCustomSetting
DESKTOP
mkdir -p ~/.local/share/applications
ln -sf "$DIR/my-custom-setting.desktop" ~/.local/share/applications/my-custom-setting.desktop
echo "Installed. Search for \"My Custom Setting\" in the app menu."
