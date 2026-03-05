#!/bin/bash
# VoiceInput.app ビルドスクリプト
set -e

cd "$(dirname "$0")"

echo "=== VoiceInput.app ビルド ==="

# portaudio (sounddeviceに必要)
echo "→ portaudio を確認中..."
brew install portaudio 2>/dev/null || echo "  portaudio は既にインストール済み"

# Python仮想環境
if [ ! -d venv ]; then
    echo "→ Python仮想環境を作成中..."
    python3.11 -m venv venv
fi
source venv/bin/activate

# 依存パッケージ
echo "→ パッケージをインストール中..."
pip install -r requirements.txt

# アイコン生成
if [ ! -f resources/AppIcon.icns ]; then
    echo "→ アプリアイコンを生成中..."
    python3 create_icon.py
fi

# 既存ビルドをクリーン
rm -rf build dist

# Application Supportディレクトリ作成
APP_SUPPORT="$HOME/Library/Application Support/VoiceInput"
mkdir -p "$APP_SUPPORT"

# プロジェクト内の.envがあればApplication Supportにコピー
if [ -f .env ] && [ ! -f "$APP_SUPPORT/.env" ]; then
    echo "→ .envをApplication Supportにコピー中..."
    cp .env "$APP_SUPPORT/.env"
fi

# py2appビルド
echo "→ py2appでビルド中..."
python setup.py py2app

# コード署名
echo "→ コード署名中..."
codesign --force --deep --sign - dist/VoiceInput.app

# Applicationsにインストール
echo "→ /Applications にインストール中..."
pkill -f "VoiceInput.app" 2>/dev/null || true
sleep 1
rm -rf /Applications/VoiceInput.app
cp -r dist/VoiceInput.app /Applications/

# リビルド後のアクセシビリティ権限を自動設定
# tccutil で古いエントリをリセットし、open時にmacOSが再登録できるようにする
echo "→ アクセシビリティ権限をリセット中..."
tccutil reset Accessibility com.voiceinput.app 2>/dev/null || true
tccutil reset Microphone com.voiceinput.app 2>/dev/null || true

echo ""
echo "=== ビルド＆インストール完了 ==="
echo ""
echo "※初回起動時にアクセシビリティとマイクの許可ダイアログが表示されます"
echo "  許可すればリビルドするまで再度表示されません"
echo "起動: open /Applications/VoiceInput.app"
