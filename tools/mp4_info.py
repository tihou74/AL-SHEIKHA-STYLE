#!/usr/bin/env python3
"""قراءة ترميز MP4 وأبعاده ومدّته من بنية الملفّ — بلا ffprobe.

سببه: فيديو بترميز HEVC/H.265 يُرفَض في كثير من المتصفّحات فيظهر **مستطيل
أسود بلا رسالة** — ولا يكتشفه إلا المالك على شاشته. فيُقرأ الترميز قبل
النشر لا بعده.

يفشل بمخرج غير صفري إن لم يكن الترميز صالحاً للويب.
"""
import struct
import sys
from pathlib import Path

CONTAINERS = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts', b'udta'}

# ترميزات الفيديو
VIDEO_OK = {b'avc1': 'H.264/AVC ✓ يعمل في كل المتصفّحات',
            b'avc3': 'H.264/AVC ✓',
            b'vp09': 'VP9 — يعمل في كروم وفايرفوكس، لا في سفاري القديم ⚠',
            b'av01': 'AV1 — حديث، لا يعمل في سفاري القديم ⚠'}
VIDEO_BAD = {b'hvc1': 'HEVC/H.265 ✗ لا يعمل في كروم وفايرفوكس على ويندوز وأندرويد',
             b'hev1': 'HEVC/H.265 ✗',
             b'dvh1': 'Dolby Vision ✗',
             b'dvhe': 'Dolby Vision ✗'}
AUDIO = {b'mp4a': 'AAC', b'ac-3': 'AC-3', b'ec-3': 'E-AC-3', b'Opus': 'Opus',
         b'alac': 'ALAC ✗ غير مدعوم في الويب'}


def walk(data, start, end, found, depth=0):
    pos = start
    while pos + 8 <= end:
        size = struct.unpack('>I', data[pos:pos + 4])[0]
        btype = data[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                break
            size = struct.unpack('>Q', data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            break
        body, body_end = pos + header, pos + size

        if btype == b'ftyp':
            found['brands'] = [data[body:body + 4].decode('latin1')]
        elif btype == b'mvhd':
            ver = data[body]
            if ver == 1:
                ts = struct.unpack('>I', data[body + 20:body + 24])[0]
                dur = struct.unpack('>Q', data[body + 24:body + 32])[0]
            else:
                ts = struct.unpack('>I', data[body + 12:body + 16])[0]
                dur = struct.unpack('>I', data[body + 16:body + 20])[0]
            if ts:
                found['duration'] = dur / ts
        elif btype == b'tkhd':
            ver = data[body]
            off = body + (96 if ver == 1 else 84) - 8
            try:
                w = struct.unpack('>I', data[off:off + 4])[0] >> 16
                h = struct.unpack('>I', data[off + 4:off + 8])[0] >> 16
                if w and h:
                    found.setdefault('tracks_wh', []).append((w, h))
            except Exception:
                pass
        elif btype == b'stsd':
            n = struct.unpack('>I', data[body + 4:body + 8])[0]
            p = body + 8
            for _ in range(n):
                if p + 8 > body_end:
                    break
                esize = struct.unpack('>I', data[p:p + 4])[0]
                fmt = data[p + 4:p + 8]
                found.setdefault('formats', []).append(fmt)
                if esize < 8:
                    break
                p += esize

        if btype in CONTAINERS:
            walk(data, body, body_end, found, depth + 1)
        pos = body_end


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    data = path.read_bytes()
    found = {}
    walk(data, 0, len(data), found)

    size_mb = len(data) / 1048576
    print(f'الملفّ: {path.name}')
    print(f'الحجم: {size_mb:.2f} ميجابايت')
    if 'brands' in found:
        print(f'النوع: {found["brands"][0]}')
    if 'duration' in found:
        print(f'المدّة: {found["duration"]:.1f} ثانية')
    for (w, h) in found.get('tracks_wh', []):
        print(f'الأبعاد: {w}×{h}')

    fmts = found.get('formats', [])
    if not fmts:
        print('✗ لم يُقرأ أي ترميز — الملفّ غير مفهوم أو ليس MP4 سليماً')
        return 1

    print('\nالترميزات:')
    ok = True
    has_video = False
    for f in fmts:
        if f in VIDEO_OK:
            has_video = True
            print(f'  فيديو {f.decode("latin1")}: {VIDEO_OK[f]}')
        elif f in VIDEO_BAD:
            has_video = True
            ok = False
            print(f'  فيديو {f.decode("latin1")}: {VIDEO_BAD[f]}')
        elif f in AUDIO:
            print(f'  صوت {f.decode("latin1")}: {AUDIO[f]}')
        else:
            print(f'  {f.decode("latin1", "replace")}: غير معروف ⚠')

    if not has_video:
        print('\n✗ لا مسار فيديو — هذا ملفّ صوت لا فيديو')
        return 1

    print()
    if size_mb > 25:
        print(f'⚠ الحجم {size_mb:.1f} ميجا يتجاوز حدّ رفع GitHub (٢٥ ميجا)')
    if found.get('duration', 0) > 30:
        print(f'⚠ المدّة {found["duration"]:.0f} ثانية طويلة لبطل يدور في حلقة')
    print('✓ صالح للويب' if ok else '✗ غير صالح: يحتاج تحويلاً إلى H.264')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
