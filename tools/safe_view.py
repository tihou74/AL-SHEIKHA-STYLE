#!/usr/bin/env python3
"""حارس أبعاد الصور: لا تُفتح صورة يتجاوز أحد بُعديها الحدّ.

السبب عملي ومُجرَّب: قراءة صورة يتجاوز أحد بُعديها 2000 بكسل تُسقط الجلسة
بعد انتهاء العمل كله، فيضيع الوقت والرصيد معاً. فالقاعدة: تُقرأ الأبعاد من
رأس الملفّ أوّلاً (بلا فكّ)، ولا تُفتح صورة مجهولة الأبعاد أبداً، وما تجاوز
الحدّ تُصنع له نسخة مصغّرة ويُنظر إليها.

الأوامر:
  dims <ملفّات...>              الأبعاد + هل يجوز فتحها
  safe <دخل> <خرج.png> [حدّ]    نسخة مصغّرة آمنة (الافتراضي 1400)
  scan <مجلّد> [حدّ]             يصغّر كل ما يتجاوز الحدّ في المجلّد
"""
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from jpeg_tools import Jpeg, write_png  # noqa: E402

HARD_LIMIT = 2000      # الحدّ الذي تسقط الجلسة بتجاوزه
SAFE_TARGET = 1400     # الحدّ الذي نصغّر إليه (هامش أمان)

SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
               0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


# ---------------------------- قراءة الأبعاد ----------------------------

def dims_jpeg(data):
    i = 2
    n = len(data)
    while i + 3 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        if i + 4 > n:
            break
        ln = struct.unpack('>H', data[i + 2:i + 4])[0]
        if m in SOF_MARKERS:
            h, w = struct.unpack('>HH', data[i + 5:i + 9])
            return w, h
        i += 2 + ln
    return None


def dims_png(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    w, h = struct.unpack('>II', data[16:24])
    return w, h


def dims_gif(data):
    if data[:3] != b'GIF':
        return None
    w, h = struct.unpack('<HH', data[6:10])
    return w, h


def dims_webp(data):
    if data[:4] != b'RIFF' or data[8:12] != b'WEBP':
        return None
    if data[12:16] == b'VP8X':
        w = int.from_bytes(data[24:27], 'little') + 1
        h = int.from_bytes(data[27:30], 'little') + 1
        return w, h
    if data[12:16] == b'VP8 ':
        return struct.unpack('<HH', data[26:30])
    return None


def read_dims(path):
    """ارجع (العرض, الارتفاع, الصيغة) أو (None, None, الصيغة) إن تعذّر.

    يُقرأ الملفّ كاملاً لا أوّله: مقطع EXIF من فوتوشوب قد يتجاوز عشرات
    الكيلوبايتات (مع صورة مصغّرة داخله) فتكون علامة SOF بعده — وقراءة
    أوّل 4KB فقط كانت تُرجع «أبعاد غير مقروءة» على صور سليمة تماماً.
    """
    data = Path(path).read_bytes()

    # تُحدَّد الصيغة ببصمة الملفّ لا بتجربة الفاكّات بالترتيب.
    # السبب عطلٌ حقيقي وقع: بيانات PNG المضغوطة تحتوي بايتات تشبه علامات
    # JPEG، فقرأ الفاكّ ملفّ PNG بأبعاد 57104×30464 — ولو جاء الخطأ في
    # الاتجاه الآخر لمرّت صورة ضخمة كأنها آمنة وسقطت الجلسة.
    if data[:3] == b'\xff\xd8\xff':
        fmt, fn = 'jpeg', dims_jpeg
    elif data[:8] == b'\x89PNG\r\n\x1a\n':
        fmt, fn = 'png', dims_png
    elif data[:3] == b'GIF':
        fmt, fn = 'gif', dims_gif
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        fmt, fn = 'webp', dims_webp
    elif data[4:12] in (b'ftypheic', b'ftypheix', b'ftyphevc', b'ftypmif1'):
        return None, None, 'HEIC — لا تعمل في المتصفّحات، تحتاج تحويلاً إلى JPG'
    else:
        return None, None, 'بصمة غير معروفة'

    try:
        d = fn(data)
    except Exception as e:
        return None, None, f'{fmt} معطوبة ({e})'
    if not d:
        return None, None, f'{fmt} — تعذّرت قراءة الأبعاد'
    return d[0], d[1], fmt


# ---------------------------- فكّ PNG ----------------------------

def decode_png(path):
    """فكّ PNG بعمق 8 بتّات، غير متشابك. يرجع (عرض, ارتفاع, bytes RGB)."""
    data = Path(path).read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('ليس PNG')
    pos = 8
    w = h = depth = ctype = interlace = None
    idat = bytearray()
    plte = None
    while pos < len(data):
        ln = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + ln]
        if tag == b'IHDR':
            w, h, depth, ctype, _comp, _filt, interlace = struct.unpack('>IIBBBBB', payload)
        elif tag == b'PLTE':
            plte = payload
        elif tag == b'IDAT':
            idat += payload
        elif tag == b'IEND':
            break
        pos += 12 + ln
    if depth != 8:
        raise ValueError(f'عمق {depth} بتّة غير مدعوم (المطلوب 8)')
    if interlace:
        raise ValueError('PNG متشابك غير مدعوم')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise ValueError(f'نوع لون {ctype} غير مدعوم')

    raw = zlib.decompress(bytes(idat))
    stride = w * channels
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ft != 0:
            raise ValueError(f'مرشّح سطر غير معروف: {ft}')
        out[y * stride:(y + 1) * stride] = line
        prev = line

    # تحويل إلى RGB على خلفيّة بيضاء
    rgb = bytearray(w * h * 3)
    for i in range(w * h):
        if ctype == 2:
            rgb[i * 3:i * 3 + 3] = out[i * 3:i * 3 + 3]
        elif ctype == 6:
            r, g, b, a = out[i * 4:i * 4 + 4]
            f = a / 255.0
            rgb[i * 3] = int(r * f + 255 * (1 - f))
            rgb[i * 3 + 1] = int(g * f + 255 * (1 - f))
            rgb[i * 3 + 2] = int(b * f + 255 * (1 - f))
        elif ctype == 0:
            v = out[i]
            rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = v
        elif ctype == 4:
            v, a = out[i * 2], out[i * 2 + 1]
            f = a / 255.0
            val = int(v * f + 255 * (1 - f))
            rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = val
        elif ctype == 3:
            idx = out[i]
            if plte and idx * 3 + 2 < len(plte):
                rgb[i * 3:i * 3 + 3] = plte[idx * 3:idx * 3 + 3]
    return w, h, rgb


# ---------------------------- تصغير ----------------------------

def downscale(rgb, w, h, target):
    """تصغير بمتوسّط الصناديق — بلا تسنين ولا مكتبات."""
    if max(w, h) <= target:
        return w, h, rgb
    factor = max(w, h) / float(target)
    nw, nh = max(1, int(w / factor)), max(1, int(h / factor))
    out = bytearray(nw * nh * 3)
    for ny in range(nh):
        y0, y1 = int(ny * h / nh), max(int(ny * h / nh) + 1, int((ny + 1) * h / nh))
        for nx in range(nw):
            x0, x1 = int(nx * w / nw), max(int(nx * w / nw) + 1, int((nx + 1) * w / nw))
            sr = sg = sb = cnt = 0
            for yy in range(y0, y1):
                base = yy * w * 3
                for xx in range(x0, x1):
                    o = base + xx * 3
                    sr += rgb[o]; sg += rgb[o + 1]; sb += rgb[o + 2]
                    cnt += 1
            o = (ny * nw + nx) * 3
            out[o] = sr // cnt
            out[o + 1] = sg // cnt
            out[o + 2] = sb // cnt
    return nw, nh, out


def load_rgb(path):
    w, h, fmt = read_dims(path)
    if fmt == 'jpeg':
        img = Jpeg(path)
        return img.width, img.height, img.rgb()
    if fmt == 'png':
        return decode_png(path)
    raise ValueError(f'صيغة غير مدعومة للفكّ: {fmt}')


def make_safe(src, dst, target=SAFE_TARGET):
    w, h, rgb = load_rgb(src)
    nw, nh, small = downscale(rgb, w, h, target)
    rgba = bytearray(nw * nh * 4)
    for i in range(nw * nh):
        rgba[i * 4:i * 4 + 3] = small[i * 3:i * 3 + 3]
        rgba[i * 4 + 3] = 255
    size = write_png(dst, nw, nh, rgba)
    print(f'{src}  {w}×{h}  ⇒  {dst}  {nw}×{nh}  {size:,} bytes  ✓ آمن للفتح')
    return dst, nw, nh


def cmd_dims(paths):
    bad = False
    for p in paths:
        w, h, fmt = read_dims(p)
        if w is None:
            print(f'⛔ {p}  ({fmt}) — أبعاد غير مقروءة. **لا تُفتح**')
            bad = True
            continue
        over = max(w, h) > HARD_LIMIT
        mark = '⛔ يتجاوز الحدّ — لا تُفتح مباشرة، صغّرها أوّلاً' if over else '✓ آمنة'
        print(f'{"⛔" if over else "✓"} {p}  {w}×{h}  {fmt}  {mark}')
        if over:
            bad = True
    return 1 if bad else 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == 'dims':
        return cmd_dims(argv[2:])
    if cmd == 'safe':
        if len(argv) < 4:
            print('usage: safe_view.py safe <دخل> <خرج.png> [حدّ]')
            return 2
        make_safe(argv[2], argv[3], int(argv[4]) if len(argv) > 4 else SAFE_TARGET)
        return 0
    if cmd == 'scan':
        d = Path(argv[2] if len(argv) > 2 else '.')
        target = int(argv[3]) if len(argv) > 3 else SAFE_TARGET
        outdir = d / '_safe'
        n = 0
        for f in sorted(d.iterdir()):
            if f.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
                continue
            w, h, _ = read_dims(f)
            if w and max(w, h) > HARD_LIMIT:
                outdir.mkdir(exist_ok=True)
                make_safe(str(f), str(outdir / (f.stem + '.png')), target)
                n += 1
            else:
                print(f'✓ {f.name}  {w}×{h}  آمنة كما هي')
        print(f'\nصُغّرت {n} صورة.')
        return 0
    print('أمر غير معروف:', cmd)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
