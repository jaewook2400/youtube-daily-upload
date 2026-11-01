#!/bin/bash
# venv 생성 + 의존성 설치 + launchd 등록
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.jaewook.youtube-upload"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

cd "$DIR"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

[ -f config.json ] || cp config.example.json config.json
mkdir -p logs
chmod +x run.sh uploader.py auth.py

sed "s#__DIR__#$DIR#g" "$LABEL.plist" > "$PLIST_DEST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"

echo "설치 완료. 매일 09:00에 실행됩니다."
[ -f token.json ] || echo "다음 단계: client_secret.json 을 넣고 '.venv/bin/python auth.py' 로 로그인하세요."
