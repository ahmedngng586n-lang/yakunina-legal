"""Durable consented intake, owner-only Telegram stages and human replies.

Delivery is at least once: a timeout after Telegram accepts a message can repeat
its stable ID. Credentials, transcript bodies and upstream URLs are never logged.
"""
import datetime
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path

STATUSES = {'new': 'Новая', 'contacted': 'Связались', 'consultation': 'Консультация', 'closed': 'Закрыта'}
SOURCE_KEYS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'yclid')
CONSENT_VERSION = '2026-10-05'
SCHEMA_LOCK, DELIVERY_LOCK, POLL_LOCK = threading.Lock(), threading.Lock(), threading.Lock()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def clean(value, size):
    if not isinstance(value, str) or len(value) > size:
        raise ValueError('Некорректное поле обращения.')
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', value).strip()


def identifier(value, optional=False):
    if optional and value in (None, ''):
        return ''
    value = clean(value, 80)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{10,80}', value):
        raise ValueError('Некорректный идентификатор обращения.')
    return value


def tags(body):
    value = body.get('source', {})
    if not isinstance(value, dict):
        raise ValueError('Некорректные метки источника.')
    return {key: clean(value[key], 180) for key in SOURCE_KEYS if key in value}


@contextmanager
def database(config):
    path = Path(config.get('lead_db', Path(__file__).resolve().parents[1] / 'private' / 'legal-leads.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute('PRAGMA busy_timeout=10000')
    with SCHEMA_LOCK:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS leads (id TEXT PRIMARY KEY, request_id TEXT UNIQUE, payload TEXT, created TEXT, sent INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0)')
        columns = {row[1] for row in conn.execute('PRAGMA table_info(leads)')}
        for key, declaration in (('status', "TEXT NOT NULL DEFAULT 'new'"), ('session_id', "TEXT NOT NULL DEFAULT ''"), ('telegram_message_id', 'INTEGER'), ('updated', 'TEXT')):
            if key not in columns:
                conn.execute('ALTER TABLE leads ADD COLUMN ' + key + ' ' + declaration)
        conn.execute('CREATE TABLE IF NOT EXISTS crm_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        conn.execute("CREATE TABLE IF NOT EXISTS crm_events (id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, event_type TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '', lead_id TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL, created TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0, telegram_message_id INTEGER, error_code TEXT)")
        conn.execute('CREATE INDEX IF NOT EXISTS crm_events_pending ON crm_events(sent,next_try)')
        conn.execute('CREATE TABLE IF NOT EXISTS conversations (session_id TEXT PRIMARY KEY, token_seed TEXT, first_request_id TEXT, created TEXT NOT NULL, updated TEXT NOT NULL, consent_version TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS conversation_messages (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, session_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL, telegram_message_id INTEGER)')
        conn.execute('CREATE INDEX IF NOT EXISTS conversation_messages_session ON conversation_messages(session_id,created)')
        conn.commit()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def meta(conn, key, default=''):
    row = conn.execute('SELECT value FROM crm_meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn, key, value):
    conn.execute('INSERT INTO crm_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))


def recipient(config, conn):
    return str(config.get('telegram_chat_id') or meta(conn, 'telegram_chat_id'))


def owner(config, conn):
    value = config.get('telegram_owner_id') or meta(conn, 'telegram_owner_id')
    chat = recipient(config, conn)
    if not value and re.fullmatch(r'[1-9]\d*', chat):
        value = chat  # Private Telegram chat IDs equal the recipient user ID.
    return str(value or '')


def capabilities(config):
    with database(config) as conn:
        connected = bool(config.get('telegram_token') and recipient(config, conn))
        intake = bool(config.get('telegram_token') and (recipient(config, conn) or config.get('telegram_owner') or config.get('telegram_pairing_code')))
        pending = conn.execute('SELECT COUNT(*) FROM crm_events WHERE sent=0').fetchone()[0]
    return {'ok': True, 'capabilities': {'ai': bool(config.get('api_key')), 'telegram': connected, 'telegram_connected': connected, 'human_chat': intake},
            'crm': {'delivery': 'configured' if connected else 'awaiting_owner' if intake else 'not_configured', 'pending_events': pending}}


def session(conn, session_id):
    if session_id:
        created = now()
        conn.execute('INSERT INTO conversations(session_id,created,updated) VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET updated=excluded.updated', (session_id, created, created))


def conversation_token(conn, session_id, seed):
    secret = meta(conn, 'conversation_secret')
    if not secret:
        secret = secrets.token_hex(32)
        set_meta(conn, 'conversation_secret', secret)
    return hmac.new(secret.encode(), (session_id + ':' + seed).encode(), hashlib.sha256).hexdigest()


def authorize_session(conn, session_id, token):
    row = conn.execute('SELECT token_seed FROM conversations WHERE session_id=?', (session_id,)).fetchone()
    if not row or not row[0] or not isinstance(token, str) or not hmac.compare_digest(conversation_token(conn, session_id, row[0]).encode(), token.encode('utf-8')):
        raise PermissionError('Нет доступа к этому диалогу.')


def enqueue(conn, event_type, event_key, payload, session_id='', lead_id='', trusted=False):
    prior = conn.execute('SELECT id,sent FROM crm_events WHERE event_key=?', (event_key,)).fetchone()
    if prior:
        return prior[0], bool(prior[1])
    if not trusted and conn.execute('SELECT COUNT(*) FROM crm_events WHERE sent=0').fetchone()[0] >= 5000:
        raise OverflowError('Очередь обращений заполнена. Свяжитесь с юристом напрямую.')
    event_id = uuid.uuid4().hex[:16]
    conn.execute('INSERT INTO crm_events(id,event_key,event_type,session_id,lead_id,payload,created) VALUES(?,?,?,?,?,?,?)', (event_id, event_key, event_type, session_id, lead_id, json.dumps(payload, ensure_ascii=False), now()))
    return event_id, False


def queue_lead(config, body):
    import leads
    if not isinstance(body, dict) or body.get('website'):
        raise ValueError('Некорректная заявка.')
    lead = leads.validate(body)
    lead['session_id'] = identifier(body.get('session_id'), optional=True)
    with database(config) as conn:
        conn.execute('BEGIN IMMEDIATE')
        prior = conn.execute('SELECT id,sent FROM leads WHERE request_id=?', (lead['request_id'],)).fetchone()
        if prior:
            return prior[0], bool(prior[1])
        session_id = lead['session_id']
        if session_id:
            row = conn.execute('SELECT token_seed FROM conversations WHERE session_id=?', (session_id,)).fetchone()
            if row and row[0]:
                authorize_session(conn, session_id, body.get('conversation_token'))
            session(conn, session_id)
        lead_id, created = uuid.uuid4().hex[:12], now()
        conn.execute('INSERT INTO leads(id,request_id,payload,created,session_id,updated) VALUES(?,?,?,?,?,?)', (lead_id, lead['request_id'], json.dumps(lead, ensure_ascii=False), created, session_id, created))
        enqueue(conn, 'lead_created', 'lead:' + lead['request_id'], {}, session_id, lead_id)
    return lead_id, False


def queue_event(config, body):
    if not isinstance(body, dict) or body.get('website') or body.get('event') != 'chat_started':
        raise ValueError('Некорректное событие.')
    if body.get('consent') is not True:
        raise ValueError('Подтвердите согласие на передачу события юристу.')
    session_id = identifier(body.get('session_id'))
    identifier(body.get('request_id'))
    # Anonymous telemetry never includes free text, identity, URL or referrer.
    payload = {'source': tags(body), 'consent_version': CONSENT_VERSION}
    with database(config) as conn:
        conn.execute('BEGIN IMMEDIATE')
        session(conn, session_id)
        event_id, sent = enqueue(conn, 'chat_started', 'chat:' + session_id, payload, session_id)
    return {'ok': True, 'id': event_id, 'delivery': 'sent' if sent else 'queued'}


def queue_message(config, body):
    if not isinstance(body, dict) or body.get('website'):
        raise ValueError('Некорректное сообщение.')
    if body.get('consent') is not True:
        raise ValueError('Подтвердите согласие на передачу сообщения юристу через Telegram.')
    session_id, request_id, text = identifier(body.get('session_id')), identifier(body.get('request_id')), clean(body.get('text'), 2000)
    if not text:
        raise ValueError('Введите сообщение.')
    with database(config) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if not config.get('telegram_token') or not (recipient(config, conn) or config.get('telegram_owner') or config.get('telegram_pairing_code')):
            raise ConnectionError('Чат с юристом пока не подключён. Оставьте заявку или позвоните.')
        session(conn, session_id)
        row = conn.execute('SELECT token_seed,first_request_id FROM conversations WHERE session_id=?', (session_id,)).fetchone()
        prior = conn.execute('SELECT id,session_id FROM conversation_messages WHERE request_id=?', (request_id,)).fetchone()
        if prior and prior[1] != session_id:
            raise PermissionError('Нет доступа к этому сообщению.')
        if row[0]:
            # Stable, random first request ID can recover a lost initial response.
            if not (prior and row[1] == request_id and not body.get('conversation_token')):
                authorize_session(conn, session_id, body.get('conversation_token'))
            seed = row[0]
        else:
            seed = secrets.token_hex(24)
            conn.execute('UPDATE conversations SET token_seed=?,first_request_id=?,consent_version=? WHERE session_id=?', (seed, request_id, CONSENT_VERSION, session_id))
        token = conversation_token(conn, session_id, seed)
        if prior:
            event = conn.execute('SELECT sent FROM crm_events WHERE event_key=?', ('message:' + request_id,)).fetchone()
            return {'ok': True, 'id': prior[0], 'delivery': 'sent' if event and event[0] else 'queued', 'conversation_token': token}
        if conn.execute("SELECT COUNT(*) FROM conversation_messages WHERE session_id=? AND role='user'", (session_id,)).fetchone()[0] >= 100:
            raise OverflowError('Диалог заполнен. Продолжите обсуждение по телефону.')
        message_id, created = uuid.uuid4().hex[:16], now()
        conn.execute("INSERT INTO conversation_messages(id,request_id,session_id,role,text,created) VALUES(?,?,?,'user',?,?)", (message_id, request_id, session_id, text, created))
        conn.execute('UPDATE conversations SET updated=? WHERE session_id=?', (created, session_id))
        enqueue(conn, 'message_sent', 'message:' + request_id, {'message_id': message_id, 'text': text, 'consent_version': CONSENT_VERSION}, session_id)
    return {'ok': True, 'id': message_id, 'delivery': 'queued', 'conversation_token': token}


def conversation(config, session_id, token):
    session_id = identifier(session_id)
    with database(config) as conn:
        authorize_session(conn, session_id, token)
        rows = conn.execute('SELECT id,role,text,created FROM conversation_messages WHERE session_id=? ORDER BY created,rowid LIMIT 200', (session_id,)).fetchall()
        lead = conn.execute('SELECT status FROM leads WHERE session_id=? ORDER BY created DESC LIMIT 1', (session_id,)).fetchone()
    return {'ok': True, 'messages': [{'id': row[0], 'role': row[1], 'text': row[2], 'created': row[3]} for row in rows], 'lead_status': lead[0] if lead else None}


def display_time(created, config=None):
    offset = max(-12, min(14, int((config or {}).get('telegram_timezone_offset', 4))))
    date = datetime.datetime.fromisoformat(created).astimezone(datetime.timezone(datetime.timedelta(hours=offset)))
    return date.strftime('%d.%m.%Y %H:%M') + f' (UTC{offset:+d})'


def notification(lead_id, lead, created, status='new', config=None):
    source = '\n'.join(key + ': ' + value for key, value in lead.get('source', {}).items()) or 'Без рекламных меток'
    session_line = '\nДиалог: #' + lead.get('session_id', '')[:12] if lead.get('session_id') else ''
    return (f"Заявка #{lead_id} · {STATUSES[status]}\n{display_time(created, config)}{session_line}\n\nКлиент: {lead['name']}\nКонтакт: {lead['contact']}\nКанал: {lead['channel']}\nТема: {lead['topic'] or 'Не указана'}\nУслуга: {lead['goal']}\nЦена на сайте: {lead['price']}\n\nСитуация:\n{lead['description'] or 'Подробности не указаны'}\n\nИсточник:\n{source}\n\nСогласие на передачу: подтверждено ({lead.get('consent_version', CONSENT_VERSION)}).\nКнопки ниже меняют этап заявки. Встреча согласуется отдельно.")[:4000]


def keyboard(lead_id, status):
    buttons = [{'text': ('✓ ' if key == status else '') + label, 'callback_data': f'lead:{lead_id}:{key}'} for key, label in STATUSES.items()]
    return {'inline_keyboard': [buttons[:2], buttons[2:]]}


def telegram_call(config, method, payload):
    request = urllib.request.Request('https://api.telegram.org/bot' + config['telegram_token'] + '/' + method, data=json.dumps(payload, ensure_ascii=False).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        if method == 'editMessageText' and error.code == 400:
            try:
                body = json.loads(error.read(12000))
                if body.get('description', '').lower().startswith('bad request: message is not modified'):
                    return {'ok': True, 'result': {}}
            except (ValueError, AttributeError):
                pass
        raise ConnectionError('telegram_http_' + str(error.code)) from None
    if not isinstance(data, dict) or data.get('ok') is not True:
        raise ConnectionError('telegram_rejected')
    return data


def deliver_event(config, conn, row):
    event_id, event_type, session_id, lead_id, payload, created, attempts = row
    payload = json.loads(payload)
    request, method = {'chat_id': recipient(config, conn), 'disable_web_page_preview': True}, 'sendMessage'
    if event_type in ('lead_created', 'lead_card_updated'):
        lead_row = conn.execute('SELECT payload,created,status,telegram_message_id FROM leads WHERE id=?', (lead_id,)).fetchone()
        if not lead_row:
            conn.execute('UPDATE crm_events SET sent=1 WHERE id=?', (event_id,))
            return
        lead, lead_created, status, card_id = lead_row
        request.update(text=notification(lead_id, json.loads(lead), lead_created, status, config), reply_markup=keyboard(lead_id, status))
        if event_type == 'lead_card_updated':
            if not card_id:
                raise ConnectionError('card_not_delivered')
            method, request['message_id'] = 'editMessageText', card_id
    elif event_type == 'chat_started':
        request['text'] = f'Человек начал чат · #{session_id[:12]}\n{display_time(created, config)}\nСодержание появится после отправки сообщения с согласием.\nСобытие #{event_id}'
    elif event_type == 'message_sent':
        request['text'] = f"Сообщение клиента · диалог #{session_id[:12]}\n{display_time(created, config)}\n\n{payload['text']}\n\nСогласие на передачу через Telegram: подтверждено.\nЧтобы ответить на сайте, ответьте на это сообщение в Telegram.\nСообщение #{payload['message_id']}"
    elif event_type == 'lead_status_changed':
        request['text'] = f"Заявка #{lead_id}: {STATUSES[payload['previous_status']]} → {STATUSES[payload['status']]}\n{display_time(created, config)}\nСобытие #{event_id}"
    elif event_type == 'owner_connected':
        request['text'] = 'Сайт подключён. Здесь будут заявки и сообщения. Меняйте этап кнопками под заявкой; чтобы ответить в чат сайта, используйте «Ответить» на сообщение клиента.'
    else:
        raise ValueError('unsupported_event')
    result = telegram_call(config, method, request).get('result')
    telegram_id = result.get('message_id') if isinstance(result, dict) else None
    conn.execute('UPDATE crm_events SET sent=1,error_code=NULL,telegram_message_id=? WHERE id=?', (telegram_id, event_id))
    if event_type == 'lead_created':
        conn.execute('UPDATE leads SET sent=1,telegram_message_id=? WHERE id=?', (telegram_id, lead_id))
    if event_type == 'message_sent':
        conn.execute('UPDATE conversation_messages SET telegram_message_id=? WHERE id=?', (telegram_id, payload['message_id']))


def deliver(config, lead_id=None):
    if not config.get('telegram_token'):
        return False
    with DELIVERY_LOCK, database(config) as conn:
        if not recipient(config, conn):
            return False
        for old_id, request_id, session_id in conn.execute('SELECT id,request_id,session_id FROM leads WHERE sent=0 LIMIT 100').fetchall():
            enqueue(conn, 'lead_created', 'lead:' + request_id, {}, session_id, old_id, trusted=True)
        conn.commit()
        columns = 'id,event_type,session_id,lead_id,payload,created,attempts'
        if lead_id:  # Explicit manual retry; HTTP intake uses the background schedule.
            rows = conn.execute('SELECT ' + columns + ' FROM crm_events WHERE lead_id=? AND sent=0 ORDER BY created,rowid LIMIT 8', (lead_id,)).fetchall()
        else:
            # Confirm owner setup promptly even when intake accumulated beforehand.
            rows = conn.execute('SELECT ' + columns + " FROM crm_events WHERE sent=0 AND next_try<=? ORDER BY CASE event_type WHEN 'owner_connected' THEN 0 ELSE 1 END,created,rowid LIMIT 8", (time.time(),)).fetchall()
        for row in rows:
            try:
                deliver_event(config, conn, row)
            except Exception as error:
                delay = min(600, 10 * 2 ** min(row[6], 6))
                code = str(error) if isinstance(error, ConnectionError) and re.fullmatch(r'[a-z_0-9]+', str(error)) else 'delivery_failed'
                conn.execute('UPDATE crm_events SET attempts=attempts+1,next_try=?,error_code=? WHERE id=?', (time.time() + delay, code, row[0]))
                if row[1] == 'lead_created':
                    conn.execute('UPDATE leads SET attempts=attempts+1,next_try=? WHERE id=?', (time.time() + delay, row[3]))
            conn.commit()
        if lead_id:
            row = conn.execute('SELECT sent FROM leads WHERE id=?', (lead_id,)).fetchone()
            return bool(row and row[0])
    return False


def authorized(config, conn, sender, chat):
    return isinstance(sender, dict) and isinstance(chat, dict) and bool(owner(config, conn) and str(sender.get('id', '')) == owner(config, conn) and str(chat.get('id', '')) == recipient(config, conn))


def bind_owner(config, conn, message):
    expected = str(config.get('telegram_owner', '')).lstrip('@').lower()
    sender, chat = message.get('from', {}), message.get('chat', {})
    if not isinstance(sender, dict) or not isinstance(chat, dict) or not isinstance(message.get('text'), str):
        return False
    sender_id = sender.get('id', chat.get('id'))
    if chat.get('type') != 'private' or not sender_id or str(sender_id) != str(chat.get('id')):
        return False
    pinned = meta(conn, 'telegram_owner_id') or str(config.get('telegram_owner_id') or '')
    if pinned and pinned != str(sender_id):
        return False
    pairing = config.get('telegram_pairing_code')
    paired = bool(isinstance(pairing, str) and pairing and hmac.compare_digest(message['text'].strip().encode('utf-8'), ('/start ' + pairing).encode('utf-8')))
    named = bool(expected and str(sender.get('username', '')).lower() == expected and message['text'].strip() == 'Подключить сайт 9137')
    if paired:
        if meta(conn, 'telegram_pairing_used') or recipient(config, conn):
            return False
        set_meta(conn, 'telegram_pairing_used', '1')
    elif not named:
        return False
    set_meta(conn, 'telegram_chat_id', chat['id'])
    set_meta(conn, 'telegram_owner_id', sender_id)
    config['telegram_chat_id'], config['telegram_owner_id'] = str(chat['id']), str(sender_id)
    enqueue(conn, 'owner_connected', 'owner:' + str(sender_id), {}, trusted=True)
    return True


def process_update(config, update):
    if not isinstance(update, dict):
        return False
    update_id = update.get('update_id')
    if update_id is not None and (not isinstance(update_id, int) or isinstance(update_id, bool) or update_id < 0):
        return False
    acknowledgement, changed = None, False
    with database(config) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if update_id is not None and update_id < int(meta(conn, 'telegram_update_offset', '0')):
            return False
        callback = update.get('callback_query')
        if isinstance(callback, dict):
            sender, message = callback.get('from', {}), callback.get('message', {})
            if not isinstance(message, dict):
                message = {}
            match = re.fullmatch(r'lead:([a-f0-9]{12}):(new|contacted|consultation|closed)', str(callback.get('data', '')))
            if not authorized(config, conn, sender, message.get('chat', {})):
                acknowledgement = (callback.get('id'), 'Эта кнопка доступна только владельцу CRM.')
            elif match:
                lead_id, status = match.groups()
                row = conn.execute('SELECT status,telegram_message_id,session_id FROM leads WHERE id=?', (lead_id,)).fetchone()
                if row and row[1] and row[1] == message.get('message_id'):
                    if row[0] != status:
                        conn.execute('UPDATE leads SET status=?,updated=? WHERE id=?', (status, now(), lead_id))
                        key = str(update_id) if update_id is not None else hashlib.sha256(str(callback.get('id', '')).encode()).hexdigest()[:24]
                        enqueue(conn, 'lead_card_updated', 'card:' + key, {}, row[2], lead_id, trusted=True)
                        enqueue(conn, 'lead_status_changed', 'status:' + key, {'previous_status': row[0], 'status': status}, row[2], lead_id, trusted=True)
                        changed = True
                    acknowledgement = (callback.get('id'), 'Этап: ' + STATUSES[status])
                else:
                    acknowledgement = (callback.get('id'), 'Используйте актуальную карточку заявки.')
        message = update.get('message')
        if isinstance(message, dict):
            if bind_owner(config, conn, message):
                changed = True
            elif authorized(config, conn, message.get('from', {}), message.get('chat', {})):
                reply_message = message.get('reply_to_message', {})
                reply = reply_message.get('message_id') if isinstance(reply_message, dict) else None
                row = conn.execute("SELECT session_id FROM conversation_messages WHERE role='user' AND telegram_message_id=?", (reply,)).fetchone() if reply else None
                if row and isinstance(message.get('text'), str):
                    # Telegram permits longer owner replies than the intake input.
                    # A long reply must never poison the durable polling offset.
                    text = clean(message['text'][:4000], 4000)
                    if text:
                        key, created = 'telegram:' + str(update_id if update_id is not None else message.get('message_id')), now()
                        conn.execute("INSERT OR IGNORE INTO conversation_messages(id,request_id,session_id,role,text,created,telegram_message_id) VALUES(?,?,?,'lawyer',?,?,?)", (uuid.uuid4().hex[:16], key, row[0], text, created, message.get('message_id')))
                        conn.execute('UPDATE conversations SET updated=? WHERE session_id=?', (created, row[0]))
                        changed = True
        if update_id is not None:
            set_meta(conn, 'telegram_update_offset', update_id + 1)
    if acknowledgement and acknowledgement[0]:
        try:
            telegram_call(config, 'answerCallbackQuery', {'callback_query_id': acknowledgement[0], 'text': acknowledgement[1]})
        except Exception:
            pass  # Durable state already committed; the ephemeral toast can expire.
    return changed


def poll_updates(config):
    if not config.get('telegram_token'):
        return False
    changed = False
    with POLL_LOCK:
        with database(config) as conn:
            offset = int(meta(conn, 'telegram_update_offset', '0'))
        result = telegram_call(config, 'getUpdates', {'offset': offset, 'timeout': 0, 'limit': 100, 'allowed_updates': ['message', 'callback_query']}).get('result', [])
        if not isinstance(result, list):
            return False
        for update in sorted((item for item in result if isinstance(item, dict) and isinstance(item.get('update_id'), int)), key=lambda item: item['update_id']):
            changed = process_update(config, update) or changed
    return changed


def resolve_recipient(config):
    if not config.get('telegram_token') or not config.get('telegram_owner'):
        return False
    try:
        with database(config) as conn:
            offset = int(meta(conn, 'telegram_update_offset', '0'))
        request = urllib.request.Request('https://api.telegram.org/bot' + config['telegram_token'] + '/getUpdates', data=json.dumps({'offset': offset, 'timeout': 0, 'limit': 100}).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.load(response)
        if data.get('ok') is False:
            return False
        changed = False
        for update in data.get('result', []):
            changed = process_update(config, update) or changed
        return changed
    except Exception:
        return False


def prune(config):
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat(timespec='seconds')
    with database(config) as conn:
        conn.execute('DELETE FROM crm_events WHERE sent=1 AND created<?', (cutoff,))
        conn.execute('DELETE FROM leads WHERE sent=1 AND COALESCE(updated,created)<?', (cutoff,))
        pending = "SELECT session_id FROM crm_events WHERE sent=0 AND session_id<>''"
        expired = 'SELECT session_id FROM conversations WHERE updated<? AND session_id NOT IN (' + pending + ')'
        conn.execute('DELETE FROM conversation_messages WHERE session_id IN (' + expired + ')', (cutoff,))
        conn.execute('DELETE FROM conversations WHERE updated<? AND session_id NOT IN (' + pending + ')', (cutoff,))


def start_worker(config):
    def work():
        cycles = 0
        while True:
            try:
                deliver(config)
                if config.get('telegram_token'):
                    poll_updates(config)
                if cycles % 120 == 0:
                    prune(config)
            except Exception:
                pass
            cycles += 1
            time.sleep(3 if config.get('telegram_token') else 30)
    threading.Thread(target=work, daemon=True, name='telegram-crm').start()
