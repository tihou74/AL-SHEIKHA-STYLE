#!/usr/bin/env python3
"""توليد نسخ شعار بمقاسات الويب من الأصل، بخلفيّة شفّافة.

السبب: الشعار الكامل 899×1260 وحجمه 269 كيلوبايت، ويُعرض بعرض 190 بكسل
كأقصى حدّ. فتحميل 269 كيلوبايت لعرض 190 بكسل هدرٌ على باقة الجوّال.

التصغير يشمل قناة الشفافيّة لا الألوان وحدها — وإلا ظهرت حدود مسنّنة.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from jpeg_tools import Jpeg, write_png, to_hex  # noqa: E402

SRC = 'brand/al-sheikha-style-logo-899x1600.jpg'
GOLD = (0xBA, 0x9D, 0x66)


def build_rgba(src, gold=GOLD):
    """يحوّل الفنّ الذهبي على أبيض إلى RGBA بلون موحّد + شفافيّة محسوبة."""
    img = Jpeg(src)
    rgb = img.rgb()
    w, h = img.width, img.height
    denom = 255.0 - gold[2]          # القناة الزرقاء: أكبر فرق عن الأبيض
    rgba = bytearray(w * h * 4)
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            v = rgb[(y * w + x) * 3 + 2]
            a = (255.0 - v) / denom
            a = 0.0 if a < 0 else (1.0 if a > 1 else a)
            av = int(a * 255 + 0.5)
            if av < 8:
                av = 0
            o = (y * w + x) * 4
            rgba[o], rgba[o + 1], rgba[o + 2], rgba[o + 3] = gold[0], gold[1], gold[2], av
            if av > 16:
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
    pad = 4
    minx = max(0, minx - pad); miny = max(0, miny - pad)
    maxx = min(w - 1, maxx + pad); maxy = min(h - 1, maxy + pad)
    nw, nh = maxx - minx + 1, maxy - miny + 1
    crop = bytearray(nw * nh * 4)
    for y in range(nh):
        s = ((miny + y) * w + minx) * 4
        crop[y * nw * 4:(y + 1) * nw * 4] = rgba[s:s + nw * 4]
    return crop, nw, nh


def downscale_rgba(rgba, w, h, target_w):
    """متوسّط صناديق على القنوات الأربع — الشفافيّة تُصغَّر مع اللون."""
    if w <= target_w:
        return rgba, w, h
    f = w / float(target_w)
    nw = target_w
    nh = max(1, int(round(h / f)))
    out = bytearray(nw * nh * 4)
    for ny in range(nh):
        y0, y1 = int(ny * h / nh), max(int(ny * h / nh) + 1, int((ny + 1) * h / nh))
        for nx in range(nw):
            x0, x1 = int(nx * w / nw), max(int(nx * w / nw) + 1, int((nx + 1) * w / nw))
            sa = sr = sg = sb = cnt = 0
            for yy in range(y0, y1):
                base = yy * w * 4
                for xx in range(x0, x1):
                    o = base + xx * 4
                    a = rgba[o + 3]
                    sr += rgba[o] * a; sg += rgba[o + 1] * a; sb += rgba[o + 2] * a
                    sa += a; cnt += 1
            o = (ny * nw + nx) * 4
            if sa:
                out[o] = min(255, sr // sa)
                out[o + 1] = min(255, sg // sa)
                out[o + 2] = min(255, sb // sa)
            else:
                out[o] = GOLD[0]; out[o + 1] = GOLD[1]; out[o + 2] = GOLD[2]
            out[o + 3] = sa // cnt
    return out, nw, nh


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC
    widths = [int(a) for a in sys.argv[2:]] or [450, 220]
    rgba, w, h = build_rgba(src)
    print(f'الأصل بعد الاقتطاع: {w}×{h}  لون {to_hex(*GOLD)}')
    for tw in widths:
        small, nw, nh = downscale_rgba(rgba, w, h, tw)
        out = f'brand/logo-gold-{nw}.png'
        size = write_png(out, nw, nh, small)
        print(f'  {out}  {nw}×{nh}  {size/1024:.0f} KB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
