"""
py2app ビルド設定
usage: python setup.py py2app
"""

from setuptools import setup

APP = ["main.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "resources/AppIcon.icns",
    "packages": [
        "rumps",
        "sounddevice",
        "numpy",
        "openai",
        "anthropic",
        "pynput",
        "dotenv",
        "pydub",
        "objc",
        "AppKit",
        "Foundation",
        "ApplicationServices",
        "Quartz",
    ],
    "includes": [
        "config",
        "preferences",
    ],
    "plist": {
        "CFBundleName": "VoiceInput",
        "CFBundleDisplayName": "VoiceInput",
        "CFBundleIdentifier": "com.voiceinput.app",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "LSUIElement": False,
        "NSMicrophoneUsageDescription": "音声入力のためにマイクを使用します",
        "NSAppleEventsUsageDescription": "テキストのペーストのためにアクセシビリティを使用します",
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
