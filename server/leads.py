"""Consultation validation and compatibility API for the durable Telegram CRM."""
import re
# Keep this import exposed for older integrations that mocked the HTTP transport.
import urllib.request

GOALS = {'Консультация': 'от 1 500 ₽', 'Проверка документа': 'от 3 000 ₽', 'Договор или претензия': 'от 4 000 ₽', 'Исковое заявление': 'от 5 000 ₽', 'Судебное сопровождение': 'от 15 000 ₽'}

def clean(value, max_length):
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError('Некорректное поле заявки.')
    return re.sub(r'[\x00-\x08\x0b-\x1f]', '', value).strip()

def validate(body):
    if body.get('consent') is not True or body.get('consent_version') != '2026-10-05.1':
        raise ValueError('Подтвердите согласие на передачу заявки юристу.')
    name = clean(body.get('name', ''), 80)
    contact = clean(body.get('contact', ''), 120)
    phone = bool(re.fullmatch(r'[+()\d\s-]+', contact)) and 10 <= len(re.sub(r'\D', '', contact)) <= 15
    if not name or not contact or not (phone or re.fullmatch(r'@[a-zA-Z0-9_]{5,32}', contact) or re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', contact)):
        raise ValueError('Укажите имя и телефон, Telegram @username или email.')
    if (body.get('kind') == 'callback' or body.get('channel') == 'callback') and not phone:
        raise ValueError('Введите телефон с кодом города или страны.')
    if body.get('phone_format') == 'ru' and not re.fullmatch(r'7\d{10}', re.sub(r'\D', '', contact)):
        raise ValueError('Введите российский номер: +7 и 10 цифр.')
    goal = clean(body.get('goal', 'Консультация'), 80)
    if goal not in GOALS:
        raise ValueError('Выберите формат консультации.')
    key = clean(body.get('request_id', ''), 64)
    if not re.fullmatch(r'[a-zA-Z0-9-]{10,64}', key):
        raise ValueError('Некорректный идентификатор заявки.')
    source = body.get('source', {})
    if not isinstance(source, dict):
        raise ValueError('Некорректные метки источника.')
    tags = {k: clean(source[k], 180) for k in ('utm_source','utm_medium','utm_campaign','utm_content','utm_term','yclid') if k in source}
    return {'name': name, 'contact': contact, 'topic': clean(body.get('topic', ''), 120),
            'goal': goal, 'price': GOALS[goal], 'description': clean(body.get('description', ''), 1500),
            'channel': {'chat':'Чат','callback':'Обратный звонок'}.get(body.get('channel'),'Форма на сайте'), 'source': tags,
            'request_id': key, 'consent_version': '2026-10-05.1'}

# Existing deployments retain leads.queue/deliver/database/start_worker.
from crm import (database, queue_lead as queue, deliver, start_worker,
                 resolve_recipient, notification)
