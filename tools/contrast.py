#!/usr/bin/env python3
"""حساب نسبة تباين WCAG بين لونين — لئلّا يُقترح لون نصّ لا يُقرأ.

الحدود: 4.5:1 للنصّ العادي، 3:1 للنصّ الكبير (18pt+ أو 14pt عريض)
و3:1 لحدود عناصر الإدخال والأيقونات الدالّة.
"""
import sys
from itertools import combinations


def lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color):
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def verdict(r):
    if r >= 7:
        return 'AAA ✓ (نصّ عادي وكبير)'
    if r >= 4.5:
        return 'AA ✓ (نصّ عادي)'
    if r >= 3:
        return 'AA للنصّ الكبير فقط / حدود — ✗ للنصّ العادي'
    return '✗ لا يُقرأ — لا يُستعمل للنصّ'


def main(argv):
    colors = [c if c.startswith('#') else '#' + c for c in argv[1:]]
    if len(colors) < 2:
        print(__doc__)
        return 2
    if len(colors) == 2:
        pairs = [(colors[0], colors[1])]
    else:
        pairs = list(combinations(colors, 2))
    width = max(len(f'{a} على {b}') for a, b in pairs)
    for a, b in pairs:
        r = ratio(a, b)
        print(f'{a} على {b}'.ljust(width) + f'  {r:5.2f}:1   {verdict(r)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
