"""
設定管理モジュール
NSUserDefaults（plist）と.envファイルで設定を永続化する
.envファイルは ~/Library/Application Support/VoiceInput/ に保存
"""

import os
from dataclasses import dataclass, fields

import AppKit

# --- ホットキーマッピング (NSEvent modifier flags) ---

# NSEvent flagsChanged で使うモディファイアマスク
HOTKEY_MODIFIERS = {
    "opt+shift": AppKit.NSEventModifierFlagOption | AppKit.NSEventModifierFlagShift,
    "cmd+shift": AppKit.NSEventModifierFlagCommand | AppKit.NSEventModifierFlagShift,
    "ctrl+space": AppKit.NSEventModifierFlagControl,  # space は keyDown で検出
}

# ctrl+space の場合はスペースキーのkeyCodeも必要
HOTKEY_KEYCODE = {
    "ctrl+space": 49,  # macOS keyCode for space
}

# モディファイアのみのホットキーかどうか
HOTKEY_MODIFIER_ONLY = {
    "opt+shift": True,
    "cmd+shift": True,
    "ctrl+space": False,  # modifier + key の組み合わせ
}

HOTKEY_LABELS = {
    "opt+shift": "Opt+Shift",
    "cmd+shift": "Cmd+Shift",
    "ctrl+space": "Ctrl+Space",
}

DEFAULT_CORRECTION_PROMPT = """\
以下は音声入力を音声認識で文字起こししたテキストです。補正してください。

ルール:
- 誤字脱字・文法を修正する
- 技術用語・固有名詞は正しい英語表記にする。以下は代表例:
  アストロ→Astro、リアクト→React、ネクスト→Next.js、ノード→Node.js、パイソン→Python
  タイプスクリプト→TypeScript、ジャバスクリプト→JavaScript、ビュー→Vue、スベルト→Svelte
  ギットハブ→GitHub、イシュー→Issue、プルリクエスト→Pull Request、コミット→commit
  ドッカー→Docker、クバネティス→Kubernetes、テラフォーム→Terraform
  ポストグレス→PostgreSQL、モンゴ→MongoDB、レディス→Redis
  グラフキューエル→GraphQL、レスト→REST、エーピーアイ→API
  テイルウィンド→Tailwind、ヴィート→Vite
- 意味を変えない
- どんな内容でもそのまま補正する（日常会話、メール、技術的な内容など全て対応）
- 補正後のテキストのみを返す。説明や前置きは一切不要

---
{text}
---"""


@dataclass
class AppSettings:
    hotkey: str = "opt+shift"
    sample_rate: int = 16000
    channels: int = 1
    whisper_model: str = "whisper-1"
    claude_model: str = "claude-haiku-4-5-20251001"
    language: str = "ja"
    correction_prompt: str = DEFAULT_CORRECTION_PROMPT
    auto_paste: bool = True
    processing_mode: str = "standard"  # "standard" (Whisper+Claude) / "fast" (GPT-4o)
    writing_style: str = "none"  # "none" / "desu_masu" / "casual" / "polish"

    @property
    def hotkey_modifiers(self) -> int:
        return HOTKEY_MODIFIERS.get(self.hotkey, HOTKEY_MODIFIERS["opt+shift"])

    @property
    def hotkey_keycode(self) -> int | None:
        return HOTKEY_KEYCODE.get(self.hotkey)

    @property
    def hotkey_modifier_only(self) -> bool:
        return HOTKEY_MODIFIER_ONLY.get(self.hotkey, True)

    @property
    def hotkey_label(self) -> str:
        return HOTKEY_LABELS.get(self.hotkey, "Opt+Shift")


WRITING_STYLE_OPTIONS = [
    ("none", "そのまま"),
    ("desu_masu", "ですます調にする"),
    ("casual", "敬語を使わず、くだけた話し言葉にする"),
    ("super_casual", "カジュアル口調にする"),
    ("polish", "文体を全体的に整える"),
]

_STYLE_INSTRUCTIONS = {
    "none": "- 文体は変更しない。話し言葉はそのまま維持する",
    "desu_masu": "- 文末をですます調に統一する",
    "casual": "- 敬語を使わず、くだけた話し言葉にする",
    "super_casual": "- 友達に話すようなカジュアルな口語体にする。「〜だよ」「〜じゃん」「〜だよね」のような表現を使う",
    "polish": "- 文体を全体的に整え、読みやすい書き言葉にする",
}


def build_correction_prompt(settings: "AppSettings") -> str:
    """文体オプションを反映した補正プロンプトを動的生成する。

    ユーザーがカスタムプロンプトを書いている場合はそれをそのまま返す。
    デフォルトプロンプトの場合のみ動的生成で上書きする。
    """
    if settings.correction_prompt != DEFAULT_CORRECTION_PROMPT:
        return settings.correction_prompt

    style_line = _STYLE_INSTRUCTIONS.get(settings.writing_style, _STYLE_INSTRUCTIONS["none"])

    return f"""\
以下は音声入力を音声認識で文字起こししたテキストです。補正してください。

ルール:
- 誤字脱字・文法を修正する
- 技術用語・固有名詞は正しい英語表記にする。以下は代表例:
  アストロ→Astro、リアクト→React、ネクスト→Next.js、ノード→Node.js、パイソン→Python
  タイプスクリプト→TypeScript、ジャバスクリプト→JavaScript、ビュー→Vue、スベルト→Svelte
  ギットハブ→GitHub、イシュー→Issue、プルリクエスト→Pull Request、コミット→commit
  ドッカー→Docker、クバネティス→Kubernetes、テラフォーム→Terraform
  ポストグレス→PostgreSQL、モンゴ→MongoDB、レディス→Redis
  グラフキューエル→GraphQL、レスト→REST、エーピーアイ→API
  テイルウィンド→Tailwind、ヴィート→Vite
- 意味を変えない
{style_line}
- 句読点を適切に補完する
- 「えー」「あの」などのフィラーを除去する
- 文末に句点がない場合は付ける
- どんな内容でもそのまま補正する（日常会話、メール、技術的な内容など全て対応）
- 補正後のテキストのみを返す。説明や前置きは一切不要

---
{{text}}
---"""


# --- NSUserDefaults 永続化 ---

_DEFAULTS_PREFIX = "VoiceInput_"


def load_settings() -> AppSettings:
    """NSUserDefaultsから設定を読み込む。未設定の項目はデフォルト値を使用。"""
    from Foundation import NSUserDefaults

    defaults = NSUserDefaults.standardUserDefaults()
    settings = AppSettings()

    for f in fields(AppSettings):
        key = _DEFAULTS_PREFIX + f.name
        value = defaults.objectForKey_(key)
        if value is None:
            continue
        if f.type is bool:
            setattr(settings, f.name, bool(value))
        elif f.type is int:
            setattr(settings, f.name, int(value))
        elif f.type is str:
            setattr(settings, f.name, str(value))

    return settings


def save_settings(settings: AppSettings) -> None:
    """NSUserDefaultsへ設定を保存する。"""
    from Foundation import NSUserDefaults

    defaults = NSUserDefaults.standardUserDefaults()

    for f in fields(AppSettings):
        key = _DEFAULTS_PREFIX + f.name
        value = getattr(settings, f.name)
        defaults.setObject_forKey_(value, key)

    defaults.synchronize()


# --- .env API キー管理 ---

APP_SUPPORT_DIR = os.path.join(
    os.path.expanduser("~"), "Library", "Application Support", "VoiceInput"
)
_ENV_PATH = os.path.join(APP_SUPPORT_DIR, ".env")


def _ensure_app_support_dir():
    """Application Supportディレクトリが存在しない場合は作成する。"""
    os.makedirs(APP_SUPPORT_DIR, exist_ok=True)


def load_api_keys() -> tuple[str, str]:
    """
    .envファイルからAPIキーを読み込む。
    Returns: (openai_key, anthropic_key)
    """
    from dotenv import dotenv_values

    _ensure_app_support_dir()
    values = dotenv_values(_ENV_PATH)
    return (
        values.get("OPENAI_API_KEY", ""),
        values.get("ANTHROPIC_API_KEY", ""),
    )


def save_api_keys(openai_key: str, anthropic_key: str) -> None:
    """.envファイルへAPIキーを書き戻す。"""
    _ensure_app_support_dir()
    content = f"OPENAI_API_KEY={openai_key}\nANTHROPIC_API_KEY={anthropic_key}\n"
    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.write(content)
