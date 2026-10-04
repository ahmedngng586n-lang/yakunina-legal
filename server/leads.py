"""Validate a consultation request, durably queue it, deliver to configured owner."""
import datetime
import json
import re
import sqlite3
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from contextlib import contextmanager

GOALS = {'Консультация': 'от 1 500 ₽', 'Проверка документа': 'от 3 000 ₽', 'Договор или претензия': 'от 4 000 ₽', 'Исковое заявление': 'от 5 000 ₽', 'Судебное сопровождение': 'от 15 000 ₽'}
_delivery_lock = threading.Lock()

def clean(value, max_length):
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError('Некорректное поле заявки.')
    return re.sub(r'[\x00-\x08\x0b-\x1f]', '', value).strip()

def validate(body):
    if body.get('consent') is not True:
        raise ValueError('Подтвердите согласие на передачу заявки юристу.')
    name = clean(body.get('name', ''), 80)
    contact = clean(body.get('contact', ''), 120)
    if not name or not contact or not (len(re.sub(r'\D', '', contact)) >= 10 or re.fullmatch(r'@[\w]{5,32}', contact) or re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', contact)):
        raise ValueError('Укажите имя и телефон, Telegram @username или email.')
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
            'channel': 'Чат' if body.get('channel') == 'chat' else 'Основной виджет', 'source': tags,
            'request_id': key, 'consent_version': '2026-10-04'}

@contextmanager
def database(config):
    path = Path(config.get('lead_db', Path(__file__).resolve().parents[1] / 'private' / 'legal-leads.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute('CREATE TABLE IF NOT EXISTS leads (id TEXT PRIMARY KEY, request_id TEXT UNIQUE, payload TEXT, created TEXT, sent INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0)')
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def queue(config, body):
    lead = validate(body)
    with database(config) as conn:
        prior = conn.execute('SELECT id,sent FROM leads WHERE request_id=?', (lead['request_id'],)).fetchone()
        if prior:
            return prior[0], bool(prior[1])
        lead_id = uuid.uuid4().hex[:12]
        created = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).isoformat(timespec='seconds')
        conn.execute('INSERT INTO leads(id,request_id,payload,created) VALUES(?,?,?,?)', (lead_id, lead['request_id'], json.dumps(lead, ensure_ascii=False), created))
    return lead_id, False

def notification(lead_id, lead, created):
    tags = '\n'.join(k + ': ' + v for k, v in lead['source'].items()) or 'Без рекламных меток'
    return f"Новая заявка #{lead_id}\n{created}\n\nКто: {lead['name']}\nКонтакт: {lead['contact']}\nОткуда: {lead['channel']}\nТема: {lead['topic']}\nУслуга: {lead['goal']}\nЦена на сайте: {lead['price']}\n\nЗапрос клиента:\n{lead['description'] or 'Подробности не указаны'}\n\nИсточник рекламы:\n{tags}\n\nСогласие на передачу заявки: подтверждено. Время встречи ещё не назначено."

def deliver(config, lead_id=None):
    if not config.get('telegram_token') or not config.get('telegram_chat_id'):
        return False
    with _delivery_lock, database(config) as conn:
        if lead_id:
            rows = conn.execute('SELECT id,payload,created,attempts FROM leads WHERE id=? AND sent=0', (lead_id,)).fetchall()
        else:
            rows = conn.execute('SELECT id,payload,created,attempts FROM leads WHERE sent=0 AND next_try<=? LIMIT 5', (time.time(),)).fetchall()
        for row_id, payload, created, attempts in rows:
            try:
                body = json.dumps({'chat_id': config['telegram_chat_id'], 'text': notification(row_id, json.loads(payload), created)}, ensure_ascii=False).encode()
                req = urllib.request.Request('https://api.telegram.org/bot' + config['telegram_token'] + '/sendMessage', data=body, headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req, timeout=8) as response:
                    ok = json.load(response).get('ok', False)
                if not ok:
                    raise ValueError()
                conn.execute('UPDATE leads SET sent=1 WHERE id=?', (row_id,))
            except Exception:
                conn.execute('UPDATE leads SET attempts=attempts+1,next_try=? WHERE id=?', (time.time()+min(600,30*(attempts+1)),row_id))
            conn.commit()
        if lead_id:
            row = conn.execute('SELECT sent FROM leads WHERE id=?',(lead_id,)).fetchone()
            return bool(row and row[0])
    return False

def start_worker(config):
    def work():
        while True:
            try:
                if not config.get('telegram_chat_id') and config.get('telegram_owner'):
                    resolve_recipient(config)
                deliver(config)
                with database(config) as conn:
                    cutoff = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))-datetime.timedelta(days=30)).isoformat(timespec='seconds')
                    conn.execute('DELETE FROM leads WHERE sent=1 AND created<?',(cutoff,))
            except Exception:
                pass
            time.sleep(30)
    threading.Thread(target=work, daemon=True, name='telegram-leads').start()

def resolve_recipient(config):
    """Bind only the named owner who sent the explicit setup phrase, never the first visitor."""
    token = config.get('telegram_token')
    owner = config.get('telegram_owner','').lstrip('@').lower()
    if not token or not owner:
        return False
    req = urllib.request.Request('https://api.telegram.org/bot'+token+'/getUpdates',data=b'{"timeout":0,"limit":100}',headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.load(response)
        for update in data.get('result',[]):
            message = update.get('message',{})
            sender = message.get('from',{})
            chat = message.get('chat',{})
            if chat.get('type') == 'private' and sender.get('username','').lower() == owner and message.get('text','').strip() == 'Подключить сайт 9137':
                config['telegram_chat_id'] = str(chat['id'])
                path = config.get('_config_path')
                if path:
                    saved = json.loads(Path(path).read_text(encoding='utf-8'))
                    saved['telegram_chat_id'] = config['telegram_chat_id']
                    Path(path).write_text(json.dumps(saved),encoding='utf-8')
                return True
    except Exception:
        pass
    return False
