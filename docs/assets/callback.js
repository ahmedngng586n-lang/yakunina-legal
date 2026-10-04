'use strict';
(() => {
  const config=window.LEGAL_SITE||{};
  const publicStatic=location.hostname.endsWith('.github.io')||location.protocol==='file:';
  const form=document.getElementById('callback-form');
  const status=form.querySelector('.callback-status');
  const button=form.querySelector('button[type="submit"]');
  const source={};
  try{Object.assign(source,JSON.parse(sessionStorage.getItem('legal_source')||'{}'));}catch{}
  const track=name=>{if(window.LEGAL_METRIKA_ID&&typeof window.ym==='function')window.ym(window.LEGAL_METRIKA_ID,'reachGoal',name);};
  function safeUrl(value,hosts){try{const url=new URL(value);return url.protocol==='https:'&&hosts.includes(url.hostname)?url.href:'';}catch{return '';}}
  const max=safeUrl(config.maxProfileUrl,['max.ru','www.max.ru']);
  const telegram=safeUrl(config.telegramProfileUrl,['t.me']);
  for(const [selector,url] of [['[data-profile-max]',max],['[data-profile-telegram]',telegram]]){
    document.querySelectorAll(selector).forEach(a=>{if(url){a.href=url;a.hidden=false;a.target='_blank';a.rel='noopener noreferrer';a.addEventListener('click',()=>track(selector.includes('max')?'messenger_click':'telegram_click'));}});
  }
  document.querySelectorAll('.contact-write').forEach(a=>{if(max||telegram){a.href=max||telegram;a.textContent=a.closest('.mobile-actions')?'Написать':max?'Написать в MAX':'Написать в Telegram';}a.addEventListener('click',()=>track(max?'messenger_click':telegram?'telegram_click':'sms_click'));});
  const facts=document.getElementById('practice-facts');
  for(const [key,label] of [['address','Приём'],['hours','Часы работы'],['consultationDuration','Длительность консультации'],['paymentMethods','Оплата'],['practiceStatus','Статус практики'],['courtScope','Работа в суде']]){
    if(typeof config[key]==='string'&&config[key].trim()){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=config[key];facts.append(dt,dd);facts.hidden=false;}
  }
  if(config.photo&&/^(assets\/)[\w./-]+$/.test(config.photo)){const image=document.getElementById('lawyer-photo');image.src=config.photo;image.hidden=false;}
  const promise=document.querySelector('.callback-promise');
  if(config.callbackPromise&&typeof config.callbackPromise==='string'){promise.textContent=config.callbackPromise;promise.hidden=false;}
  for(const [key,label,hosts] of [['yandexBusinessUrl','Отзывы на Яндекс Картах',['yandex.ru','yandex.com']],['twoGisUrl','Карточка в 2ГИС',['2gis.ru']]]){
    const url=safeUrl(config[key],hosts);if(url){const a=document.createElement('a');a.href=url;a.textContent=label;a.className='text-link';a.target='_blank';a.rel='noopener noreferrer';document.querySelector('.contact-channel-buttons').append(a);}
  }
  document.querySelectorAll('[data-local-only]').forEach(el=>{el.hidden=publicStatic;});
  const proofGroups=[['reviews','Отзывы клиентов','quote'],['cases','Примеры работы','task']];
  for(const [key,title,required] of proofGroups){
    if(!Array.isArray(config[key]))continue;
    const entries=config[key].filter(item=>item&&typeof item[required]==='string'&&item[required].trim()).slice(0,key==='reviews'?3:2);
    if(!entries.length)continue;
    const section=document.createElement('section');section.className='section verified-proof';
    const heading=document.createElement('h2');heading.textContent=title;section.append(heading);
    for(const item of entries){const article=document.createElement('article');if(key==='reviews'){const quote=document.createElement('blockquote');quote.textContent=item.quote;article.append(quote);if(item.author){const cite=document.createElement('p');cite.textContent=item.author;article.append(cite);}}else{for(const [field,label] of [['task','Задача'],['result','Результат']]){if(typeof item[field]==='string'){const p=document.createElement('p'),b=document.createElement('strong');b.textContent=label+': ';p.append(b,document.createTextNode(item[field]));article.append(p);}}}section.append(article);}
    document.getElementById('contact').before(section);
  }
  document.querySelectorAll('[data-callback-open]').forEach(el=>el.addEventListener('click',()=>track('callback_open')));
  if(publicStatic){form.hidden=true;document.getElementById('callback-offline').hidden=false;return;}
  let requestId=crypto.randomUUID();
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(button.disabled)return;
    const phone=form.elements.phone.value.trim();
    if(!/^[+()\d\s-]+$/.test(phone)||phone.replace(/\D/g,'').length<10||phone.replace(/\D/g,'').length>15){status.textContent='Введите телефон с кодом города или страны.';form.elements.phone.focus();return;}
    button.disabled=true;button.textContent='Отправляем…';status.textContent='';
    try{
      const response=await fetch('/api/lead',{method:'POST',headers:{'Content-Type':'application/json','X-Legal-Chat':'1'},body:JSON.stringify({request_id:requestId,name:form.elements.name.value.trim(),contact:phone,goal:'Консультация',topic:'Обратный звонок',description:'Клиент просит связаться по указанному телефону.',kind:'callback',consent:form.elements.consent.checked,website:form.elements.website.value,source,channel:'callback'})});
      const data=await response.json().catch(()=>({error:'Не удалось отправить заявку. Позвоните по номеру на сайте.'}));
      if(!response.ok||!data.ok)throw new Error(data.error);
      track('lead_submit');track('callback_submit');
      status.textContent=data.delivery==='sent'?'Просьба о звонке передана юристу.':'Заявка сохранена, но уведомление пока не доставлено. Для срочного вопроса позвоните.';
      button.textContent='Заявка сохранена';
    }catch(error){status.textContent=error.message||'Не удалось отправить заявку. Позвоните по номеру на сайте.';button.disabled=false;button.textContent='Повторить отправку';}
  });
})();
