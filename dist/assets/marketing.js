/* Set the real counter ID before public launch. No placeholder counter sends data. */
window.LEGAL_METRIKA_ID = Number(window.LEGAL_SITE?.metrikaId) || 0;
if (window.LEGAL_METRIKA_ID > 0) {
  window.ym = window.ym || function () { (window.ym.a = window.ym.a || []).push(arguments); };
  window.ym.l = Date.now();
  const tag = document.createElement('script');
  tag.src = 'https://mc.yandex.ru/metrika/tag.js';
  tag.async = true;
  document.head.append(tag);
  window.ym(window.LEGAL_METRIKA_ID, 'init', { clickmap: true, trackLinks: true, accurateTrackBounce: true, webvisor: false });
}
