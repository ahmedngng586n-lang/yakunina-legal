'use strict';
(() => {
  const config = window.LEGAL_SITE || {};
  const read = key => { try { return sessionStorage.getItem(key); } catch { return null; } };
  const save = (key, value) => { try { sessionStorage.setItem(key, value); } catch {} };
  const uid = () => typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : 'request-' + Date.now() + '-' + Math.random().toString(36).slice(2);
  let sessionId = read('legal_session');
  if (!sessionId || !/^[a-zA-Z0-9_-]{10,80}$/.test(sessionId)) { sessionId = uid(); save('legal_session', sessionId); }
  let token = read('legal_conversation_token') || '';
  const source = {};
  try { Object.assign(source, JSON.parse(read('legal_source') || '{}')); } catch {}
  const query = new URLSearchParams(location.search);
  for (const key of ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'yclid']) {
    if (query.has(key)) source[key] = query.get(key).slice(0, 180);
  }
  save('legal_source', JSON.stringify(source));
  // GitHub Pages uses the configured HTTPS gateway; the server and localhost use their own origin.
  let apiBase = '';
  if (location.hostname.endsWith('.github.io') && config.apiBaseUrl) {
    try { const value = new URL(config.apiBaseUrl); if (value.protocol === 'https:') apiBase = value.origin; } catch {}
  }
  const apiUrl = path => apiBase + path;
  async function request(path, body, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeout || 12000);
    try {
      const headers = { ...(body ? { 'Content-Type': 'application/json', 'X-Legal-Chat': '1' } : {}), ...(options.headers || {}) };
      const response = await fetch(apiUrl(path), { method: body ? 'POST' : 'GET', headers, ...(body ? { body: JSON.stringify(body) } : {}), signal: controller.signal, cache: 'no-store', credentials: 'omit' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok !== true) { const error = new Error(data.error || 'Сервис временно недоступен. Попробуйте ещё раз или позвоните.'); error.status = response.status; throw error; }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Не удалось подтвердить получение. Повторите отправку или позвоните.');
      if (error instanceof TypeError) throw new Error('Нет связи с сервисом. Проверьте подключение и повторите отправку.');
      throw error;
    } finally { clearTimeout(timer); }
  }
  const client = window.LegalClient = { uid, source, sessionId, apiUrl, request, config, capabilities: {}, available: false,
    conversation: () => ({ session_id: sessionId, ...(token ? { conversation_token: token } : {}) }),
    selectContext: detail => document.dispatchEvent(new CustomEvent('legal:context', { detail })) };
  client.ready = location.protocol === 'file:' ? Promise.resolve(false) : request('/api/health', null, { timeout: 5000 }).then(data => {
    client.available = true; client.capabilities = data.capabilities || {}; return true;
  }).catch(() => false);

  const menu = document.querySelector('.menu-toggle'), nav = document.getElementById('navigation');
  function closeMenu() { nav.classList.remove('open'); menu.setAttribute('aria-expanded', 'false'); menu.setAttribute('aria-label', 'Открыть меню'); }
  menu.addEventListener('click', () => { const open = !nav.classList.contains('open'); nav.classList.toggle('open', open); menu.setAttribute('aria-expanded', String(open)); menu.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню'); });
  nav.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && nav.classList.contains('open')) { closeMenu(); menu.focus(); } });
  document.querySelectorAll('[data-topic],[data-goal]').forEach(link => link.addEventListener('click', () => client.selectContext({ topic: link.dataset.topic, goal: link.dataset.goal })));

  const dialog = document.getElementById('consult-chat'), humanPane = document.getElementById('human-pane'), aiPane = document.getElementById('ai-pane');
  const tabs = document.querySelector('.chat-tabs'), humanTab = document.getElementById('human-tab'), aiTab = document.getElementById('ai-tab');
  const form = document.getElementById('chat-form'), input = document.getElementById('chat-input'), send = document.getElementById('chat-send');
  const log = document.getElementById('chat-log'), status = document.getElementById('chat-status');
  let launcher, pollTimer, pollBusy = false, sending = false, pendingMessage, selectedPane = 'human';
  const knownMessages = new Set(), userTexts = [];
  function message(parent, text, role, created = '') {
    parent.querySelector('.chat-welcome')?.remove();
    const item = document.createElement('div'); item.className = 'chat-message' + (role === 'user' ? ' user' : '');
    const label = document.createElement('p'); label.className = 'chat-message-label'; label.textContent = role === 'user' ? 'Вы' : role === 'lawyer' ? 'Светлана Якунина · юрист' : 'ИИ-помощник';
    if (created) { const date = new Date(created); if (!Number.isNaN(date.getTime())) label.textContent += ' · ' + date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }); }
    const bubble = document.createElement('div'); bubble.className = 'chat-bubble'; bubble.textContent = text;
    item.append(label, bubble); parent.append(item); parent.scrollTop = parent.scrollHeight; return item;
  }
  function setPane(name) {
    selectedPane = name; humanPane.hidden = name !== 'human'; aiPane.hidden = name !== 'ai';
    humanTab.setAttribute('aria-selected', String(name === 'human')); aiTab.setAttribute('aria-selected', String(name === 'ai'));
    humanTab.tabIndex = name === 'human' ? 0 : -1; aiTab.tabIndex = name === 'ai' ? 0 : -1;
    document.getElementById('chat-heading').textContent = name === 'human' ? 'Написать юристу' : 'ИИ-помощник';
    if (name === 'human') poll();
  }
  humanTab.addEventListener('click', () => setPane('human')); aiTab.addEventListener('click', () => setPane('ai'));
  tabs.addEventListener('keydown', event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const name = event.key === 'Home' ? 'human' : event.key === 'End' ? 'ai' : selectedPane === 'human' ? 'ai' : 'human'; setPane(name); (name === 'human' ? humanTab : aiTab).focus(); } });
  async function poll() {
    if (!dialog.open || document.hidden || selectedPane !== 'human' || !token || !client.capabilities.human_chat || pollBusy) return;
    pollBusy = true;
    try {
      const data = await request('/api/conversation?session_id=' + encodeURIComponent(sessionId), null, { headers: { Authorization: 'Bearer ' + token }, timeout: 9000 });
      for (const item of data.messages || []) {
        if (knownMessages.has(item.id)) continue; knownMessages.add(item.id);
        message(log, item.text, item.role, item.created); if (item.role === 'user') userTexts.push(item.text);
      }
      if (data.lead_status && data.lead_status !== 'new') {
        const labels = { contacted: 'Юрист связался с вами по обращению.', consultation: 'Заявка переведена на этап консультации. Время уточните у юриста.', closed: 'Обращение закрыто юристом.' };
        if (labels[data.lead_status]) status.textContent = labels[data.lead_status];
      }
      if (status.dataset.pollError === '1') { status.textContent = 'Связь восстановлена. Ответы появятся в этом чате.'; delete status.dataset.pollError; }
    } catch (error) {
      status.textContent = error.status === 403 ? 'История этого чата недоступна. Для продолжения свяжитесь по телефону или оставьте заявку.' : 'Обновление переписки временно недоступно. Попробуем снова; для срочного вопроса позвоните.';
      status.dataset.pollError = '1';
    } finally { pollBusy = false; }
  }
  function openChat(button) {
    launcher = button; setPane('human');
    if (!dialog.open) { dialog.showModal(); document.body.classList.add('modal-open'); }
    if (client.capabilities.human_chat) input.focus({ preventScroll: true });
    poll(); clearInterval(pollTimer); pollTimer = setInterval(poll, 6000);
  }
  document.querySelectorAll('[data-open-chat]').forEach(button => button.addEventListener('click', () => openChat(button)));
  dialog.querySelector('.chat-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { document.body.classList.remove('modal-open'); clearInterval(pollTimer); launcher?.focus({ preventScroll: true }); });
  dialog.addEventListener('click', event => { if (event.target !== dialog) return; const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  client.ready.then(available => {
    const human = available && client.capabilities.human_chat;
    form.hidden = !human; document.getElementById('chat-offline').hidden = human;
    if (!human) { log.hidden = true; humanPane.querySelector('.chat-disclosure').hidden = true; }
    tabs.hidden = !client.capabilities.ai;
    if (dialog.open && human) input.focus({ preventScroll: true });
    if (token && human) document.getElementById('chat-consent').checked = read('legal_chat_consent') === '2026-10-05';
  });
  // Opening a dialog alone sends no event. Start is logged only after a visitor consents and presses Send.
  async function started() {
    if (read('legal_chat_started') === sessionId) return;
    try { await request('/api/events', { event: 'chat_started', session_id: sessionId, request_id: uid(), consent: true, source }); save('legal_chat_started', sessionId); } catch {}
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (sending || !client.capabilities.human_chat || !form.reportValidity()) return;
    const text = input.value.trim(); if (!text && !pendingMessage) { input.focus(); return; }
    if (!document.getElementById('chat-consent').checked) return;
    if (!pendingMessage) pendingMessage = { request_id: uid(), text };
    sending = true; send.disabled = true; input.readOnly = true; send.textContent = 'Отправляем…'; status.textContent = '';
    try {
      await started();
      const data = await request('/api/messages', { ...client.conversation(), ...pendingMessage, consent: true });
      token = data.conversation_token; save('legal_conversation_token', token); save('legal_chat_consent', '2026-10-05');
      if (!knownMessages.has(data.id)) { knownMessages.add(data.id); message(log, pendingMessage.text, 'user'); userTexts.push(pendingMessage.text); }
      input.value = ''; pendingMessage = null; input.readOnly = false;
      status.textContent = data.delivery === 'sent' ? 'Сообщение передано юристу. Ответ появится здесь.' : 'Сообщение сохранено. Уведомление юристу отправляется; ответ появится здесь.';
      poll(); window.LegalMarketing?.track('message_sent');
    } catch (error) {
      status.textContent = error.message + (error.status ? '' : ' Повторная отправка этого сообщения не создаст дубль.');
      if (error.status && error.status < 500) { pendingMessage = null; input.readOnly = false; }
    } finally { sending = false; send.disabled = false; send.textContent = pendingMessage ? 'Повторить отправку' : 'Отправить сообщение ↗'; }
  });
  dialog.querySelector('.chat-booking').addEventListener('click', () => {
    const description = [...userTexts, input.value.trim()].filter(Boolean).join('\n').slice(0, 1500);
    const topic = /зарплат|работодател|увол|трудов|на работе/i.test(description) ? 'Трудовые вопросы' : undefined;
    client.selectContext({ description, topic, channel: 'chat', fromChat: true }); dialog.close();
    document.getElementById('callback').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    document.getElementById('callback-name').focus({ preventScroll: true });
  });

  const aiForm = document.getElementById('ai-form'), aiInput = document.getElementById('ai-input'), aiLog = document.getElementById('ai-log'), aiSend = document.getElementById('ai-send'), aiStatus = document.getElementById('ai-status');
  let aiBusy = false, aiController, aiHistory = [], aiTurns = 0;
  aiForm.addEventListener('submit', async event => {
    event.preventDefault(); if (aiBusy) { aiController.abort(); return; }
    if (!client.capabilities.ai || !aiForm.reportValidity()) return;
    const text = aiInput.value.trim(); if (!text) return;
    aiBusy = true; aiInput.value = ''; aiInput.readOnly = true; aiSend.textContent = 'Остановить ответ'; aiStatus.textContent = '';
    message(aiLog, text, 'user'); const answer = message(aiLog, 'Готовлю предварительный ответ…', 'ai'); answer.classList.add('pending');
    const bubble = answer.querySelector('.chat-bubble'); let result = '', complete = false;
    aiController = new AbortController(); const timer = setTimeout(() => aiController.abort(), 45000);
    try {
      const response = await fetch(apiUrl('/api/chat'), { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Legal-Chat': '1' }, body: JSON.stringify({ messages: [...aiHistory.slice(-10), { role: 'user', content: text }], turn_count: aiTurns + 1 }), signal: aiController.signal, credentials: 'omit' });
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error || 'Помощник временно недоступен.'); }
      if (!response.body) throw new Error('Ответ недоступен в этом браузере.');
      const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const packet = await reader.read(); buffer += decoder.decode(packet.value || new Uint8Array(), { stream: !packet.done });
        const events = buffer.split('\n\n'); buffer = events.pop();
        for (const chunk of events) { if (!chunk.startsWith('data: ')) continue; const data = JSON.parse(chunk.slice(6)); if (data.error) throw new Error(data.error); if (data.text) { result += data.text; bubble.textContent = result; answer.classList.remove('pending'); aiLog.scrollTop = aiLog.scrollHeight; } if (data.done) complete = true; }
        if (packet.done) break;
      }
      if (!result || !complete) throw new Error('Ответ прерван. Попробуйте ещё раз.');
      aiHistory.push({ role: 'user', content: text }, { role: 'assistant', content: result }); aiTurns++;
      if (aiTurns >= 3) aiStatus.textContent = 'Для разбора ваших документов и дальнейших действий перейдите во вкладку «Юрист».';
    } catch (error) { bubble.textContent = result || (error.name === 'AbortError' ? 'Ответ остановлен.' : error.message); aiStatus.textContent = result ? 'Ответ прерван. Обсудите вопрос с юристом.' : 'Можно повторить вопрос или написать юристу.'; if (!result) aiInput.value = text; }
    finally { clearTimeout(timer); answer.classList.remove('pending'); aiBusy = false; aiInput.readOnly = false; aiSend.textContent = 'Спросить помощника'; }
  });
})();
