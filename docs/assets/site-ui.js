(() => {
  'use strict';
  const config = window.LEGAL_SITE || {};
  const portrait = document.querySelector('[data-lawyer-portrait]');
  if (portrait && /^assets\/[\w./-]+$/.test(config.photo || '')) {
    portrait.src = (document.body.dataset.siteRoot || '') + config.photo;
    portrait.hidden = false;
    document.querySelector('[data-portrait-placeholder]')?.setAttribute('hidden', '');
  }
  document.querySelectorAll('[data-show-map]').forEach(button => {
    button.addEventListener('click', () => {
      const frame = button.closest('.map-panel').querySelector('iframe');
      frame.src = frame.dataset.src;
      frame.hidden = false;
      button.parentElement.hidden = true;
    });
  });
  const phoneView = matchMedia('(max-width: 680px)');
  function readingLayout() {
    document.querySelectorAll('.service-section').forEach((section, index) => { section.open = !phoneView.matches || index === 0; });
    const menu = document.querySelector('.service-menu');
    if (menu) menu.open = !phoneView.matches;
  }
  readingLayout();
  phoneView.addEventListener('change', readingLayout);
})();
