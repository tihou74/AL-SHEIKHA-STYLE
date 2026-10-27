/* الشيخة ستايل — سكربت مشترك للصفحتين */
(function () {
  'use strict';

  /* يُعلن عن نفسه: بلا الجافاسكربت يبقى المحتوى ظاهراً ولا يُخفيه الظهور التدريجي */
  var root = document.documentElement;
  root.classList.remove('no-js');
  root.classList.add('js');

  /* من يطلب تقليل الحركة: تُعرض اللقطة الثابتة ولا يُشغَّل الفيديو */
  var v = document.querySelector('.hero video');
  if (v && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    v.removeAttribute('autoplay');
    try { v.pause(); } catch (e) {}
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
