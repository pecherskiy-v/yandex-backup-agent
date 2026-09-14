"""Иконка интеграции: облако с буквой «Я» и стрелкой вверх.

Буква нужна, чтобы с одного взгляда было видно, чьё это облако — в списке
мест хранения копий их может быть несколько. Фирменное начертание Яндекса
при этом не копируется: буква набрана обычным жирным гротеском на своём
поле, а не белым по красному квадрату, который является товарным знаком.

Рисуется кодом, а не хранится картинкой, чтобы её можно было пересобрать в
любом размере — brands Home Assistant просит и 256, и 512.
"""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw, ImageFont

TOP = (74, 163, 255)
BOTTOM = (31, 111, 208)
CLOUD = (255, 255, 255)

S = 1024  # рисуем крупно и уменьшаем — так края выходят гладкими

#: Жирный гротеск с кириллицей. Первый попавшийся из списка, иначе буквы
#: не будет вовсе — молча рисовать облако без «Я» хуже, чем упасть.
FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise SystemExit("не нашёл жирный шрифт с кириллицей — см. FONTS")


def render(size: int) -> Image.Image:
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # поле с вертикальным градиентом
    field = Image.new("RGBA", (S, S))
    px = field.load()
    for y in range(S):
        k = y / (S - 1)
        colour = tuple(round(a + (b - a) * k) for a, b in zip(TOP, BOTTOM))
        for x in range(S):
            px[x, y] = (*colour, 255)

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((32, 32, S - 32, S - 32), radius=224, fill=255)
    base.paste(field, (0, 0), mask)

    draw = ImageDraw.Draw(base)

    # облако — три круга и перемычка под ними
    draw.ellipse((280, 300, 616, 636), fill=CLOUD)
    draw.ellipse((176, 420, 432, 676), fill=CLOUD)
    draw.ellipse((536, 428, 792, 684), fill=CLOUD)
    draw.rounded_rectangle((240, 520, 744, 700), radius=90, fill=CLOUD)

    # буква — чьё это облако
    font = _font(300)
    draw.text((470, 545), "Я", font=font, fill=BOTTOM, anchor="mm")

    # стрелка вверх — копии уезжают наружу; сбоку, чтобы не спорить с буквой
    draw.line((690, 560, 690, 370), fill=BOTTOM, width=58)
    draw.line((606, 454, 690, 370), fill=BOTTOM, width=58)
    draw.line((774, 454, 690, 370), fill=BOTTOM, width=58)
    draw.ellipse((661, 341, 719, 399), fill=BOTTOM)
    draw.ellipse((661, 531, 719, 589), fill=BOTTOM)

    return base.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, size in (("icon", 256), ("icon@2x", 512), ("logo", 256), ("logo@2x", 512)):
        render(size).save(f"{out}/{name}.png")
        print(f"{out}/{name}.png {size}×{size}")
