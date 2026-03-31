"""アイコン生成スクリプト

assets/ ディレクトリに icon.png と icon.ico を生成する。
ビルド前に一度実行しておく。

使い方:
    cd Filtflow/assets
    python create_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICON_SIZE: int = 64
OUTPUT_DIR: Path = Path(__file__).parent


def _draw_icon(size: int) -> Image.Image:
    """Filtflow アイコン画像を生成する。

    暗背景に緑の円、中央に "F" の文字。
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 外円（ダークグレー背景）
    draw.ellipse([1, 1, size - 1, size - 1], fill=(28, 28, 28, 255))

    # 内円（グリーン）
    m = size // 6
    draw.ellipse([m, m, size - m, size - m], fill=(0, 180, 70, 255))

    # "F" 文字
    try:
        font: ImageFont.ImageFont | ImageFont.FreeTypeFont = ImageFont.truetype(
            "arial.ttf", int(size * 0.45)
        )
    except OSError:
        font = ImageFont.load_default()

    text = "F"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2 - bbox[0]
    y = (size - text_h) // 2 - bbox[1]
    draw.text((x, y), text, fill=(255, 255, 255, 230), font=font)

    return img


def main() -> None:
    sizes = [16, 24, 32, 48, 64]
    base = _draw_icon(ICON_SIZE)

    # icon.png（64x64）
    png_path = OUTPUT_DIR / "icon.png"
    base.save(str(png_path), format="PNG")
    print(f"生成: {png_path}")

    # icon.ico（複数サイズを含む）
    ico_images = [_draw_icon(s) for s in sizes]
    ico_path = OUTPUT_DIR / "icon.ico"
    ico_images[0].save(
        str(ico_path),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=ico_images[1:],
    )
    print(f"生成: {ico_path}")


if __name__ == "__main__":
    main()
