"""アイコン生成スクリプト

assets/ ディレクトリに icon.png と icon.ico を生成する。
ビルド前に一度実行しておく。

使い方:
    cd Filtflow/assets
    python create_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BASE_SIZE: int = 72
OUTPUT_DIR: Path = Path(__file__).parent

BG_COLOR = (12, 12, 17, 255)  # #0c0c11
STROKE_COLOR_RGB = (194, 189, 180)  # #c2bdb4

WAVES = [
    # (y_offset, opacity, stroke_width) — 72px 基準
    (-6, 0.20, 1.5),  # 背面
    (0, 0.55, 1.8),  # 中間
    (+6, 1.00, 2.0),  # 前面
]

AMPLITUDE = 22  # 制御点距離 (72px 基準)
MARGIN = 3  # 左右マージン (72px 基準)
CORNER_RATIO = 0.222  # 角丸半径 ≈ サイズの 22%


def _bezier_point(
    p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], t: float
) -> tuple[float, float]:
    """二次ベジェ曲線上の点を返す。"""
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
    return (x, y)


def _quadratic_bezier_points(
    p0: tuple[float, float],
    cp: tuple[float, float],
    p1: tuple[float, float],
    steps: int = 64,
) -> list[tuple[float, float]]:
    """二次ベジェ曲線のポイント列を生成する。"""
    return [_bezier_point(p0, cp, p1, t / steps) for t in range(steps + 1)]


def _draw_icon(size: int) -> Image.Image:
    """Filtflow アイコン画像を生成する。"""
    # 高解像度で描画してアンチエイリアスを得る
    ss = 4  # supersampling factor
    hi = size * ss
    hi_scale = hi / BASE_SIZE

    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 角丸正方形の背景
    r = round(BASE_SIZE * CORNER_RATIO * hi_scale)
    draw.rounded_rectangle([0, 0, hi - 1, hi - 1], radius=r, fill=BG_COLOR)

    # 波形を描画
    margin = MARGIN * hi_scale
    x_start = margin
    x_mid = hi / 2
    x_end = hi - margin
    y_center = hi / 2
    amp = AMPLITUDE * hi_scale

    for y_off_base, opacity, sw_base in WAVES:
        y_off = y_off_base * hi_scale
        sw = sw_base * hi_scale
        y = y_center + y_off

        # SVG: M x_start,y  Q x_q1,y-amp  x_mid,y  Q x_q2,y+amp  x_end,y
        p0 = (x_start, y)
        cp1 = (x_start + (x_mid - x_start) / 2, y - amp)
        p1 = (x_mid, y)
        cp2 = (x_mid + (x_end - x_mid) / 2, y + amp)
        p2 = (x_end, y)

        points = _quadratic_bezier_points(p0, cp1, p1, steps=80)
        points += _quadratic_bezier_points(p1, cp2, p2, steps=80)[1:]

        color = (*STROKE_COLOR_RGB, round(255 * opacity))
        width = max(1, round(sw))
        draw.line(points, fill=color, width=width)

    # ダウンサンプル
    img = img.resize((size, size), Image.LANCZOS)
    return img


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 72]
    base = _draw_icon(64)

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
