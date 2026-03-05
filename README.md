# VoiceInput

macOS用の音声入力アプリ。ホットキーで録音し、AIが文字起こし・補正して自動ペーストします。

## 仕組み

1. ホットキー（デフォルト: Opt+Shift）で録音開始/停止
2. Whisper APIで音声を文字起こし
3. Claude APIでテキストを補正（誤字修正、技術用語変換、フィラー除去）
4. クリップボードにコピーし、アクティブなアプリに自動ペースト

### 処理モード

| モード | 処理フロー | 特徴 |
|--------|-----------|------|
| 標準 | Whisper → Claude | 高精度 |
| 高速 | GPT-4o（一括処理） | 低遅延 |

### 文体オプション

補正時の文体を選択できます。

| オプション | 動作 |
|-----------|------|
| そのまま（デフォルト） | 文体を変更しない |
| ですます調にする | 文末をですます調に統一 |
| 話し言葉にする | 自然な話し言葉に変換 |
| 文体を全体的に整える | 読みやすい書き言葉に整形 |

## セットアップ

### 必要なもの

- macOS 13+
- Python 3.11
- Homebrew
- OpenAI APIキー
- Anthropic APIキー

### インストール

```bash
git clone https://github.com/yumazd/voiceinput.git
cd voiceinput
```

APIキーを設定:

```bash
mkdir -p ~/Library/Application\ Support/VoiceInput
cat > ~/Library/Application\ Support/VoiceInput/.env << 'EOF'
OPENAI_API_KEY=your-openai-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
EOF
```

ビルド&インストール:

```bash
./build.sh
```

### 起動

```bash
open /Applications/VoiceInput.app
```

初回起動時にアクセシビリティとマイクの許可を求められます。許可してください。

## 設定

メニューバーのマイクアイコン → 「設定…」から変更できます。

- **ホットキー** — Opt+Shift / Cmd+Shift / Ctrl+Space
- **処理モード** — 標準 / 高速
- **文体オプション** — そのまま / ですます調 / 話し言葉 / 文体を整える
- **AIモデル** — Whisperモデル、Claudeモデル
- **言語** — 日本語、English、中文 など
- **補正プロンプト** — カスタマイズ可能

## ライセンス

MIT
