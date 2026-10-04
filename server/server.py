"""Static landing and a same-origin streaming AI gateway. Python standard library only."""
import argparse
import datetime
import json
import os
import re
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error
from collections import defaultdict, deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from leads import queue as queue_lead, deliver as deliver_lead, start_worker

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = Path(__file__).with_name('assistant-instructions.md').read_text(encoding='utf-8')
SLOTS = threading.BoundedSemaphore(3)
REQUESTS = defaultdict(deque)
LOCK = threading.Lock()
CONFIG = {}
LEAD_REQUESTS = defaultdict(deque)

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
        super().end_headers()

    def json_error(self, status, message):
        data = json.dumps({'error': message}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path == '/api/lead':
            return self.create_lead()
        if self.path != '/api/chat':
            return self.json_error(404, 'Страница не найдена.')
        origin = self.headers.get('Origin', '')
        host = self.headers.get('Host', '')
        if origin and origin not in ('http://' + host, 'https://' + host):
            return self.json_error(403, 'Запрос разрешён только с этого сайта.')
        if self.headers.get('X-Legal-Chat') != '1' or 'application/json' not in self.headers.get('Content-Type', ''):
            return self.json_error(403, 'Некорректный запрос.')
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 24000:
                return self.json_error(413, 'Сократите сообщение.')
            body = json.loads(self.rfile.read(size))
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
            return self.json_error(503, 'ИИ пока не подключён. Свяжитесь с юристом по телефону или в MAX.')
        now = time.monotonic()
        with LOCK:
            recent = REQUESTS[self.client_address[0]]
            while recent and recent[0] < now - 60:
                recent.popleft()
            if len(recent) >= 12:
                return self.json_error(429, 'Слишком много сообщений. Подождите минуту.')
            recent.append(now)
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

    def create_lead(self):
        origin = self.headers.get('Origin', '')
        host = self.headers.get('Host', '')
        if (origin and origin not in ('http://' + host, 'https://' + host)) or self.headers.get('X-Legal-Chat') != '1' or 'application/json' not in self.headers.get('Content-Type',''):
            return self.json_error(403, 'Запрос разрешён только с этого сайта.')
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 12000:
                raise ValueError('Сократите заявку.')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body,dict) or body.get('website'):
                raise ValueError('Некорректная заявка.')
            now = time.monotonic()
            with LOCK:
                recent = LEAD_REQUESTS[self.client_address[0]]
                while recent and recent[0] < now-600:
                    recent.popleft()
                if len(recent) >= 5:
                    return self.json_error(429, 'Подождите перед повторной отправкой.')
                recent.append(now)
            lead_id, sent = queue_lead(CONFIG, body)
        except (ValueError,TypeError) as error:
            return self.json_error(400, str(error) if isinstance(error,ValueError) else 'Некорректная заявка.')
        except Exception:
            return self.json_error(503,'Не удалось сохранить заявку. Позвоните или напишите в MAX.')
        if not sent:
            sent = deliver_lead(CONFIG,lead_id)
        data = json.dumps({'ok':True,'id':lead_id,'delivery':'sent' if sent else 'queued'},ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
    if 'lead_db' not in CONFIG:
        CONFIG['lead_db'] = str((args.config.parent if args.config else ROOT.parent / 'private') / 'legal-leads.sqlite3')
    start_worker(CONFIG)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'Legal landing: http://{args.host}:{args.port}/ | model: {CONFIG["model"]}', flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
