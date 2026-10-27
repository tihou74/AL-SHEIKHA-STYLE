#!/usr/bin/env python3
"""فكّ JPEG أساسي وقياس ألوانه وإخراج PNG بخلفيّة شفّافة — ببايثون المجرّد.

سبب كتابة هذا بدل استخدام مكتبة: في هذه البيئة لا pip ولا npm (الاثنان محجوبان)،
ولا ImageMagick، والمتصفّح المتاح بلا إنترنت ويتعطّل محلّياً. فالطريق الوحيد
للقياس الحقيقي (لا التخمين) هو فكّ الصورة هنا.

يدعم: SOF0 (baseline)، ثلاث مكوّنات، أي نسب عيّنة، وDRI.
لا يدعم: progressive (SOF2) — ويقول ذلك صريحاً بدل أن يُخرج ألواناً خطأ.

الأوامر:
  measure <jpg>                        قياس الألوان الغالبة
  transparent <jpg> <out.png> [hex]    شعار بخلفيّة شفّافة بلون موحّد
  info <jpg>                           معلومات الصورة
"""
import math
import struct
import sys
import zlib
from array import array
from pathlib import Path

ZIGZAG = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
]

# معاملات IDCT محسوبة مرّة واحدة (لا داخل الحلقة)
_COS = [[math.cos((2 * x + 1) * u * math.pi / 16) * (math.sqrt(0.5) if u == 0 else 1.0)
         for u in range(8)] for x in range(8)]


class JpegError(Exception):
    pass


class BitReader:
    """قارئ بتّات من مقطع المسح، يتعامل مع حشو 0xFF00 ويتوقّف عند العلامات."""

    __slots__ = ('data', 'pos', 'bits', 'nbits')

    def __init__(self, data, pos):
        self.data = data
        self.pos = pos
        self.bits = 0
        self.nbits = 0

    def _fill(self):
        d = self.data
        b = d[self.pos]
        self.pos += 1
        if b == 0xFF:
            nxt = d[self.pos] if self.pos < len(d) else 0
            if nxt == 0x00:
                self.pos += 1
            else:
                # علامة: نُعيد أصفاراً بدل أن نقرأها بتّات
                b = 0
                self.pos -= 1
        self.bits = (self.bits << 8) | b
        self.nbits += 8

    def bit(self):
        if self.nbits == 0:
            self._fill()
        self.nbits -= 1
        return (self.bits >> self.nbits) & 1

    def receive(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v

    def align(self):
        self.bits = 0
        self.nbits = 0


def extend(v, n):
    """تمديد الإشارة حسب معيار JPEG."""
    return v - (1 << n) + 1 if n and v < (1 << (n - 1)) else v


def build_huffman(counts, symbols):
    """يبني خريطة (طول, رمز) -> قيمة."""
    table = {}
    code = 0
    k = 0
    for length in range(1, 17):
        for _ in range(counts[length - 1]):
            table[(length, code)] = symbols[k]
            k += 1
            code += 1
        code <<= 1
    return table


def huff_decode(reader, table):
    code = 0
    for length in range(1, 17):
        code = (code << 1) | reader.bit()
        v = table.get((length, code))
        if v is not None:
            return v
    raise JpegError('رمز هوفمان غير معروف')


def idct_block(coeffs, qt, out):
    """يحسب 64 بكسل من معاملات الكتلة. يختصر الكتل المسطّحة (AC كلها صفر)."""
    flat = True
    for i in range(1, 64):
        if coeffs[i]:
            flat = False
            break
    if flat:
        v = coeffs[0] * qt[0] / 8.0 + 128.0
        v = 0 if v < 0 else (255 if v > 255 else int(v + 0.5))
        for i in range(64):
            out[i] = v
        return

    # فكّ الضغط إلى ترتيب طبيعي
    blk = [0.0] * 64
    for i in range(64):
        c = coeffs[i]
        if c:
            blk[ZIGZAG[i]] = c * qt[i]

    # IDCT منفصل: صفوف ثم أعمدة
    tmp = [0.0] * 64
    cos = _COS
    for r in range(8):
        base = r * 8
        row = blk[base:base + 8]
        if not any(row[1:]):
            # صف بترددات صفر: القيمة ثابتة عبره = 0.5 * F0 * cos[x][0] = F0*√0.5*0.5
            v = row[0] * math.sqrt(0.5) * 0.5
            for x in range(8):
                tmp[base + x] = v
            continue
        for x in range(8):
            cx = cos[x]
            s = 0.0
            for u in range(8):
                cu = row[u]
                if cu:
                    s += cu * cx[u]
            tmp[base + x] = s * 0.5
    for c in range(8):
        col = [tmp[r * 8 + c] for r in range(8)]
        for y in range(8):
            cy = cos[y]
            s = 0.0
            for v in range(8):
                cv = col[v]
                if cv:
                    s += cv * cy[v]
            val = s * 0.5 + 128.0
            out[y * 8 + c] = 0 if val < 0 else (255 if val > 255 else int(val + 0.5))


class Jpeg:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        self.qt = {}
        self.huff_dc = {}
        self.huff_ac = {}
        self.comps = []
        self.width = self.height = 0
        self.restart_interval = 0
        self.planes = {}
        self._parse()

    def _parse(self):
        d = self.data
        if d[0:2] != b'\xff\xd8':
            raise JpegError('ليس ملف JPEG')
        i = 2
        sos_at = None
        while i + 3 < len(d):
            if d[i] != 0xFF:
                i += 1
                continue
            m = d[i + 1]
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            if m == 0xD9:
                break
            ln = struct.unpack('>H', d[i + 2:i + 4])[0]
            seg = d[i + 4:i + 2 + ln]
            if m == 0xDB:
                p = 0
                while p < len(seg):
                    pq = seg[p] >> 4
                    tq = seg[p] & 15
                    p += 1
                    if pq:
                        vals = [struct.unpack('>H', seg[p + 2 * k:p + 2 * k + 2])[0] for k in range(64)]
                        p += 128
                    else:
                        vals = list(seg[p:p + 64])
                        p += 64
                    self.qt[tq] = vals
            elif m == 0xC4:
                p = 0
                while p < len(seg):
                    tc = seg[p] >> 4
                    th = seg[p] & 15
                    counts = list(seg[p + 1:p + 17])
                    total = sum(counts)
                    symbols = list(seg[p + 17:p + 17 + total])
                    tbl = build_huffman(counts, symbols)
                    (self.huff_dc if tc == 0 else self.huff_ac)[th] = tbl
                    p += 17 + total
            elif m == 0xC0 or m == 0xC1:
                self.height, self.width = struct.unpack('>HH', seg[1:5])
                nc = seg[5]
                for c in range(nc):
                    cid, samp, tq = seg[6 + c * 3], seg[7 + c * 3], seg[8 + c * 3]
                    self.comps.append({'id': cid, 'h': samp >> 4, 'v': samp & 15, 'q': tq})
            elif m == 0xC2:
                raise JpegError('الصورة progressive (SOF2) وهذا الفاكّ لا يدعمها')
            elif m == 0xDD:
                self.restart_interval = struct.unpack('>H', seg[0:2])[0]
            elif m == 0xDA:
                ns = seg[0]
                for k in range(ns):
                    cs, tt = seg[1 + k * 2], seg[2 + k * 2]
                    for comp in self.comps:
                        if comp['id'] == cs:
                            comp['dc'] = tt >> 4
                            comp['ac'] = tt & 15
                sos_at = i + 2 + ln
                break
            i += 2 + ln
        if sos_at is None:
            raise JpegError('لم يوجد مقطع مسح (SOS)')
        self._decode_scan(sos_at)

    def _decode_scan(self, pos):
        comps = self.comps
        hmax = max(c['h'] for c in comps)
        vmax = max(c['v'] for c in comps)
        mcux = (self.width + 8 * hmax - 1) // (8 * hmax)
        mcuy = (self.height + 8 * vmax - 1) // (8 * vmax)
        self.hmax, self.vmax, self.mcux, self.mcuy = hmax, vmax, mcux, mcuy

        for c in comps:
            c['pw'] = mcux * c['h'] * 8
            c['ph'] = mcuy * c['v'] * 8
            c['plane'] = array('B', bytes(c['pw'] * c['ph']))
            c['pred'] = 0

        reader = BitReader(self.data, pos)
        coeffs = [0] * 64
        out = [0] * 64
        mcu_count = 0
        total_mcus = mcux * mcuy

        for my in range(mcuy):
            for mx in range(mcux):
                if self.restart_interval and mcu_count and mcu_count % self.restart_interval == 0:
                    reader.align()
                    # تخطّي علامة إعادة التشغيل
                    while reader.pos + 1 < len(self.data):
                        if self.data[reader.pos] == 0xFF and 0xD0 <= self.data[reader.pos + 1] <= 0xD7:
                            reader.pos += 2
                            break
                        reader.pos += 1
                    for c in comps:
                        c['pred'] = 0
                mcu_count += 1

                for c in comps:
                    qt = self.qt[c['q']]
                    dctab = self.huff_dc[c['dc']]
                    actab = self.huff_ac[c['ac']]
                    for by in range(c['v']):
                        for bx in range(c['h']):
                            for k in range(64):
                                coeffs[k] = 0
                            t = huff_decode(reader, dctab)
                            diff = extend(reader.receive(t), t) if t else 0
                            c['pred'] += diff
                            coeffs[0] = c['pred']
                            k = 1
                            while k < 64:
                                rs = huff_decode(reader, actab)
                                r, s = rs >> 4, rs & 15
                                if s == 0:
                                    if r == 15:
                                        k += 16
                                        continue
                                    break
                                k += r
                                if k > 63:
                                    break
                                coeffs[k] = extend(reader.receive(s), s)
                                k += 1
                            idct_block(coeffs, qt, out)
                            px = (mx * c['h'] + bx) * 8
                            py = (my * c['v'] + by) * 8
                            plane = c['plane']
                            pw = c['pw']
                            for yy in range(8):
                                row = (py + yy) * pw + px
                                plane[row:row + 8] = array('B', out[yy * 8:yy * 8 + 8])
            if my % 20 == 0:
                sys.stderr.write(f'\r  فكّ الصورة: {100 * (my + 1) // mcuy}%  ')
                sys.stderr.flush()
        sys.stderr.write('\r' + ' ' * 40 + '\r')

    def rgb(self):
        """ارجع bytearray بطول w*h*3."""
        w, h = self.width, self.height
        comps = self.comps
        hmax, vmax = self.hmax, self.vmax
        out = bytearray(w * h * 3)
        if len(comps) == 1:
            c = comps[0]
            plane, pw = c['plane'], c['pw']
            for y in range(h):
                for x in range(w):
                    v = plane[y * pw + x]
                    o = (y * w + x) * 3
                    out[o] = out[o + 1] = out[o + 2] = v
            return out
        cy, cb, cr = comps[0], comps[1], comps[2]
        yp, ybw = cy['plane'], cy['pw']
        bp, bbw = cb['plane'], cb['pw']
        rp, rbw = cr['plane'], cr['pw']
        sx_b, sy_b = hmax // cb['h'], vmax // cb['v']
        sx_r, sy_r = hmax // cr['h'], vmax // cr['v']
        for y in range(h):
            yrow = y * ybw
            brow = (y // sy_b) * bbw
            rrow = (y // sy_r) * rbw
            orow = y * w * 3
            for x in range(w):
                Y = yp[yrow + x]
                Cb = bp[brow + x // sx_b] - 128
                Cr = rp[rrow + x // sx_r] - 128
                r = Y + 1.402 * Cr
                g = Y - 0.344136 * Cb - 0.714136 * Cr
                b = Y + 1.772 * Cb
                o = orow + x * 3
                out[o] = 0 if r < 0 else (255 if r > 255 else int(r))
                out[o + 1] = 0 if g < 0 else (255 if g > 255 else int(g))
                out[o + 2] = 0 if b < 0 else (255 if b > 255 else int(b))
        return out


# ------------------------------- أدوات اللون -------------------------------

def to_hex(r, g, b):
    return '#%02X%02X%02X' % (r, g, b)


def hsl(r, g, b):
    rr, gg, bb = r / 255, g / 255, b / 255
    mx, mn = max(rr, gg, bb), min(rr, gg, bb)
    l = (mx + mn) / 2
    d = mx - mn
    if d == 0:
        return 0, 0.0, l
    s = d / (1 - abs(2 * l - 1)) if l not in (0, 1) else 0.0
    if mx == rr:
        hh = ((gg - bb) / d) % 6
    elif mx == gg:
        hh = (bb - rr) / d + 2
    else:
        hh = (rr - gg) / d + 4
    return int(hh * 60) % 360, s, l


def measure(path):
    img = Jpeg(path)
    rgb = img.rgb()
    w, h = img.width, img.height
    buckets = {}
    total = w * h
    near_white = 0
    for i in range(0, len(rgb), 3):
        r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
        if r > 243 and g > 243 and b > 243:
            near_white += 1
            continue
        key = (r >> 4, g >> 4, b >> 4)
        e = buckets.get(key)
        if e is None:
            buckets[key] = [1, r, g, b]
        else:
            e[0] += 1
            e[1] += r
            e[2] += g
            e[3] += b
    rows = []
    for (n, sr, sg, sb) in buckets.values():
        r, g, b = round(sr / n), round(sg / n), round(sb / n)
        hh, ss, ll = hsl(r, g, b)
        rows.append({'n': n, 'hex': to_hex(r, g, b), 'rgb': (r, g, b), 'h': hh, 's': ss, 'l': ll})
    rows.sort(key=lambda x: -x['n'])

    print(f'الصورة: {w}×{h}   بكسلات: {total:,}')
    print(f'أبيض/قريب من الأبيض: {100 * near_white / total:.1f}%')
    print()
    print('أكثر ١٢ لوناً (غير الأبيض):')
    print('   اللون     نسبة%     H     S      L')
    for x in rows[:12]:
        print(f"   {x['hex']}  {100 * x['n'] / total:7.3f}  {x['h']:4}  {x['s']:.2f}  {x['l']:.2f}")

    gold = [x for x in rows if 20 <= x['h'] <= 60 and x['s'] >= 0.20 and 0.25 < x['l'] < 0.80]
    print()
    print('== الذهبي (تدرّج H بين 20 و60) ==')
    for x in gold[:6]:
        print(f"   {x['hex']}   {100 * x['n'] / total:.3f}%   L={x['l']:.2f}  S={x['s']:.2f}")

    # الذهبي «الحقيقي» = أغمق التدرّجات الشائعة (أقلّها خلطاً بالأبيض)
    strong = [x for x in gold if x['n'] > total * 0.0004]
    strong.sort(key=lambda x: x['l'])
    print()
    if strong:
        best = strong[0]
        print(f"⇒ الذهبي الأقرب للحقيقة: {best['hex']}  (H={best['h']} S={best['s']:.2f} L={best['l']:.2f})")
    dark = [x for x in rows if x['s'] < 0.18 and x['l'] < 0.35]
    if dark:
        print(f"⇒ أغمق رمادي شائع: {dark[0]['hex']}")
    return img, rgb


# ------------------------------- كتابة PNG -------------------------------

def write_png(path, w, h, rgba):
    def chunk(tag, payload):
        return (struct.pack('>I', len(payload)) + tag + payload
                + struct.pack('>I', zlib.crc32(tag + payload) & 0xFFFFFFFF))

    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
           + chunk(b'IEND', b''))
    Path(path).write_bytes(png)
    return len(png)


def transparent(path, out_path, hex_color=None, trim=True):
    """يحوّل فنّاً أحادي اللون على أبيض إلى PNG شفّاف بلون موحّد.

    الفكرة: البكسل = a*C + (1-a)*أبيض. فمن قناة واحدة نحسب a:
      a = (255 - قيمة) / (255 - قيمة_اللون)
    ونستخدم القناة ذات أكبر فرق (للذهبي: الأزرق) لأنها أدقّ إشارة.
    والنتيجة لون نظيف موحّد قابل لإعادة التلوين لاحقاً.
    """
    img = Jpeg(path)
    rgb = img.rgb()
    w, h = img.width, img.height

    if hex_color is None:
        # اقترح اللون من القياس: أغمق ذهبي شائع
        buckets = {}
        for i in range(0, len(rgb), 3):
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            if r > 243 and g > 243 and b > 243:
                continue
            key = (r >> 4, g >> 4, b >> 4)
            e = buckets.get(key)
            if e is None:
                buckets[key] = [1, r, g, b]
            else:
                e[0] += 1; e[1] += r; e[2] += g; e[3] += b
        cands = []
        for (n, sr, sg, sb) in buckets.values():
            r, g, b = round(sr / n), round(sg / n), round(sb / n)
            hh, ss, ll = hsl(r, g, b)
            if 20 <= hh <= 60 and ss >= 0.20 and 0.25 < ll < 0.80 and n > w * h * 0.0004:
                cands.append((ll, (r, g, b)))
        cands.sort()
        cr, cg, cb = cands[0][1] if cands else (197, 160, 89)
    else:
        hx = hex_color.lstrip('#')
        cr, cg, cb = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)

    # القناة ذات أكبر فرق عن الأبيض
    diffs = (255 - cr, 255 - cg, 255 - cb)
    ch = diffs.index(max(diffs))
    denom = float(max(diffs)) or 1.0

    rgba = bytearray(w * h * 4)
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            o3 = (y * w + x) * 3
            v = rgb[o3 + ch]
            a = (255.0 - v) / denom
            a = 0 if a < 0 else (1.0 if a > 1 else a)
            av = int(a * 255 + 0.5)
            if av < 8:            # تنظيف هالة ضغط JPEG
                av = 0
            o4 = (y * w + x) * 4
            rgba[o4] = cr
            rgba[o4 + 1] = cg
            rgba[o4 + 2] = cb
            rgba[o4 + 3] = av
            if av > 16:
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y

    if trim and maxx >= 0:
        pad = 4
        minx = max(0, minx - pad); miny = max(0, miny - pad)
        maxx = min(w - 1, maxx + pad); maxy = min(h - 1, maxy + pad)
        nw, nh = maxx - minx + 1, maxy - miny + 1
        crop = bytearray(nw * nh * 4)
        for y in range(nh):
            src = ((miny + y) * w + minx) * 4
            dst = y * nw * 4
            crop[dst:dst + nw * 4] = rgba[src:src + nw * 4]
        rgba, w, h = crop, nw, nh

    size = write_png(out_path, w, h, rgba)
    print(f'كُتب: {out_path}  {w}×{h}  {size:,} bytes  لون موحّد {to_hex(cr, cg, cb)}')
    return out_path, w, h, to_hex(cr, cg, cb)


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, path = argv[1], argv[2]
    if cmd == 'info':
        img = Jpeg(path)
        print(f'{img.width}×{img.height}  مكوّنات: {len(img.comps)}  '
              f'عيّنات: {[(c["h"], c["v"]) for c in img.comps]}')
    elif cmd == 'measure':
        measure(path)
    elif cmd == 'decode-png':
        # للتحقّق البصري من صحّة الفكّ: يُخرج الصورة كما فُكَّت بلا أي معالجة
        img = Jpeg(path)
        rgb = img.rgb()
        w, h = img.width, img.height
        rgba = bytearray(w * h * 4)
        for i in range(w * h):
            rgba[i * 4] = rgb[i * 3]
            rgba[i * 4 + 1] = rgb[i * 3 + 1]
            rgba[i * 4 + 2] = rgb[i * 3 + 2]
            rgba[i * 4 + 3] = 255
        out = argv[3] if len(argv) > 3 else 'decoded.png'
        size = write_png(out, w, h, rgba)
        print(f'كُتب: {out}  {w}×{h}  {size:,} bytes')
    elif cmd == 'transparent':
        out = argv[3] if len(argv) > 3 else 'out.png'
        hexc = argv[4] if len(argv) > 4 else None
        transparent(path, out, hexc)
    else:
        print('أمر غير معروف:', cmd)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
