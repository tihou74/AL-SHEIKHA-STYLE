#!/usr/bin/env python3
"""تحقّق بصري من شفافيّة الشعار: يركّبه على خلفيّة داكنة وأخرى عاجيّة.

إن ظهر مربّع أبيض حول الشعار على الجانب الداكن فالاستخراج فاشل.
هذا الفحص بصري بالقصد: الرقم لا يُثبت غياب الهالة، والعين تُثبته.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from jpeg_tools import Jpeg, write_png  # noqa: E402

GOLD = (0xBA, 0x9D, 0x66)
DARK = (0x1B, 0x1A, 0x19)
CREAM = (0xFA, 0xF8, 0xF4)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else 'brand/al-sheikha-style-logo-899x1600.jpg'
    out = sys.argv[2] if len(sys.argv) > 2 else 'verify-transparency.png'
    img = Jpeg(src)
    rgb = img.rgb()
    w, h = img.width, img.height

    denom = 255.0 - GOLD[2]          # القناة الزرقاء: أكبر فرق عن الأبيض
    W = w * 2
    rgba = bytearray(W * h * 4)
    for y in range(h):
        for x in range(w):
            v = rgb[(y * w + x) * 3 + 2]
            a = (255.0 - v) / denom
            a = 0.0 if a < 0 else (1.0 if a > 1 else a)
            if a * 255 < 8:
                a = 0.0
            for panel, bg in ((0, DARK), (1, CREAM)):
                o = (y * W + panel * w + x) * 4
                rgba[o] = int(GOLD[0] * a + bg[0] * (1 - a))
                rgba[o + 1] = int(GOLD[1] * a + bg[1] * (1 - a))
                rgba[o + 2] = int(GOLD[2] * a + bg[2] * (1 - a))
                rgba[o + 3] = 255
    size = write_png(out, W, h, rgba)
    print(f'كُتب: {out}  {W}×{h}  {size:,} bytes')
    print('اليسار: على داكن #1B1A19   اليمين: على عاجي #FAF8F4')


if __name__ == '__main__':
    main()
