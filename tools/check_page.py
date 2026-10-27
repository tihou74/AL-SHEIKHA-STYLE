#!/usr/bin/env python3
"""حارس صفحة: المراجع المفقودة، توازن الوسوم، قواعد العربيّة، الألوان المرفوضة.

سببه: رابط صورة مكسور أو لون مرفوض لا يرمي خطأً ولا يظهر في أي سجلّ — يظهر
على شاشة المالك فقط، وبعد أن يفقد الثقة. فيُفحص قبل النشر لا بعده.

قاعدة في الحارس نفسه: **لا يُعلن النجاح على صفر هدف.** إن لم يجد تنسيقاً
يفحصه أو قاعدة لون يقرؤها، يسقط ويقول إن العطل فيه لا في الصفحة — لأن
حارساً يفحص صفراً يقول «سليم» دائماً.

الاستعمال:
  python3 tools/check_page.py index.html en.html
"""
import re
import sys
from pathlib import Path

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}

# محدّدات يجوز فيها تباعد الحروف: لاتينيّة صريحة، أو أرقام، أو مقصورة على
# الصفحة الإنجليزيّة
LATIN_SAFE = ('latin', 'num', 'lang="en"', "lang='en'", '[lang=en]')

EXTERNAL = ('http://', 'https://', '//', '#', 'data:', 'mailto:', 'tel:')


def repo_root(path: Path) -> Path:
    """أعلى مجلّد فيه tools/ — ليعمل الحارس من أي مكان."""
    p = path.resolve().parent
    for cand in [p] + list(p.parents):
        if (cand / 'tools' / 'forbidden-colors.txt').exists():
            return cand
    return p


# ----------------------------- جمع التنسيق -----------------------------

def collect_css(path: Path):
    """ارجع [(الاسم, نصّ CSS)] من <style> ومن ملفّات <link> المحلّية."""
    html = path.read_text(encoding='utf-8')
    out = []
    for m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S | re.I):
        if m.group(1).strip():
            out.append((f'{path.name} «style»', m.group(1)))
    for tag in re.findall(r'<link[^>]+>', html, re.I):
        if not re.search(r'rel\s*=\s*["\']stylesheet["\']', tag, re.I):
            continue
        href = re.search(r'href\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        if not href:
            continue
        h = href.group(1)
        if h.startswith(EXTERNAL):
            continue
        f = path.parent / h.split('?')[0]
        if f.exists():
            out.append((h, f.read_text(encoding='utf-8')))
    return out


# ----------------------------- الفحوص -----------------------------

def load_pending(root: Path):
    f = root / 'tools' / 'pending-assets.txt'
    if not f.exists():
        return set()
    return {ln.strip() for ln in f.read_text(encoding='utf-8').splitlines()
            if ln.strip() and not ln.startswith('#')}


def check_refs(path: Path, root: Path):
    """كل src/href محلّي يجب أن يوجد، إلا ما كان معلناً في قائمة الانتظار."""
    html = path.read_text(encoding='utf-8')
    pending = load_pending(root)
    refs = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html)
    problems, waiting, checked = [], [], 0
    for r in refs:
        if r.startswith(EXTERNAL):
            continue
        checked += 1
        clean = r.split('?')[0].split('#')[0]
        if (path.parent / clean).exists():
            continue
        (waiting if clean in pending else problems).append(clean)
    return checked, problems, sorted(set(waiting))


def check_tags(path: Path):
    html = path.read_text(encoding='utf-8')
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    html = re.sub(r'<(script|style)\b.*?</\1>', '', html, flags=re.S | re.I)
    stack, problems = [], []
    for m in re.finditer(r'<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>', html):
        closing, name, self_close = m.group(1), m.group(2).lower(), m.group(4)
        if name in VOID or self_close:
            continue
        if not closing:
            stack.append(name)
        elif not stack:
            problems.append(f'إغلاق بلا فتح: </{name}>')
        elif stack[-1] != name:
            problems.append(f'ترتيب خطأ: مفتوح <{stack[-1]}> ويُغلق </{name}>')
            if name in stack:
                while stack and stack.pop() != name:
                    pass
        else:
            stack.pop()
    if stack:
        problems.append('وسوم لم تُغلق: ' + ', '.join(stack))
    return problems


def check_arabic_typography(sources):
    """تباعد الحروف على نصّ عربي عطلٌ بصري: يقطع اتّصال الحروف.

    يُفحص كل مصدر تنسيق. القيمة صفر أو normal لا تضرّ. والمحدّد المقصور على
    الصفحة الإنجليزيّة مستثنى لأن اللاتينيّة لا تتّصل حروفها.
    """
    errors, notes, blocks = [], [], 0
    for name, css in sources:
        for m in re.finditer(r'([^{}]*)\{([^}]*)\}', css):
            blocks += 1
            decls = re.findall(r'letter-spacing\s*:\s*([^;}]+)', m.group(2))
            if not decls:
                continue
            live = [d.strip() for d in decls
                    if d.strip().lower() not in ('0', '0px', '0em', '0rem', 'normal')]
            if not live:
                continue
            selector = m.group(1).strip().splitlines()[-1].strip()
            if not any(tok in selector for tok in LATIN_SAFE):
                errors.append(f'{name}: letter-spacing: {live[0]} على «{selector}»'
                              ' — يقطع حروف العربيّة')
        for prop in ('margin-left', 'margin-right', 'padding-left', 'padding-right'):
            n = len(re.findall(r'[;{\s]' + re.escape(prop), css))
            if n:
                notes.append(f'{name}: «{prop}» {n} مرّة — تُفضَّل المنطقيّة (inline-start/end)')
    return errors, notes, blocks


def load_forbidden(root: Path):
    f = root / 'tools' / 'forbidden-colors.txt'
    if not f.exists():
        return {}
    rules = {}
    # السطر قاعدةٌ فقط إن كان لوناً ست عشريّاً تتبعه جدولة — فلا تُقرأ أسطر
    # الشرح (وهي تبدأ بـ# أيضاً) كأنّها قواعد
    for line in f.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^(#[0-9A-Fa-f]{3,8})\t+(.*)$', line.rstrip())
        if m:
            rules[m.group(1).upper()] = m.group(2).strip()
    return rules


def check_forbidden(path: Path, sources, rules):
    """يُفحص الـHTML وكل ملفّات التنسيق — فالألوان قد تكون خارج الصفحة."""
    text = path.read_text(encoding='utf-8').upper()
    for _, css in sources:
        text += '\n' + css.upper()
    return [f'{c} — {why}' for c, why in rules.items() if c in text]


# ----------------------------- التشغيل -----------------------------

def main(argv):
    targets = [Path(a) for a in argv[1:]] or [Path('index.html')]
    failed = False
    for t in targets:
        if not t.exists():
            print(f'✗ الملفّ غير موجود: {t}')
            failed = True
            continue
        root = repo_root(t)
        print(f'=== {t} ===')

        checked, missing, waiting = check_refs(t, root)
        if checked == 0:
            print('✗ لم يُفحص أي مرجع محلّي — الحارس معطوب لا الصفحة')
            failed = True
        elif missing:
            print(f'✗ مراجع مفقودة غير معلنة ({len(missing)} من {checked}):')
            for m in missing:
                print('   -', m)
            failed = True
        else:
            print(f'✓ كل المراجع المحلّية موجودة أو معلنة ({checked})')
        if waiting:
            print(f'⏳ بانتظار رفع المالك ({len(waiting)}):')
            for m in waiting:
                print('   -', m)

        tagp = check_tags(t)
        if tagp:
            print('✗ مشاكل وسوم:')
            for p in tagp:
                print('   -', p)
            failed = True
        else:
            print('✓ الوسوم متوازنة')

        sources = collect_css(t)
        if not sources:
            print('✗ لم يوجد أي تنسيق لفحصه (لا <style> ولا ملفّ CSS محلّي)'
                  ' — الحارس يفحص صفراً، والعطل فيه لا في الصفحة')
            failed = True
            print()
            continue

        errs, notes, blocks = check_arabic_typography(sources)
        if blocks == 0:
            print('✗ قُرئ التنسيق ولم تُحلَّل أي قاعدة — الحارس معطوب')
            failed = True
        elif errs:
            print('✗ مخالفات تخصّ العربيّة:')
            for e in errs:
                print('   -', e)
            failed = True
        else:
            srcs = ', '.join(n for n, _ in sources)
            print(f'✓ لا مخالفات عربيّة ({blocks} قاعدة في: {srcs})')
        for n in notes:
            print('⚠ ملاحظة:', n)

        rules = load_forbidden(root)
        if not rules:
            print('✗ لم تُقرأ أي قاعدة لون مرفوض — الحارس معطوب لا الصفحة')
            failed = True
        else:
            banned = check_forbidden(t, sources, rules)
            if banned:
                print('✗ ألوان رفضها المالك عادت:')
                for b in banned:
                    print('   -', b)
                failed = True
            else:
                print(f'✓ لا لون مرفوض ({len(rules)} قاعدة مفحوصة)')
        print()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
