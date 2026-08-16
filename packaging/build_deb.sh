#!/bin/bash
# 构建 dafeiyu-pet 的 .deb 安装包（在 packaging/ 目录下运行）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/src"
PKG_NAME="dafeiyu-pet"
VERSION="1.0.1"
ARCH="amd64"
DEB="$ROOT/${PKG_NAME}_${VERSION}_${ARCH}.deb"

echo "==> [1/3] 生成 256x256 图标"
python3 "$ROOT/packaging/make_icon.py"

echo "==> [2/3] 组装 deb 目录结构"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
D="$STAGE/debian"

install -d "$D/opt/dafeiyu-pet"
cp -r "$SRC/dist/dafeiyu-pet/." "$D/opt/dafeiyu-pet/"
chmod 755 "$D/opt/dafeiyu-pet/dafeiyu-pet"

install -d "$D/usr/bin"
ln -s /opt/dafeiyu-pet/dafeiyu-pet "$D/usr/bin/dafeiyu-pet"

install -d "$D/usr/share/applications"
install -m 644 "$ROOT/packaging/dafeiyu-pet.desktop" "$D/usr/share/applications/"

install -d "$D/usr/share/icons/hicolor/256x256/apps"
install -m 644 "$ROOT/dist/dafeiyu-pet.png" "$D/usr/share/icons/hicolor/256x256/apps/dafeiyu-pet.png"

install -d "$D/usr/share/doc/dafeiyu-pet"
cp "$SRC/LICENSE" "$D/usr/share/doc/dafeiyu-pet/copyright"

install -d "$D/DEBIAN"
install -m 644 "$ROOT/packaging/control" "$D/DEBIAN/control"

echo "==> [3/3] 构建 .deb"
dpkg-deb --build --root-owner-group "$D" "$DEB"
echo "==> 完成: $DEB ($(du -h "$DEB" | cut -f1))"
