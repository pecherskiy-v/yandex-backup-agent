"""Иконка интеграции: облако со стрелкой вверх на синем поле.

Рисуется кодом, а не хранится картинкой, чтобы её можно было пересобрать в
любом размере — brands Home Assistant просит и 256, и 512. Логотип Яндекса
намеренно не используется: это чужой товарный знак.
"""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw

TOP = (74, 163, 255)
BOTTOM = (31, 111, 208)
CLOUD = (255, 255, 255)

S = 1024  # рисуем крупно и уменьшаем — так края выходят гладкими


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

    # стрелка вверх — знак того, что копии уезжают наружу
    draw.line((512, 760, 512, 400), fill=BOTTOM, width=76)
    draw.line((376, 520, 512, 384), fill=BOTTOM, width=76)
    draw.line((648, 520, 512, 384), fill=BOTTOM, width=76)
    draw.ellipse((474, 346, 550, 422), fill=BOTTOM)
    draw.ellipse((474, 722, 550, 798), fill=BOTTOM)

    return base.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, size in (("icon", 256), ("icon@2x", 512), ("logo", 256), ("logo@2x", 512)):
        render(size).save(f"{out}/{name}.png")
        print(f"{out}/{name}.png {size}×{size}")
