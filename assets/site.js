/* الشيخة ستايل — سكربت مشترك للصفحتين */
(function () {
  'use strict';

  /* يُعلن عن نفسه: بلا الجافاسكربت يبقى المحتوى ظاهراً ولا يُخفيه الظهور التدريجي */
  var root = document.documentElement;
  root.classList.remove('no-js');
  root.classList.add('js');

  var v = document.querySelector('.hero video');

  /* هل الشبكة أو إعداد الجهاز يطلب تقليل البيانات؟ */
  function saveData() {
    var c = navigator.connection || navigator.webkitConnection;
    if (!c) return false;
    if (c.saveData) return true;
    return /^(slow-2g|2g|3g)$/.test(c.effectiveType || '');
  }

  /* من يطلب تقليل الحركة: تُعرض اللقطة الثابتة ولا يُشغَّل الفيديو */
  if (v && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    v.removeAttribute('autoplay');
    try { v.pause(); } catch (e) {}
  } else if (v && saveData()) {
    /* باقة محدودة أو شبكة بطيئة: تُعرض اللقطة الثابتة ولا يُنزَّل الفيديو
       (٢٫٧ ميجا على شبكة ضعيفة = شاشة فارغة طويلاً) */
    v.removeAttribute('autoplay');
    v.preload = 'none';
    try { v.pause(); } catch (e) {}
  } else if (v) {
    /* مقطع أقصر من ٥ ثوانٍ يدور في حلقة فيبدو تكراره كأنه خلل.
       إبطاؤه يُطيل الدورة ويعطي إحساس الحركة البطيئة — وهو أرقى.
       الإبطاء يُقاس على المدّة الحقيقيّة لا يُفترض. */
    v.addEventListener('loadedmetadata', function () {
      var d = v.duration;
      if (isFinite(d) && d > 0 && d < 5) {
        try { v.playbackRate = Math.max(0.45, d / 5); } catch (e) {}
      }
    });
  }

  /* ظهور تدريجي — وبلا IntersectionObserver يظهر الكلّ فوراً */
  var items = document.querySelectorAll('[data-reveal]');
  if (!('IntersectionObserver' in window)) {
    Array.prototype.forEach.call(items, function (el) { el.classList.add('in'); });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
  Array.prototype.forEach.call(items, function (el) { io.observe(el); });
})();
