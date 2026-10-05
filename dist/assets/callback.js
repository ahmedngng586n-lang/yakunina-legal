'use strict';
(() => {
  const client = window.LegalClient, config = client.config;
  const form = document.getElementById('callback-form'), status = form.querySelector('.callback-status'), button = form.querySelector('button[type=submit]');
  const fields = form.elements, availability = document.getElementById('form-availability');
  const formatContext = document.createElement('div'); formatContext.className = 'format-context'; formatContext.hidden = true;
  const formatText = document.createElement('p'), resetFormat = document.createElement('button'); resetFormat.type = 'button'; resetFormat.className = 'text-link'; resetFormat.textContent = 'Начать с консультации';
  formatContext.append(formatText, resetFormat); availability.after(formatContext);
  let goal = 'Консультация', channel = 'landing', requestId = client.uid(), pending, busy = false;
  function showGoal() { formatContext.hidden = goal === 'Консультация'; formatText.textContent = 'Выбран формат: ' + goal + '.'; }
  resetFormat.addEventListener('click', () => { if (busy || pending) return; goal = 'Консультация'; showGoal(); });
  function safeUrl(value, hosts) { try { const url = new URL(value); return url.protocol === 'https:' && hosts.includes(url.hostname) ? url.href : ''; } catch { return ''; } }
  for (const [selector, key, hosts] of [['[data-profile-max]', 'maxProfileUrl', ['max.ru', 'www.max.ru']], ['[data-profile-telegram]', 'telegramProfileUrl', ['t.me']]]) {
    const url = safeUrl(config[key], hosts); if (!url) continue;
    document.querySelectorAll(selector).forEach(link => { link.href = url; link.hidden = false; link.target = '_blank'; link.rel = 'noopener noreferrer'; });
  }
  const facts = document.getElementById('practice-facts');
  for (const [key, label] of [['address', 'Приём'], ['hours', 'Часы работы'], ['consultationDuration', 'Консультация'], ['paymentMethods', 'Оплата'], ['practiceStatus', 'Статус практики'], ['courtScope', 'Работа в суде']]) {
    if (typeof config[key] !== 'string' || !config[key].trim()) continue;
    const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = label; dd.textContent = config[key]; facts.append(dt, dd); facts.hidden = false;
  }
  if (config.photo && /^(assets\/)[\w./-]+$/.test(config.photo)) { const image = document.getElementById('lawyer-photo'); image.src = config.photo; image.hidden = false; }
  if (typeof config.callbackPromise === 'string' && config.callbackPromise.trim()) { const promise = document.querySelector('.callback-promise'); promise.textContent = config.callbackPromise; promise.hidden = false; }
  const hints = { 'Трудовые вопросы': 'Что произошло на работе и когда? Если есть важная дата, укажите её.', 'Договоры и сделки': 'Какой договор и что хотите выяснить перед подписанием?', 'Недвижимость и аренда': 'Какая сделка планируется и что вызывает вопрос?', 'Претензии и судебная работа': 'В чём спор и на каком он этапе? Укажите важные даты.', 'Юридическая помощь бизнесу': 'Какая задача у организации и какой объём помощи нужен?' };
  function context() {
    document.getElementById('topic-hint').textContent = hints[fields.topic.value] || 'Пары предложений достаточно. Если есть важная дата, укажите её.';
    document.getElementById('offline-sms').href = 'sms:+79228921257?body=' + encodeURIComponent('Здравствуйте! Хочу обсудить юридический вопрос. Тема: ' + fields.topic.value + '. Подскажите формат и стоимость консультации.');
  }
  fields.topic.addEventListener('change', context); context();
  document.addEventListener('legal:context', event => {
    if (busy || pending) return;
    const detail = event.detail || {};
    if (detail.topic && [...fields.topic.options].some(option => option.value === detail.topic)) { fields.topic.value = detail.topic; goal = 'Консультация'; }
    if (detail.goal) goal = detail.goal;
    if (detail.description && !fields.description.value.trim()) fields.description.value = detail.description;
    if (detail.channel) channel = detail.channel;
    context(); showGoal();
  });
  client.ready.then(available => {
    if (!available) { form.hidden = true; availability.textContent = ''; document.getElementById('callback-offline').hidden = false; return; }
    button.disabled = false; availability.textContent = '';
  });
  function validContact(value) {
    return (/^[+()\d\s-]+$/.test(value) && value.replace(/\D/g, '').length >= 10 && value.replace(/\D/g, '').length <= 15) || /^@[a-zA-Z0-9_]{5,32}$/.test(value) || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }
  function fieldError(field, id, message) { document.getElementById(id).textContent = message; field.setAttribute('aria-invalid', String(!!message)); }
  function validate() {
    const checks = [[fields.name, 'name-error', fields.name.value.trim() ? '' : 'Укажите, как к вам обращаться.'], [fields.contact, 'contact-error', validContact(fields.contact.value.trim()) ? '' : 'Укажите телефон с кодом страны, Telegram @username или email.'], [fields.consent, 'consent-error', fields.consent.checked ? '' : 'Для отправки обращения подтвердите согласие.']];
    checks.forEach(check => fieldError(...check)); const first = checks.find(check => check[2]); if (first) first[0].focus(); return !first;
  }
  for (const [field, id] of [[fields.name, 'name-error'], [fields.contact, 'contact-error'], [fields.consent, 'consent-error']]) { field.addEventListener('input', () => { if (document.getElementById(id).textContent) fieldError(field, id, ''); }); }
  function lockFields(locked) { for (const item of [fields.name, fields.contact, fields.topic, fields.description, fields.consent]) item.disabled = locked; }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !client.available || (!pending && !validate())) return;
    if (!pending) pending = { request_id: requestId, name: fields.name.value.trim(), contact: fields.contact.value.trim(), topic: fields.topic.value, goal, description: fields.description.value.trim(), consent: fields.consent.checked, website: fields.website.value, source: client.source, channel, ...client.conversation() };
    busy = true; lockFields(true); button.disabled = true; button.textContent = 'Отправляем…'; status.textContent = '';
    try {
      const data = await client.request('/api/lead', pending);
      form.hidden = true; formatContext.hidden = true; availability.textContent = ''; document.getElementById('lead-success').hidden = false;
      document.getElementById('lead-result').textContent = data.delivery === 'sent' ? 'Заявка передана юристу. Светлана свяжется с вами по указанному контакту.' : 'Заявка сохранена. Уведомление юристу отправляется. Для срочного обсуждения позвоните.';
      document.getElementById('lead-reference').textContent = '#' + data.id;
      const heading = document.querySelector('#lead-success h3'); heading.tabIndex = -1; heading.focus({ preventScroll: true });
      pending = null; window.LegalMarketing?.track('lead_created');
    } catch (error) {
      status.textContent = error.message + (error.status ? '' : ' Повторная отправка этой заявки не создаст дубль.');
      if (error.status && error.status < 500) { pending = null; lockFields(false); }
      status.focus({ preventScroll: true });
    } finally { busy = false; button.disabled = false; button.textContent = pending ? 'Повторить отправку' : 'Оставить заявку ↗'; }
  });
})();
