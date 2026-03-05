"""
設定ウィンドウ（AppKit ネイティブUI）
2カラムレイアウト: 左=設定項目、右=補正プロンプト
"""

import AppKit
import objc
from Foundation import NSMakeRect, NSObject

from config import (
    HOTKEY_LABELS,
    WRITING_STYLE_OPTIONS,
    AppSettings,
    load_api_keys,
    load_settings,
)

# --- 定数 ---
WIN_WIDTH = 820
WIN_HEIGHT = 580
LEFT_WIDTH = 400
RIGHT_X = LEFT_WIDTH + 15
RIGHT_WIDTH = WIN_WIDTH - RIGHT_X - 10
LABEL_WIDTH = 120
FIELD_X = 135
LEFT_FIELD_WIDTH = LEFT_WIDTH - FIELD_X - 10
PADDING = 10

PROCESSING_MODE_OPTIONS = [
    ("standard", "標準（Whisper + Claude）"),
    ("fast", "高速（GPT-4o）"),
]

LANGUAGE_OPTIONS = [
    ("ja", "日本語"),
    ("en", "English"),
    ("zh", "中文"),
    ("ko", "한국어"),
    ("es", "Español"),
    ("fr", "Français"),
    ("de", "Deutsch"),
]

CLAUDE_MODEL_OPTIONS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250514",
    "claude-opus-4-0-20250514",
]

SAMPLE_RATE_OPTIONS = [16000, 44100, 48000]
CHANNEL_OPTIONS = [1, 2]


def _make_label(text: str, frame: tuple) -> AppKit.NSTextField:
    label = AppKit.NSTextField.alloc().initWithFrame_(NSMakeRect(*frame))
    label.setStringValue_(text)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setAlignment_(AppKit.NSTextAlignmentRight)
    label.setFont_(AppKit.NSFont.systemFontOfSize_(13))
    return label


def _make_popup(items: list[str], frame: tuple) -> AppKit.NSPopUpButton:
    popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(*frame), False
    )
    for item in items:
        popup.addItemWithTitle_(item)
    return popup


class PreferencesWindowController(NSObject):
    """設定ウィンドウを管理するコントローラ"""

    _on_save = None

    @classmethod
    def create(cls, on_save=None):
        controller = cls.alloc().init()
        controller._on_save = on_save
        controller._build_window()
        return controller

    def _build_window(self):
        style = (
            AppKit.NSTitledWindowMask
            | AppKit.NSClosableWindowMask
            | AppKit.NSMiniaturizableWindowMask
        )
        self._window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(200, 200, WIN_WIDTH, WIN_HEIGHT),
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("VoiceInput 設定")
        self._window.setReleasedWhenClosed_(False)

        content = self._window.contentView()

        # ========== 左カラム: 設定項目 ==========
        y = WIN_HEIGHT - 45

        # --- APIキー ---
        y = self._add_section_header(content, "APIキー", y, PADDING, LEFT_WIDTH)

        content.addSubview_(_make_label("OpenAI:", (PADDING, y, LABEL_WIDTH, 24)))
        self._openai_field = AppKit.NSSecureTextField.alloc().initWithFrame_(
            NSMakeRect(FIELD_X, y, LEFT_FIELD_WIDTH, 24)
        )
        content.addSubview_(self._openai_field)
        y -= 30

        content.addSubview_(_make_label("Anthropic:", (PADDING, y, LABEL_WIDTH, 24)))
        self._anthropic_field = AppKit.NSSecureTextField.alloc().initWithFrame_(
            NSMakeRect(FIELD_X, y, LEFT_FIELD_WIDTH, 24)
        )
        content.addSubview_(self._anthropic_field)
        y -= 36

        # --- ホットキー ---
        y = self._add_section_header(content, "ホットキー", y, PADDING, LEFT_WIDTH)

        content.addSubview_(_make_label("ホットキー:", (PADDING, y, LABEL_WIDTH, 26)))
        hotkey_labels = list(HOTKEY_LABELS.values())
        self._hotkey_popup = _make_popup(hotkey_labels, (FIELD_X, y, 160, 26))
        content.addSubview_(self._hotkey_popup)
        y -= 36

        # --- 処理モード ---
        y = self._add_section_header(content, "処理モード", y, PADDING, LEFT_WIDTH)

        content.addSubview_(_make_label("モード:", (PADDING, y, LABEL_WIDTH, 26)))
        self._mode_popup = _make_popup(
            [label for _, label in PROCESSING_MODE_OPTIONS], (FIELD_X, y, LEFT_FIELD_WIDTH, 26)
        )
        content.addSubview_(self._mode_popup)
        y -= 36

        # --- AIモデル ---
        y = self._add_section_header(content, "AIモデル", y, PADDING, LEFT_WIDTH)

        content.addSubview_(_make_label("Whisper:", (PADDING, y, LABEL_WIDTH, 24)))
        self._whisper_field = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(FIELD_X, y, LEFT_FIELD_WIDTH, 24)
        )
        content.addSubview_(self._whisper_field)
        y -= 30

        content.addSubview_(_make_label("Claude:", (PADDING, y, LABEL_WIDTH, 26)))
        self._claude_popup = _make_popup(CLAUDE_MODEL_OPTIONS, (FIELD_X, y, LEFT_FIELD_WIDTH, 26))
        content.addSubview_(self._claude_popup)
        y -= 36

        # --- 言語・オーディオ（コンパクトに） ---
        y = self._add_section_header(content, "言語・オーディオ", y, PADDING, LEFT_WIDTH)

        content.addSubview_(_make_label("言語:", (PADDING, y, LABEL_WIDTH, 26)))
        lang_labels = [f"{code} - {name}" for code, name in LANGUAGE_OPTIONS]
        self._lang_popup = _make_popup(lang_labels, (FIELD_X, y, 160, 26))
        content.addSubview_(self._lang_popup)
        y -= 30

        content.addSubview_(_make_label("サンプルレート:", (PADDING, y, LABEL_WIDTH, 26)))
        sr_labels = [str(r) for r in SAMPLE_RATE_OPTIONS]
        self._sr_popup = _make_popup(sr_labels, (FIELD_X, y, 100, 26))

        # チャンネルを同じ行に
        ch_label = _make_label("Ch:", (FIELD_X + 110, y, 30, 26))
        ch_label.setAlignment_(AppKit.NSTextAlignmentRight)
        content.addSubview_(ch_label)
        ch_labels = [str(c) for c in CHANNEL_OPTIONS]
        self._ch_popup = _make_popup(ch_labels, (FIELD_X + 148, y, 60, 26))
        content.addSubview_(self._sr_popup)
        content.addSubview_(self._ch_popup)
        y -= 34

        # --- 自動ペースト ---
        self._auto_paste_cb = AppKit.NSButton.alloc().initWithFrame_(
            NSMakeRect(FIELD_X, y, 200, 22)
        )
        self._auto_paste_cb.setButtonType_(AppKit.NSSwitchButton)
        self._auto_paste_cb.setTitle_("自動ペースト")
        content.addSubview_(self._auto_paste_cb)
        y -= 36

        # --- 文体オプション ---
        y = self._add_section_header(content, "文体オプション", y, PADDING, LEFT_WIDTH)

        content.addSubview_(_make_label("文体:", (PADDING, y, LABEL_WIDTH, 26)))
        style_labels = [label for _, label in WRITING_STYLE_OPTIONS]
        self._writing_style_popup = _make_popup(style_labels, (FIELD_X, y, LEFT_FIELD_WIDTH, 26))
        content.addSubview_(self._writing_style_popup)

        # ========== 右カラム: 補正プロンプト ==========
        prompt_top = WIN_HEIGHT - 45
        self._add_section_header(content, "補正プロンプト", prompt_top, RIGHT_X, RIGHT_WIDTH)
        prompt_top -= 28

        prompt_bottom = 50  # ボタンの上
        prompt_height = prompt_top - prompt_bottom

        scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            NSMakeRect(RIGHT_X, prompt_bottom, RIGHT_WIDTH, prompt_height)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(AppKit.NSBezelBorder)

        self._prompt_tv = AppKit.NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, RIGHT_WIDTH - 17, prompt_height)
        )
        self._prompt_tv.setMinSize_((0, prompt_height))
        self._prompt_tv.setMaxSize_((1e7, 1e7))
        self._prompt_tv.setVerticallyResizable_(True)
        self._prompt_tv.setHorizontallyResizable_(False)
        self._prompt_tv.textContainer().setWidthTracksTextView_(True)
        self._prompt_tv.setFont_(AppKit.NSFont.systemFontOfSize_(12))

        scroll.setDocumentView_(self._prompt_tv)
        content.addSubview_(scroll)

        # ========== ボタン（右下） ==========
        btn_y = 12

        cancel_btn = AppKit.NSButton.alloc().initWithFrame_(
            NSMakeRect(WIN_WIDTH - 200, btn_y, 80, 32)
        )
        cancel_btn.setTitle_("キャンセル")
        cancel_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        cancel_btn.setTarget_(self)
        cancel_btn.setAction_(objc.selector(self.cancel_, signature=b"v@:@"))
        content.addSubview_(cancel_btn)

        save_btn = AppKit.NSButton.alloc().initWithFrame_(
            NSMakeRect(WIN_WIDTH - 110, btn_y, 80, 32)
        )
        save_btn.setTitle_("保存")
        save_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        save_btn.setTarget_(self)
        save_btn.setAction_(objc.selector(self.save_, signature=b"v@:@"))
        save_btn.setKeyEquivalent_("\r")
        content.addSubview_(save_btn)

        # 現在の設定を読み込んでUIに反映
        self._load_current()

    def _add_section_header(self, view, title: str, y: int, x: int = PADDING, width: int = 0) -> int:
        if width == 0:
            width = LEFT_WIDTH
        label = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(x, y, width, 18)
        )
        label.setStringValue_(title)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
        label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        view.addSubview_(label)
        return y - 28

    def _load_current(self):
        """現在の設定値をUIコントロールに反映する"""
        settings = load_settings()
        openai_key, anthropic_key = load_api_keys()

        self._openai_field.setStringValue_(openai_key)
        self._anthropic_field.setStringValue_(anthropic_key)

        hotkey_keys = list(HOTKEY_LABELS.keys())
        if settings.hotkey in hotkey_keys:
            self._hotkey_popup.selectItemAtIndex_(hotkey_keys.index(settings.hotkey))

        mode_keys = [key for key, _ in PROCESSING_MODE_OPTIONS]
        if settings.processing_mode in mode_keys:
            self._mode_popup.selectItemAtIndex_(mode_keys.index(settings.processing_mode))

        self._whisper_field.setStringValue_(settings.whisper_model)

        if settings.claude_model in CLAUDE_MODEL_OPTIONS:
            self._claude_popup.selectItemAtIndex_(
                CLAUDE_MODEL_OPTIONS.index(settings.claude_model)
            )

        lang_codes = [code for code, _ in LANGUAGE_OPTIONS]
        if settings.language in lang_codes:
            self._lang_popup.selectItemAtIndex_(lang_codes.index(settings.language))

        if settings.sample_rate in SAMPLE_RATE_OPTIONS:
            self._sr_popup.selectItemAtIndex_(
                SAMPLE_RATE_OPTIONS.index(settings.sample_rate)
            )

        if settings.channels in CHANNEL_OPTIONS:
            self._ch_popup.selectItemAtIndex_(
                CHANNEL_OPTIONS.index(settings.channels)
            )

        self._prompt_tv.setString_(settings.correction_prompt)

        self._auto_paste_cb.setState_(
            AppKit.NSOnState if settings.auto_paste else AppKit.NSOffState
        )

        style_keys = [key for key, _ in WRITING_STYLE_OPTIONS]
        if settings.writing_style in style_keys:
            self._writing_style_popup.selectItemAtIndex_(style_keys.index(settings.writing_style))

    def _gather_settings(self) -> tuple[AppSettings, str, str]:
        """UIコントロールから設定値を収集する"""
        hotkey_keys = list(HOTKEY_LABELS.keys())
        lang_codes = [code for code, _ in LANGUAGE_OPTIONS]
        mode_keys = [key for key, _ in PROCESSING_MODE_OPTIONS]
        style_keys = [key for key, _ in WRITING_STYLE_OPTIONS]

        settings = AppSettings(
            hotkey=hotkey_keys[self._hotkey_popup.indexOfSelectedItem()],
            sample_rate=SAMPLE_RATE_OPTIONS[self._sr_popup.indexOfSelectedItem()],
            channels=CHANNEL_OPTIONS[self._ch_popup.indexOfSelectedItem()],
            whisper_model=str(self._whisper_field.stringValue()),
            claude_model=CLAUDE_MODEL_OPTIONS[self._claude_popup.indexOfSelectedItem()],
            language=lang_codes[self._lang_popup.indexOfSelectedItem()],
            correction_prompt=str(self._prompt_tv.string()),
            auto_paste=self._auto_paste_cb.state() == AppKit.NSOnState,
            processing_mode=mode_keys[self._mode_popup.indexOfSelectedItem()],
            writing_style=style_keys[self._writing_style_popup.indexOfSelectedItem()],
        )

        openai_key = str(self._openai_field.stringValue())
        anthropic_key = str(self._anthropic_field.stringValue())

        return settings, openai_key, anthropic_key

    def _ensure_edit_menu(self):
        """LSUIElementアプリにEditメニューを追加（Cmd+V等を有効化）"""
        mainMenu = AppKit.NSApp.mainMenu()
        if mainMenu is None:
            mainMenu = AppKit.NSMenu.alloc().init()
            AppKit.NSApp.setMainMenu_(mainMenu)

        # 既にEditメニューがあればスキップ
        if mainMenu.itemWithTitle_("Edit") is not None:
            return

        editMenu = AppKit.NSMenu.alloc().initWithTitle_("Edit")
        for title, action, key in [
            ("Cut", "cut:", "x"),
            ("Copy", "copy:", "c"),
            ("Paste", "paste:", "v"),
            ("Select All", "selectAll:", "a"),
            ("Undo", "undo:", "z"),
            ("Redo", "redo:", "Z"),
        ]:
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, action, key
            )
            editMenu.addItem_(item)

        editMenuItem = AppKit.NSMenuItem.alloc().init()
        editMenuItem.setTitle_("Edit")
        editMenuItem.setSubmenu_(editMenu)
        mainMenu.addItem_(editMenuItem)

    def show(self):
        """ウィンドウを表示して前面に持ってくる"""
        self._ensure_edit_menu()
        self._load_current()
        self._window.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def _do_save(self):
        settings, openai_key, anthropic_key = self._gather_settings()
        if self._on_save:
            self._on_save(settings, openai_key, anthropic_key)
        self._window.orderOut_(None)

    @objc.python_method
    def _do_cancel(self):
        self._window.orderOut_(None)

    def save_(self, sender):
        self._do_save()

    def cancel_(self, sender):
        self._do_cancel()
