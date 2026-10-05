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
  let banner;
  function choice() { try { return sessionStorage.getItem('legal_analytics_consent'); } catch { return null; } }
  function showChoice() {
    if (!counter) return;
    if (!banner) {
      banner = document.createElement('aside'); banner.className = 'analytics-choice'; banner.setAttribute('aria-label', 'Настройки аналитики');
      const text = document.createElement('p'); text.textContent = 'Разрешить Яндекс Метрику для оценки посещений и обращений? Запись действий и форм отключена.';
      const link = document.createElement('a'); link.href = 'privacy.html'; link.textContent = 'Подробнее';
      const accept = document.createElement('button'); accept.type = 'button'; accept.textContent = 'Разрешить';
      const decline = document.createElement('button'); decline.type = 'button'; decline.textContent = 'Без аналитики';
      const choose = value => { try { sessionStorage.setItem('legal_analytics_consent', value); } catch {} banner.hidden = true; if (value === 'accepted') start(); };
      accept.addEventListener('click', () => choose('accepted')); decline.addEventListener('click', () => choose('declined'));
      banner.append(text, link, accept, decline); document.body.append(banner);
    }
    banner.hidden = false;
  }
  const settings = document.createElement('button'); settings.type = 'button'; settings.className = 'analytics-settings'; settings.textContent = 'Настройки аналитики'; settings.addEventListener('click', showChoice);
  document.querySelector('.footer-right')?.append(settings);
  document.addEventListener('click', event => {
    const target = event.target.closest('a,button'); if (!target) return;
    let goal;
    if (target.matches('[data-profile-max]')) goal = 'max_click';
    else if (target.matches('[href^="tel:"]')) goal = 'phone_click';
    else if (target.matches('[href^="mailto:"]')) goal = 'email_click';
    else if (target.matches('[data-open-chat]')) goal = 'chat_open';
    if (goal) window.LegalMarketing.track(goal);
  });
  start(); if (!choice()) showChoice();
})();
