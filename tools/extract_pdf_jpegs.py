#!/usr/bin/env python3
"""استخراج صور JPEG المدمجة من ملف PDF بلا أي مكتبة خارجية.

صور DCTDecode داخل PDF هي بايتات JPEG خام، فيكفي اقتطاع ما بين FFD8 و FFD9.
يطبع أبعاد كل صورة مستخرجة (تُقرأ من رؤوس SOF) حتى نتحقق من حد 2000 بكسل
قبل أي محاولة لعرضها.
"""
import struct
import sys
from pathlib import Path

SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
               0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def jpeg_size(buf: bytes):
    """ارجع (العرض, الارتفاع) من أول علامة SOF، أو None إن لم تُقرأ."""
    i = 2
    n = len(buf)
    while i + 3 < n:
        if buf[i] != 0xFF:
            i += 1
            continue
        marker = buf[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > n:
            break
        seg_len = struct.unpack(">H", buf[i + 2:i + 4])[0]
        if marker in SOF_MARKERS:
            if i + 9 <= n:
                h = struct.unpack(">H", buf[i + 5:i + 7])[0]
                w = struct.unpack(">H", buf[i + 7:i + 9])[0]
                return w, h
            break
        i += 2 + seg_len
    return None


def carve(data: bytes):
    """ارجع قائمة بايتات كل JPEG موجود في البيانات."""
    out = []
    pos = 0
    while True:
        start = data.find(b"\xff\xd8\xff", pos)
        if start == -1:
            break
        end = data.find(b"\xff\xd9", start + 3)
        if end == -1:
            break
        out.append(data[start:end + 2])
        pos = end + 2
    return out


def main(argv):
    if len(argv) < 3:
        print("usage: extract_pdf_jpegs.py <in.pdf> <out-prefix>")
        return 2
    src = Path(argv[1])
    prefix = Path(argv[2])
    prefix.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    images = carve(data)
    if not images:
        print("لم توجد صور JPEG مدمجة في هذا الملف.")
        return 1
    for idx, blob in enumerate(images, 1):
        dims = jpeg_size(blob)
        path = prefix.with_name(f"{prefix.name}-{idx}.jpg")
        path.write_bytes(blob)
        if dims:
            w, h = dims
            over = " ⚠️ يتجاوز 2000 بكسل — لا تُقرأ مباشرة" if max(w, h) > 2000 else " ✓ داخل الحد"
            print(f"{path}  {w}x{h}  {len(blob)} bytes{over}")
        else:
            print(f"{path}  أبعاد غير مقروءة  {len(blob)} bytes  ⚠️ لا تُقرأ قبل معرفة الأبعاد")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
