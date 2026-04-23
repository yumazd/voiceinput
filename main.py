#!/usr/bin/env python3
"""
VoiceInput - macOS音声入力アプリ
ホットキーで録音 → Whisper APIで文字起こし → Claude APIで補正 → 自動ペースト
"""

import os
import sys

# py2app バンドル内ではデフォルトエンコーディングが ascii になるため UTF-8 を強制
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("LANG", "ja_JP.UTF-8")
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import base64
import io
import shutil
import threading
import time
import wave

import AppKit
import anthropic
import numpy as np
import openai
import rumps
import sounddevice as sd
from dotenv import load_dotenv

from config import (
    APP_SUPPORT_DIR,
    build_correction_prompt,
    load_api_keys,
    load_settings,
    save_api_keys,
    save_settings,
)

# ログ設定 — py2appバンドル内では APP_SUPPORT_DIR が想定外のパスになる場合があるため
# expanduser で明示的にホームから構築する
_LOG_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "VoiceInput")
os.makedirs(_LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(_LOG_DIR, "voiceinput.log")


def _log(msg: str):
    """ログファイルとstderrに書き出す"""
    import datetime
    import sys
    line = f"{datetime.datetime.now().isoformat()} {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception as e:
        print(f"LOG WRITE ERROR: {e} path={LOG_PATH}", file=sys.stderr)
    print(line, end="", file=sys.stderr)

# .app から起動すると PATH に /usr/local/bin 等が含まれないため補完する
_EXTRA_PATHS = ["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin"]
for p in _EXTRA_PATHS:
    if p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = p + ":" + os.environ.get("PATH", "")

# pydub が ffmpeg を見つけられるよう明示的に設定
_ffmpeg = shutil.which("ffmpeg")
_ffprobe = shutil.which("ffprobe")
if _ffmpeg:
    from pydub import AudioSegment
    AudioSegment.converter = _ffmpeg
if _ffprobe:
    from pydub import AudioSegment
    AudioSegment.ffprobe = _ffprobe

# Application Support の .env を読み込む
load_dotenv(os.path.join(APP_SUPPORT_DIR, ".env"))


_log("=== モジュール初期化完了 ===")


def _check_accessibility(prompt: bool = False) -> bool:
    """アクセシビリティ権限を確認する。prompt=Trueの場合のみシステム設定ダイアログを表示"""
    from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions

    if prompt:
        options = {AppKit.NSString.stringWithString_("AXTrustedCheckOptionPrompt"): True}
        trusted = AXIsProcessTrustedWithOptions(options)
    else:
        trusted = AXIsProcessTrusted()
    _log(f"アクセシビリティ権限: {trusted}")
    return trusted


_WHISPER_HALLUCINATIONS = {
    "ご視聴ありがとうございました",
    "ご視聴ありがとうございます",
    "チャンネル登録お願いします",
    "チャンネル登録よろしくお願いします",
    "おやすみなさい",
    "ありがとうございました",
    "Thanks for watching!",
    "Thank you for watching!",
}

_WHISPER_PROMPT_HINT = (
    "Python, JavaScript, TypeScript, React, Next.js, Node.js, API, "
    "Astro, Astro Islands, Vite, MDX, Starlight, "
    "GitHub, Docker, Kubernetes, AWS, SQL, PostgreSQL, MongoDB, "
    "Redis, GraphQL, REST, HTTP, JSON, HTML, CSS, Tailwind, "
    "Vue, Svelte, Rust, Go, Swift, Terraform, CI/CD, "
    "npm, yarn, pip, brew, git, commit, push, pull request, "
    "Issue, issue, branch, merge, deploy, "
    "コンポーネント、デプロイ、リファクタリング、マイグレーション、"
    "エンドポイント、ミドルウェア、インスタンス、コンテナ、イシュー"
)


class VoiceInputApp(rumps.App):
    def __init__(self):
        _log("VoiceInputApp.__init__ 開始")
        _check_accessibility(prompt=True)
        super().__init__("🎙️", quit_button="終了")
        self.recording = False
        self.audio_frames = []
        self.stream = None
        self.prefs_controller = None
        self._hotkey_monitor = None
        self._whisper_model = None  # faster-whisper モデルキャッシュ

        # 設定読み込み
        self.settings = load_settings()
        openai_key, anthropic_key = load_api_keys()
        self.openai_client = openai.OpenAI(api_key=openai_key or os.getenv("OPENAI_API_KEY", ""))
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_key or os.getenv("ANTHROPIC_API_KEY", ""))

        self.menu = [
            rumps.MenuItem(
                f"録音開始 ({self.settings.hotkey_label})",
                callback=self.toggle_recording,
            ),
            None,
            rumps.MenuItem("状態: 待機中"),
            None,
            rumps.MenuItem("設定…", callback=self.open_preferences),
        ]

        # グローバルホットキーリスナー開始 (NSEvent)
        _log(f"ホットキー設定: {self.settings.hotkey}")
        self._start_hotkey_listener()

        # Mac起動直後はアクセシビリティやイベント基盤が未準備の場合があるため
        # ランループ開始後に遅延再登録する
        self._delayed_reinit_timer = rumps.Timer(self._delayed_reinit, 5)
        self._delayed_reinit_timer.start()

        # ローカルモードならバックグラウンドでモデルをプリロード
        if self.settings.processing_mode == "local":
            threading.Thread(target=self._preload_whisper_model, daemon=True).start()

        _log("VoiceInputApp.__init__ 完了")

    # --- 起動時の遅延再初期化 ---

    def _delayed_reinit(self, timer):
        """Mac起動直後にホットキーモニターが機能しない問題への対処。
        ランループ開始後に一度だけホットキーリスナーを再登録する。"""
        timer.stop()
        _log("遅延再初期化: ホットキーリスナー再登録")
        self._restart_hotkey_listener()
        # アクセシビリティ権限を再確認
        _check_accessibility(prompt=False)

    # --- ホットキー処理 (NSEvent ベース) ---

    def _start_hotkey_listener(self):
        if self.settings.hotkey_modifier_only:
            # Opt+Shift, Cmd+Shift: モディファイアキーのみ → flagsChanged を監視
            mask = AppKit.NSEventMaskFlagsChanged
        else:
            # Ctrl+Space: モディファイア+キー → keyDown を監視
            mask = AppKit.NSEventMaskKeyDown

        self._hotkey_monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, self._handle_hotkey_event
        )
        _log(f"ホットキーモニター開始 (mask={mask})")

    def _stop_hotkey_listener(self):
        if self._hotkey_monitor:
            AppKit.NSEvent.removeMonitor_(self._hotkey_monitor)
            self._hotkey_monitor = None

    def _restart_hotkey_listener(self):
        self._stop_hotkey_listener()
        self._start_hotkey_listener()

    def _handle_hotkey_event(self, event):
        try:
            required_mods = self.settings.hotkey_modifiers
            # デバイス非依存のモディファイアのみ比較
            device_independent = AppKit.NSEventModifierFlagShift | AppKit.NSEventModifierFlagControl | AppKit.NSEventModifierFlagOption | AppKit.NSEventModifierFlagCommand
            current_mods = event.modifierFlags() & device_independent

            if self.settings.hotkey_modifier_only:
                # モディファイアのみホットキー: 完全一致で発動
                if current_mods == required_mods:
                    _log(f"ホットキー発動! mods={current_mods:#x}")
                    self.toggle_recording(None)
            else:
                # モディファイア+キー: モディファイアが含まれ＋キーが一致で発動
                keycode = self.settings.hotkey_keycode
                if (current_mods & required_mods) == required_mods and event.keyCode() == keycode:
                    _log(f"ホットキー発動! mods={current_mods:#x} keyCode={event.keyCode()}")
                    self.toggle_recording(None)
        except Exception as e:
            _log(f"ホットキーエラー: {e}")
            self._show_notification("エラー", str(e)[:100])
            self._reset_state()

    # --- 設定ウィンドウ ---

    def open_preferences(self, sender):
        from preferences import PreferencesWindowController

        if self.prefs_controller is None:
            self.prefs_controller = PreferencesWindowController.create(
                on_save=self._on_preferences_saved
            )
        self.prefs_controller.show()

    def _on_preferences_saved(self, new_settings, openai_key, anthropic_key):
        old_settings = self.settings
        self.settings = new_settings

        # 設定を永続化
        save_settings(new_settings)
        save_api_keys(openai_key, anthropic_key)

        # APIキー変更 → クライアント再生成
        self.openai_client = openai.OpenAI(api_key=openai_key)
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_key)

        # ホットキー変更 → リスナー再登録
        if old_settings.hotkey != new_settings.hotkey:
            self._restart_hotkey_listener()

        # メニューのホットキー表示を更新
        self._update_menu_title(f"録音開始 ({new_settings.hotkey_label})")

        # ローカルモードに変更されたらモデルをプリロード
        if new_settings.processing_mode == "local" and self._whisper_model is None:
            threading.Thread(target=self._preload_whisper_model, daemon=True).start()

    # --- 録音制御 ---

    def toggle_recording(self, sender):
        _log(f"toggle_recording 呼び出し: recording={self.recording}")
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        _log("_start_recording 開始")
        self.audio_frames = []
        last_error = None
        for attempt in range(3):
            try:
                self.stream = sd.InputStream(
                    samplerate=self.settings.sample_rate,
                    channels=self.settings.channels,
                    dtype="int16",
                    callback=self._audio_callback,
                )
                self.stream.start()
                last_error = None
                break
            except Exception as e:
                last_error = e
                self.stream = None
                if attempt < 2:
                    time.sleep(1)
        if last_error:
            self._show_notification(
                "マイクエラー",
                "マイクを開けません。システム設定 > プライバシー > マイクでVoiceInputを許可してください",
            )
            print(f"マイクエラー: {last_error}")
            return

        self.recording = True
        self.title = "⏺️"
        self._update_status("録音中...")
        self._update_menu_title(f"録音停止 ({self.settings.hotkey_label})")

    def _stop_recording(self):
        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        self.title = "⏳"
        self._update_status("処理中...")
        self._update_menu_title(f"録音開始 ({self.settings.hotkey_label})")

        threading.Thread(target=self._process_audio, daemon=True).start()

    def _audio_callback(self, indata, frames, time_info, status):
        if self.recording:
            self.audio_frames.append(indata.copy())

    # --- 音声処理パイプライン ---

    def _process_audio(self):
        try:
            _log("_process_audio 開始")
            if not self.audio_frames:
                _log("音声フレームが空")
                self._show_notification("エラー", "音声が録音されていません")
                self._reset_state()
                return

            _log(f"音声フレーム数: {len(self.audio_frames)}")
            audio_data = np.concatenate(self.audio_frames, axis=0)
            _log(f"音声データ形状: {audio_data.shape}, 長さ: {len(audio_data)/self.settings.sample_rate:.1f}秒")

            wav_buffer = self._to_wav(audio_data)
            _log("WAV変換完了")

            mp3_buffer = self._to_mp3(wav_buffer)
            _log(f"MP3変換完了, サイズ: {mp3_buffer.getbuffer().nbytes} bytes")

            if self.settings.processing_mode == "fast":
                self._update_status("GPT-4o処理中...")
                _log("GPT-4oモードで処理開始")
                result = self._process_with_gpt4o(mp3_buffer)
            elif self.settings.processing_mode == "local":
                if self._whisper_model is None:
                    self._update_status("モデル準備中（初回のみ）...")
                else:
                    self._update_status("ローカル文字起こし中...")
                _log("faster-whisperで文字起こし開始")
                raw_text = self._transcribe_local(mp3_buffer)
                _log(f"ローカル文字起こし結果: {raw_text[:100] if raw_text else '(空)'}")
                if not raw_text or raw_text in _WHISPER_HALLUCINATIONS:
                    if raw_text:
                        _log(f"ハルシネーション検出（無視）: {raw_text}")
                    raw_text = ""
                if not raw_text:
                    self._show_notification("エラー", "文字起こしに失敗しました")
                    self._reset_state()
                    return
                self._update_status("AI補正中...")
                _log("Claude補正開始")
                result = self._correct_text(raw_text)
            else:
                self._update_status("文字起こし中...")
                _log("Whisperで文字起こし開始")
                raw_text = self._transcribe(mp3_buffer)
                _log(f"文字起こし結果: {raw_text[:100] if raw_text else '(空)'}")
                if not raw_text or raw_text in _WHISPER_HALLUCINATIONS:
                    if raw_text:
                        _log(f"ハルシネーション検出（無視）: {raw_text}")
                    raw_text = ""
                if not raw_text:
                    self._show_notification("エラー", "文字起こしに失敗しました")
                    self._reset_state()
                    return
                self._update_status("AI補正中...")
                _log("Claude補正開始")
                result = self._correct_text(raw_text)

            _log(f"処理結果: {result[:100] if result else '(空)'}")

            if not result:
                self._show_notification("エラー", "処理に失敗しました")
                self._reset_state()
                return

            if self.settings.auto_paste:
                self._paste_text(result)
            else:
                self._copy_to_clipboard(result)

            self._show_notification("完了", result[:80])

        except Exception as e:
            import traceback
            _log(f"処理エラー: {e}\n{traceback.format_exc()}")
            self._show_notification("エラー", str(e)[:100])
        finally:
            self._reset_state()

    def _to_wav(self, audio_data: np.ndarray) -> io.BytesIO:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.settings.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.settings.sample_rate)
            wf.writeframes(audio_data.tobytes())
        buf.seek(0)
        return buf

    def _to_mp3(self, wav_buffer: io.BytesIO) -> io.BytesIO:
        from pydub import AudioSegment

        audio = AudioSegment.from_wav(wav_buffer)
        mp3_buf = io.BytesIO()
        audio.export(mp3_buf, format="mp3", bitrate="64k")
        mp3_buf.seek(0)
        return mp3_buf

    def _transcribe(self, mp3_buffer: io.BytesIO) -> str:
        mp3_buffer.name = "recording.mp3"
        response = self.openai_client.audio.transcriptions.create(
            model=self.settings.whisper_model,
            file=mp3_buffer,
            language=self.settings.language,
            prompt=_WHISPER_PROMPT_HINT,
        )
        return response.text.strip()

    def _preload_whisper_model(self):
        """バックグラウンドでfaster-whisperモデルをロードしておく"""
        try:
            _log("faster-whisper プリロード開始")
            WhisperModel = self._import_whisper_model()
            if self._whisper_model is None:
                model_dir = os.path.join(
                    os.path.expanduser("~"),
                    "Library", "Application Support", "VoiceInput", "models",
                )
                os.makedirs(model_dir, exist_ok=True)
                self._whisper_model = WhisperModel(
                    "small",
                    device="cpu",
                    compute_type="int8",
                    download_root=model_dir,
                )
            _log("faster-whisper プリロード完了")
        except Exception as e:
            _log(f"faster-whisper プリロード失敗: {e}")

    @staticmethod
    def _import_whisper_model():
        """faster-whisperのWhisperModelをimportして返す。

        py2appの静的解析を回避するためimportlibを使用。
        バンドル内にfaster-whisperは同梱しないため、venvのsite-packagesを探索する。
        """
        import importlib

        try:
            mod = importlib.import_module("faster_whisper")
            return mod.WhisperModel
        except ImportError:
            pass

        # py2appバンドル内: venvのsite-packagesをパスに追加して再試行
        import glob as _glob

        venv_patterns = [
            os.path.join(os.path.expanduser("~"), "localhost", "VoiceInputApp",
                         "venv", "lib", "python*", "site-packages"),
        ]
        for pattern in venv_patterns:
            for sp in _glob.glob(pattern):
                if sp not in sys.path:
                    sys.path.insert(0, sp)

        try:
            mod = importlib.import_module("faster_whisper")
            return mod.WhisperModel
        except ImportError:
            raise RuntimeError(
                "faster-whisper が未インストールです。\n"
                "pip install faster-whisper を実行してください。"
            )

    def _transcribe_local(self, mp3_buffer: io.BytesIO) -> str:
        """faster-whisper (small モデル) でローカル文字起こし"""
        import tempfile

        WhisperModel = self._import_whisper_model()

        if self._whisper_model is None:
            model_dir = os.path.join(
                os.path.expanduser("~"),
                "Library", "Application Support", "VoiceInput", "models",
            )
            os.makedirs(model_dir, exist_ok=True)
            _log(f"faster-whisper モデルロード開始 (download_root={model_dir})")
            self._whisper_model = WhisperModel(
                "small",
                device="cpu",
                compute_type="int8",
                download_root=model_dir,
            )
            _log("faster-whisper モデルロード完了")

        # faster-whisper はファイルパスが必要なため tempfile に書き出す
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(mp3_buffer.read())
            tmp_path = tmp.name

        try:
            segments, info = self._whisper_model.transcribe(
                tmp_path,
                language=self.settings.language,
                initial_prompt=_WHISPER_PROMPT_HINT,
                no_speech_threshold=0.5,
            )
            text = "".join(segment.text for segment in segments)
        finally:
            os.unlink(tmp_path)

        return text.strip()

    def _correct_text(self, raw_text: str) -> str:
        prompt_template = build_correction_prompt(self.settings)
        prompt_text = prompt_template.format(text=raw_text)
        message = self.anthropic_client.messages.create(
            model=self.settings.claude_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt_text}],
        )
        return message.content[0].text.strip()

    def _process_with_gpt4o(self, mp3_buffer: io.BytesIO) -> str:
        """GPT-4oに音声を直接送り、文字起こし+補正を1回で行う"""
        audio_b64 = base64.b64encode(mp3_buffer.read()).decode()
        prompt_template = build_correction_prompt(self.settings)
        prompt = prompt_template.replace(
            "\n---\n{text}\n---", ""
        ).strip()
        prompt += (
            "\n\n添付の音声を文字起こしし、上記ルールで補正したテキストのみを返してください。"
        )

        response = self.openai_client.chat.completions.create(
            model="gpt-4o-audio-preview",
            modalities=["text"],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_b64, "format": "mp3"},
                        },
                    ],
                }
            ],
        )
        return response.choices[0].message.content.strip()

    # --- ペースト ---

    def _copy_to_clipboard(self, text: str):
        import subprocess

        process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        process.communicate(text.encode("utf-8"))

    def _paste_text(self, text: str):
        import Quartz

        self._copy_to_clipboard(text)

        trusted = _check_accessibility(prompt=False)
        _log(f"ペースト試行: accessibility={trusted}")

        if not trusted:
            self._show_notification(
                "Cmd+Vでペースト",
                "クリップボードにコピー済み。アクセシビリティ権限を付与すると自動ペーストが有効になります"
            )
            return

        time.sleep(0.2)
        # Cmd+V を CGEvent で送信 (keyCode 9 = 'v')
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateCombinedSessionState)
        cmd_down = Quartz.CGEventCreateKeyboardEvent(src, 9, True)
        Quartz.CGEventSetFlags(cmd_down, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_down)
        time.sleep(0.05)
        cmd_up = Quartz.CGEventCreateKeyboardEvent(src, 9, False)
        Quartz.CGEventSetFlags(cmd_up, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_up)
        _log("ペースト実行 (CGEvent)")

    # --- UI更新ヘルパー ---

    def _update_status(self, status: str):
        for item in self.menu.values():
            if isinstance(item, rumps.MenuItem) and item.title.startswith("状態:"):
                item.title = f"状態: {status}"
                break

    def _update_menu_title(self, title: str):
        for item in self.menu.values():
            if isinstance(item, rumps.MenuItem) and (
                "Opt+Shift" in item.title
                or "Cmd+Shift" in item.title
                or "Ctrl+Space" in item.title
                or "録音" in item.title
            ):
                item.title = title
                break

    def _show_notification(self, title: str, message: str):
        rumps.notification("VoiceInput", title, message)

    def _reset_state(self):
        _log("_reset_state 呼び出し")
        self.title = "🎙️"
        self._update_status("待機中")


def main():
    _log("=== main() 開始 ===")
    openai_key, anthropic_key = load_api_keys()
    openai_key = openai_key or os.getenv("OPENAI_API_KEY", "")
    anthropic_key = anthropic_key or os.getenv("ANTHROPIC_API_KEY", "")
    _log(f"APIキー: OpenAI={'設定済' if openai_key else '未設定'}, Anthropic={'設定済' if anthropic_key else '未設定'}")

    if not openai_key:
        print("エラー: OPENAI_API_KEY が設定されていません。設定ウィンドウからAPIキーを設定してください。")
        return
    if not anthropic_key:
        print("エラー: ANTHROPIC_API_KEY が設定されていません。設定ウィンドウからAPIキーを設定してください。")
        return

    app = VoiceInputApp()
    app.run()


if __name__ == "__main__":
    main()
