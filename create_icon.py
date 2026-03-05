#!/usr/bin/env python3
"""
マイクアイコン画像を生成して .icns に変換する
macOS標準ツール (iconutil) を使用
"""

import os
import subprocess
import struct
import zlib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICONSET_DIR = os.path.join(SCRIPT_DIR, "resources", "AppIcon.iconset")
ICNS_PATH = os.path.join(SCRIPT_DIR, "resources", "AppIcon.icns")


def create_png(size: int) -> bytes:
    """マイクアイコンのPNG画像をピュアPythonで生成する"""
    pixels = []
    center_x = size / 2
    center_y = size / 2

    # マイクの各パーツのサイズ比率
    mic_width = size * 0.22
    mic_height = size * 0.32
    mic_top = center_y - size * 0.18
    mic_bottom = mic_top + mic_height
    mic_round_r = mic_width

    stand_width = size * 0.04
    stand_top = mic_bottom + size * 0.02
    stand_bottom = stand_top + size * 0.12

    base_width = size * 0.18
    base_y = stand_bottom
    base_height = size * 0.03

    # 弧の設定
    arc_r_outer = size * 0.28
    arc_r_inner = size * 0.24
    arc_center_y = mic_top + mic_height * 0.5
    arc_thickness = size * 0.035

    bg_r = size * 0.42  # 背景の円の半径

    for y in range(size):
        row = []
        for x in range(size):
            dx = x - center_x
            dy = y - center_y
            dist_from_center = (dx * dx + dy * dy) ** 0.5

            r, g, b, a = 0, 0, 0, 0

            # 背景の丸い円（グラデーション）
            if dist_from_center <= bg_r:
                t = dist_from_center / bg_r
                # 紫〜青のグラデーション
                r = int(100 + (140 - 100) * t)
                g = int(60 + (80 - 60) * t)
                b = int(220 + (255 - 220) * t)
                a = 255
            elif dist_from_center <= bg_r + 1:
                # アンチエイリアス
                frac = bg_r + 1 - dist_from_center
                r, g, b = 140, 80, 255
                a = int(255 * frac)

            # マイク本体（丸みのある長方形）
            in_mic_body = False
            if abs(x - center_x) <= mic_width:
                if mic_top + mic_round_r <= y <= mic_bottom - mic_round_r:
                    in_mic_body = True
                elif mic_top <= y < mic_top + mic_round_r:
                    # 上部の丸み
                    dy2 = y - (mic_top + mic_round_r)
                    dx2 = abs(x - center_x)
                    if dx2 <= mic_width and (dx2 ** 2 + dy2 ** 2) <= mic_round_r ** 2:
                        in_mic_body = True
                elif mic_bottom - mic_round_r < y <= mic_bottom:
                    # 下部の丸み
                    dy2 = y - (mic_bottom - mic_round_r)
                    dx2 = abs(x - center_x)
                    if dx2 <= mic_width and (dx2 ** 2 + dy2 ** 2) <= mic_round_r ** 2:
                        in_mic_body = True

            if in_mic_body:
                r, g, b, a = 255, 255, 255, 255

            # マイクのスタンド（縦棒）
            if abs(x - center_x) <= stand_width and stand_top <= y <= stand_bottom:
                r, g, b, a = 255, 255, 255, 255

            # ベース（横棒）
            if abs(x - center_x) <= base_width and base_y <= y <= base_y + base_height:
                r, g, b, a = 255, 255, 255, 255

            # マイクを囲む弧（U字）
            dy_arc = y - arc_center_y
            dx_arc = x - center_x
            dist_arc = (dx_arc ** 2 + dy_arc ** 2) ** 0.5

            if y >= arc_center_y:  # 下半分のみ
                if arc_r_inner <= dist_arc <= arc_r_outer:
                    r, g, b, a = 255, 255, 255, 255
            else:
                # 上の端（左右の縦線）
                if arc_r_inner <= abs(dx_arc) <= arc_r_outer and arc_center_y - size * 0.08 <= y <= arc_center_y:
                    r, g, b, a = 255, 255, 255, 255

            row.append((r, g, b, a))
        pixels.append(row)

    return _encode_png(pixels, size, size)


def _encode_png(pixels, width, height):
    """ピクセルデータをPNGバイナリにエンコードする"""
    def make_chunk(chunk_type, data):
        chunk = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + chunk + crc

    # PNG signature
    signature = b"\x89PNG\r\n\x1a\n"

    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr = make_chunk(b"IHDR", ihdr_data)

    # IDAT
    raw_data = b""
    for row in pixels:
        raw_data += b"\x00"  # filter: none
        for r, g, b, a in row:
            raw_data += struct.pack("BBBB", r, g, b, a)
    compressed = zlib.compress(raw_data)
    idat = make_chunk(b"IDAT", compressed)

    # IEND
    iend = make_chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


def main():
    os.makedirs(ICONSET_DIR, exist_ok=True)

    # macOSが必要とする全サイズを生成
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    for size, filename in sizes:
        print(f"  生成中: {filename} ({size}x{size})")
        png_data = create_png(size)
        with open(os.path.join(ICONSET_DIR, filename), "wb") as f:
            f.write(png_data)

    # iconutil で .icns に変換
    print("  .icns に変換中...")
    subprocess.run(
        ["iconutil", "-c", "icns", ICONSET_DIR, "-o", ICNS_PATH],
        check=True,
    )

    # iconsetディレクトリをクリーンアップ
    import shutil
    shutil.rmtree(ICONSET_DIR)

    print(f"  完了: {ICNS_PATH}")


if __name__ == "__main__":
    main()
