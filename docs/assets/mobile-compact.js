(() => {
  'use strict';
  const mobile = window.matchMedia('(max-width: 680px)');
  const groups = [];

  // Move the original elements rather than duplicating copy or form controls.
  // The desktop layout gets its original structure back when the viewport grows.
  function fold(parent, nodes, label) {
    if (!parent || !nodes.length) return;
    const details = document.createElement('details');
    details.className = 'compact-details';
    const summary = document.createElement('summary');
    summary.textContent = label;
    const content = document.createElement('div');
    content.className = 'compact-content';
    parent.insertBefore(details, nodes[0]);
    details.append(summary, content);
    nodes.forEach(node => content.append(node));
    groups.push({ parent, details, content });
    details.addEventListener('toggle', () => window.ScrollTrigger?.refresh());
  }

  function update() {
    if (mobile.matches && !groups.length) {
      document.querySelectorAll('.practice-card').forEach(card => {
        fold(card, [...card.children].filter(node =>
          node.matches('p:not(.card-category), ul, .service-detail-link, .service-link')), 'Подробнее об услуге');
      });
      document.querySelectorAll('.price-card').forEach(card => {
        fold(card, [...card.children].filter(node =>
          node.matches('p:not(.eyebrow):not(.price):not(.price-kind), ul')), 'Что входит в цену');
      });
      const business = document.querySelector('.business-note');
      if (business) fold(business, [...business.children].filter(node =>
        node.matches('p:not(.eyebrow), .service-detail-link')), 'Какая помощь доступна');
      const steps = document.querySelector('.steps');
      if (steps) fold(steps.parentElement, [steps], 'Четыре шага к консультации');
      const about = document.querySelector('.about-details');
      if (about) fold(about, [...about.children], 'Образование и опыт');
      const form = document.querySelector('#callback-form');
      if (form) fold(form, [...form.children].filter(node =>
        node.matches('.field')), 'Добавить тему и описание');
    } else if (!mobile.matches && groups.length) {
      groups.forEach(({ parent, details, content }) => {
        while (content.firstChild) parent.insertBefore(content.firstChild, details);
        details.remove();
      });
      groups.length = 0;
    }
    window.ScrollTrigger?.refresh();
  }

  update();
  mobile.addEventListener('change', update);
})();
