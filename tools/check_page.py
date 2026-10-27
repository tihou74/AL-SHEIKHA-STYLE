#!/usr/bin/env python3
"""حارس صفحة: يتأكّد أن كل ملفّ مُشار إليه موجود فعلاً، وأن الوسوم متوازنة.

سببه: رابط صورة مكسور لا يرمي خطأً ولا يظهر في أي سجلّ — يظهر مربّعاً فارغاً
على شاشة المالك فقط، وبعد أن يفقد الثقة. فيُفحص قبل النشر لا بعده.

يفشل بمخرج غير صفري إن وجد عطلاً، ليصلح للربط بالنشر.
"""
import re
import sys
from pathlib import Path

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}


def load_pending(root: Path):
    """أصول يُعرف أنها لم تُرفع بعد — تُستثنى من الخطأ وتُطبع دائماً."""
    f = root / 'tools' / 'pending-assets.txt'
    if not f.exists():
        return set()
    out = set()
    for line in f.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            out.add(line)
    return out


def check_refs(path: Path):
    """كل src/href محلّي يجب أن يوجد، إلا ما كان معلناً في قائمة الانتظار."""
    html = path.read_text(encoding='utf-8')
    root = path.parent
    pending = load_pending(root)
    refs = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html)
    problems, waiting, checked = [], [], 0
    for r in refs:
        if r.startswith(('http://', 'https://', '//', '#', 'data:', 'mailto:', 'tel:')):
            continue
        checked += 1
        clean = r.split('?')[0].split('#')[0]
        if (root / clean).exists():
            continue
        (waiting if clean in pending else problems).append(clean)
    return checked, problems, sorted(set(waiting))


def check_tags(path: Path):
    """توازن الوسوم — لا يلتقط كل شيء لكنه يلتقط الوسم المنسيّ."""
    html = path.read_text(encoding='utf-8')
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    html = re.sub(r'<(script|style)\b.*?</\1>', '', html, flags=re.S | re.I)
    stack, problems = [], []
    for m in re.finditer(r'<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>', html):
        closing, name, attrs, self_close = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if name in VOID or self_close:
            continue
        if not closing:
            stack.append(name)
        else:
            if not stack:
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


def check_rtl_rules(path: Path):
    """قواعد تخصّ العربيّة. ترجع (أخطاء تُسقط الفحص، ملاحظات للعلم).

    تباعد الحروف على نصّ عربي عطلٌ بصري حقيقي لا ملاحظة: يقطع اتّصال
    الحروف فتظهر الكلمة مكسّرة. فيُسقط الفحص.
    """
    css = path.read_text(encoding='utf-8')
    errors, notes = [], []
    for m in re.finditer(r'([^{}]*)\{([^}]*)\}', css):
        decls = re.findall(r'letter-spacing\s*:\s*([^;}]+)', m.group(2))
        if not decls:
            continue
        # صفر أو normal لا يضرّ — بل هو إلغاء صريح للتباعد، فلا يُنذَر عنه
        live = [d.strip() for d in decls
                if d.strip().lower() not in ('0', '0px', '0em', '0rem', 'normal')]
        if not live:
            continue
        selector = m.group(1).strip().splitlines()[-1].strip()
        if 'latin' not in selector and 'num' not in selector:
            errors.append(f'letter-spacing: {live[0]} على «{selector}» — يقطع حروف العربيّة')
    for prop in ('margin-left', 'margin-right', 'padding-left', 'padding-right', 'left:', 'right:'):
        n = len(re.findall(r'[;{\s]' + re.escape(prop), css))
        if n:
            notes.append(f'خاصيّة بصريّة «{prop}» مستعملة {n} مرّة — تُفضَّل المنطقيّة (inline-start/end)')
    return errors, notes


def check_forbidden_colors(path: Path):
    """ألوان رفضها المالك لا تعود بالسهو.

    الملفّ هو مصدر الحقيقة، ويُتحقَّق أنّه قُرئ فعلاً: قائمة فارغة تعني
    حارساً لا يفحص شيئاً ويُعلن النجاح دائماً — وذلك أسوأ من غيابه.
    """
    rules_file = path.parent / 'tools' / 'forbidden-colors.txt'
    if not rules_file.exists():
        return ['ملفّ الألوان الممنوعة غير موجود — الحارس لا يفحص شيئاً'], 0
    rules = {}
    # السطر قاعدةٌ فقط إن كان لوناً ست عشريّاً يتبعه جدولة — فلا تُقرأ
    # أسطر الشرح (وهي تبدأ بـ# أيضاً) كأنّها قواعد
    for line in rules_file.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^(#[0-9A-Fa-f]{3,8})\t+(.*)$', line.rstrip())
        if m:
            rules[m.group(1).upper()] = m.group(2).strip()
    if not rules:
        return ['لم تُقرأ أي قاعدة لون — الحارس معطوب لا الصفحة'], 0
    text = path.read_text(encoding='utf-8').upper()
    found = [f'{c} — {why}' for c, why in rules.items() if c in text]
    return found, len(rules)


def main(argv):
    targets = [Path(a) for a in argv[1:]] or [Path('index.html')]
    failed = False
    for t in targets:
        if not t.exists():
            print(f'✗ الملفّ غير موجود: {t}')
            failed = True
            continue
        print(f'=== {t} ===')
        checked, missing, waiting = check_refs(t)
        if checked == 0:
            print('✗ لم يُفحص أي مرجع محلّي — الفحص نفسه معطوب، لا الصفحة')
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

        tag_problems = check_tags(t)
        if tag_problems:
            print('✗ مشاكل وسوم:')
            for p in tag_problems:
                print('   -', p)
            failed = True
        else:
            print('✓ الوسوم متوازنة')

        rtl_errors, rtl_notes = check_rtl_rules(t)
        if rtl_errors:
            print('✗ مخالفات RTL تُسقط الفحص:')
            for p in rtl_errors:
                print('   -', p)
            failed = True
        else:
            print('✓ لا مخالفات RTL')
        for p in rtl_notes:
            print('⚠ ملاحظة:', p)

        banned, n_rules = check_forbidden_colors(t)
        if banned:
            print('✗ ألوان رفضها المالك عادت إلى الصفحة:')
            for b in banned:
                print('   -', b)
            failed = True
        else:
            print(f'✓ لا لون من الألوان المرفوضة ({n_rules} قاعدة مفحوصة)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
