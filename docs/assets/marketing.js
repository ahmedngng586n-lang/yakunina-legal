'use strict';
// CRM events are sent by the API after explicit form/chat consent, not by a tracking pixel.
// Optional Metrika is off by default and requires a separate analytics consent.
(() => {
  const counter = Number(window.LEGAL_SITE?.metrikaId) || 0;
  let started = false;
  function consented() { try { return sessionStorage.getItem('legal_analytics_consent') === 'accepted'; } catch { return false; } }
  function start() {
    if (!counter || !consented() || started) return false;
    started = true; window.LEGAL_METRIKA_ID = counter;
    window.ym = window.ym || function () { (window.ym.a = window.ym.a || []).push(arguments); };
    window.ym.l = Date.now(); const script = document.createElement('script'); script.src = 'https://mc.yandex.ru/metrika/tag.js'; script.async = true; document.head.append(script);
    window.ym(counter, 'init', { clickmap: false, trackLinks: false, accurateTrackBounce: true, webvisor: false }); return true;
  }
  window.LegalMarketing = { track(name) { if ((started || start()) && consented() && /^[a-z_]+$/.test(name)) window.ym(counter, 'reachGoal', name); } };
  start();
})();
