"""Static landing and a same-origin streaming AI gateway. Python standard library only."""
import argparse
import datetime
import ipaddress
import json
import os
import re
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from collections import OrderedDict, deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from leads import queue as queue_lead, start_worker
from crm import capabilities, queue_event, queue_message, conversation

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = Path(__file__).with_name('assistant-instructions.md').read_text(encoding='utf-8')
SLOTS = threading.BoundedSemaphore(3)
REQUESTS = OrderedDict()
LOCK = threading.Lock()
CONFIG = {}
LEAD_REQUESTS = OrderedDict()

def rate_limited(buckets, key, limit, window):
    """Bound memory even if a public endpoint receives many distinct IPs."""
    now = time.monotonic()
    with LOCK:
        recent = buckets.pop(key, deque())
        while recent and recent[0] < now - window:
            recent.popleft()
        limited = len(recent) >= limit
        if not limited:
            recent.append(now)
        buckets[key] = recent
        while len(buckets) > 2048:
            buckets.popitem(last=False)
        return limited

def limit_words(text, limit=100):
    words = list(re.finditer(r'\S+', text))
    return text[:words[limit - 1].end()] if len(words) > limit else text

class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'dist'), **kwargs)

    def log_message(self, *args):
        pass  # No transcripts, API keys or upstream error bodies in access logs.

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Cache-Control', 'no-store')
        origin = self.headers.get('Origin', '')
        if origin and self.origin_allowed(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        super().end_headers()

    def origin_allowed(self, origin):
        host = self.headers.get('Host', '')
        return not origin or origin in ('http://' + host, 'https://' + host) or origin in CONFIG.get('allowed_origins', [])

    def client_key(self):
        peer = self.client_address[0]
        # Only a trusted local reverse proxy may supply a single validated IP.
        if CONFIG.get('trust_proxy') is True:
            try:
                if ipaddress.ip_address(peer).is_loopback:
                    forwarded = self.headers.get('X-Forwarded-For', '').strip()
                    return str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
        return peer

    def json_response(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        if not self.path.startswith('/api/') or not self.origin_allowed(self.headers.get('Origin', '')):
            return self.json_error(403, 'Запрос разрешён только с этого сайта.')
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Legal-Chat, Authorization')
        self.send_header('Access-Control-Max-Age', '600')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == '/api/health':
            return self.json_response(capabilities(CONFIG))
        if url.path == '/api/conversation':
            if not self.origin_allowed(self.headers.get('Origin', '')):
                return self.json_error(403, 'Запрос разрешён только с этого сайта.')
            if rate_limited(REQUESTS, ('conversation', self.client_key()), 180, 60):
                return self.json_error(429, 'Подождите перед обновлением диалога.')
            try:
                query = urllib.parse.parse_qs(url.query)
                authorization = self.headers.get('Authorization', '')
                token = authorization[7:] if authorization.startswith('Bearer ') else ''
                return self.json_response(conversation(CONFIG, query.get('session_id', [''])[0], token))
            except PermissionError as error:
                return self.json_error(403, str(error))
            except (ValueError, TypeError):
                return self.json_error(400, 'Некорректный запрос диалога.')
            except Exception:
                return self.json_error(503, 'Диалог временно недоступен.')
        if url.path.startswith('/api/'):
            return self.json_error(404, 'Страница не найдена.')
        return super().do_GET()

    def json_error(self, status, message):
        data = json.dumps({'error': message}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path in ('/api/lead', '/api/events', '/api/messages'):
            return self.intake(self.path)
        if self.path != '/api/chat':
            return self.json_error(404, 'Страница не найдена.')
        origin = self.headers.get('Origin', '')
        host = self.headers.get('Host', '')
        if not self.origin_allowed(origin):
            return self.json_error(403, 'Запрос разрешён только с этого сайта.')
        if self.headers.get('X-Legal-Chat') != '1' or 'application/json' not in self.headers.get('Content-Type', ''):
            return self.json_error(403, 'Некорректный запрос.')
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 24000:
                return self.json_error(413, 'Сократите сообщение.')
            body = json.loads(self.rfile.read(size))
            if body.get('consent') is not True or body.get('consent_version') != '2026-10-05.1':
                return self.json_error(400, 'Подтвердите отдельное согласие на обработку вопроса помощником.')
            history = body['messages']
            if not isinstance(history, list) or not 1 <= len(history) <= 12:
                raise ValueError()
            messages = []
            for item in history:
                if item.get('role') not in ('user', 'assistant') or not isinstance(item.get('content'), str) or not 1 <= len(item['content']) <= 4000:
                    raise ValueError()
                messages.append({'role': item['role'], 'content': item['content']})
            if messages[-1]['role'] != 'user':
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError):
            return self.json_error(400, 'Не удалось прочитать сообщение.')
        if not CONFIG.get('api_key'):
            return self.json_error(503, 'ИИ пока не подключён. Свяжитесь с юристом по телефону.')
        if rate_limited(REQUESTS, ('ai', self.client_key()), 12, 60):
            return self.json_error(429, 'Слишком много сообщений. Подождите минуту.')
        if not SLOTS.acquire(blocking=False):
            return self.json_error(429, 'Помощник занят. Попробуйте через несколько секунд.')
        started = False
        try:
            prompt = SYSTEM + '\nДата сервера: ' + datetime.date.today().isoformat() + '. Дата не означает актуальность твоих знаний.'
            if body.get('turn_count') == 3:
                prompt += '\nЭто третий ответ в разговоре. Ответь не более чем в 40 словах: интерфейс отдельно добавит краткую сводку и стоимость.'
            payload = {'model': CONFIG['model'], 'messages': [{'role': 'system', 'content': prompt}] + messages,
                       'stream': True, 'max_tokens': 350, 'temperature': 0.25, 'thinking': {'type': 'disabled'}}
            request = urllib.request.Request(CONFIG['base_url'].rstrip('/') + '/chat/completions',
                       data=json.dumps(payload, ensure_ascii=False).encode(),
                       headers={'Authorization': 'Bearer ' + CONFIG['api_key'], 'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=35) as response:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Connection', 'close')
                self.send_header('X-Accel-Buffering', 'no')
                self.end_headers()
                started = True
                self.close_connection = True
                emitted = ''
                word_limit = 45 if body.get('turn_count') == 3 else 100
                for raw in response:
                    if not raw.startswith(b'data:'):
                        continue
                    value = raw[5:].strip()
                    if value == b'[DONE]':
                        break
                    packet = json.loads(value)
                    if packet.get('error'):
                        self.event({'error': 'Сервис ИИ прервал ответ. Повторите вопрос позже.'})
                        return
                    delta = packet.get('choices', [{}])[0].get('delta', {})
                    content = delta.get('content')
                    if content:
                        candidate = emitted + content
                        bounded = limit_words(candidate, word_limit)
                        addition = bounded[len(emitted):]
                        if addition:
                            self.event({'text': addition})
                        emitted = bounded
                        if bounded != candidate:
                            break
                self.event({'done': True})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            if started:
                try:
                    self.event({'error': 'Ответ прерван. Попробуйте ещё раз или свяжитесь с юристом.'})
                except OSError:
                    pass
            else:
                self.json_error(502, 'Сервис ИИ временно недоступен. Повторите вопрос или свяжитесь с юристом.')
        finally:
            SLOTS.release()

    def event(self, value):
        self.wfile.write(('data: ' + json.dumps(value, ensure_ascii=False) + '\n\n').encode())
        self.wfile.flush()

    def intake(self, path):
        if not self.origin_allowed(self.headers.get('Origin', '')) or self.headers.get('X-Legal-Chat') != '1' or 'application/json' not in self.headers.get('Content-Type', ''):
            return self.json_error(403, 'Запрос разрешён только с этого сайта.')
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 12000:
                return self.json_error(413, 'Сократите обращение.')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict) or body.get('website'):
                raise ValueError('Некорректное обращение.')
            limit, window = (5, 600) if path == '/api/lead' else (12, 60)
            if rate_limited(LEAD_REQUESTS, (path, self.client_key()), limit, window):
                return self.json_error(429, 'Подождите перед повторной отправкой.')
            if path == '/api/lead':
                lead_id, sent = queue_lead(CONFIG, body)
                result = {'ok': True, 'id': lead_id, 'delivery': 'sent' if sent else 'queued'}
            elif path == '/api/events':
                result = queue_event(CONFIG, body)
            else:
                result = queue_message(CONFIG, body)
        except PermissionError as error:
            return self.json_error(403, str(error))
        except (ValueError, TypeError) as error:
            return self.json_error(400, str(error) if isinstance(error, ValueError) else 'Некорректное обращение.')
        except (ConnectionError, OverflowError) as error:
            return self.json_error(503, str(error))
        except Exception:
            return self.json_error(503, 'Не удалось сохранить обращение. Позвоните или напишите юристу.')
        return self.json_response(result)

    def create_lead(self):
        return self.intake('/api/lead')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=9137)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    if args.config:
        CONFIG.update(json.loads(args.config.read_text(encoding='utf-8')))
        CONFIG['_config_path'] = str(args.config.resolve())
    CONFIG['api_key'] = os.environ.get('LEGAL_AI_API_KEY', CONFIG.get('api_key', ''))
    CONFIG['base_url'] = os.environ.get('LEGAL_AI_BASE_URL', CONFIG.get('base_url', 'https://ai.starimg.ru/v1'))
    CONFIG['model'] = os.environ.get('LEGAL_AI_MODEL', CONFIG.get('model', 'deepseek-v4.1-flash'))
    CONFIG['telegram_token'] = os.environ.get('LEGAL_TELEGRAM_TOKEN',CONFIG.get('telegram_token',''))
    CONFIG['telegram_chat_id'] = os.environ.get('LEGAL_TELEGRAM_CHAT_ID',CONFIG.get('telegram_chat_id',''))
    CONFIG['telegram_owner'] = os.environ.get('LEGAL_TELEGRAM_OWNER', CONFIG.get('telegram_owner', ''))
    CONFIG['telegram_owner_id'] = os.environ.get('LEGAL_TELEGRAM_OWNER_ID', CONFIG.get('telegram_owner_id', ''))
    CONFIG['telegram_pairing_code'] = os.environ.get('LEGAL_TELEGRAM_PAIRING_CODE', CONFIG.get('telegram_pairing_code', ''))
    allowed_origins = CONFIG.get('allowed_origins', [])
    if not isinstance(allowed_origins, list) or any(not isinstance(origin, str) or not re.fullmatch(r'https?://[^/\s]+', origin) or '*' in origin for origin in allowed_origins):
        parser.error('allowed_origins must be an exact list of HTTP(S) origins without paths or wildcards')
    if 'lead_db' not in CONFIG:
        CONFIG['lead_db'] = str((args.config.parent if args.config else ROOT / 'private') / 'legal-leads.sqlite3')
    start_worker(CONFIG)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'Legal landing: http://{args.host}:{args.port}/ | model: {CONFIG["model"]}', flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
