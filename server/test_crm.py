"""Isolated SQLite/HTTP CRM regressions. All Telegram calls are mocked."""
import concurrent.futures
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import crm
import leads
import server


class CRMTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {'lead_db': str(Path(self.tmp.name) / 'crm.sqlite3'), 'telegram_token': 'test-token', 'telegram_chat_id': '42', 'telegram_owner_id': '42'}
        self.sid = 'test-session-000001'
        self.lead = {'request_id': 'test-lead-000001', 'name': 'Клиент', 'contact': '+7 (922) 123-45-67', 'goal': 'Консультация', 'topic': 'Спор с работодателем', 'description': 'Задержали зарплату', 'consent': True, 'consent_version': '2026-10-05.1', 'source': {}, 'channel': 'chat'}
        self.message = {'session_id': self.sid, 'request_id': 'test-message-000001', 'text': 'Работодатель задержал зарплату.', 'consent': True, 'consent_version': '2026-10-05.1'}

    def tearDown(self):
        self.tmp.cleanup()

    def count(self, table):
        with crm.database(self.config) as conn:
            return conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def test_expired_pending_records_are_removed(self):
        crm.queue_message(self.config, self.message)
        leads.queue(self.config, self.lead)
        with crm.database(self.config) as conn:
            for table in ('crm_events', 'leads', 'conversations'):
                conn.execute('UPDATE ' + table + " SET created='2020-01-01T00:00:00+00:00'")
            conn.execute("UPDATE conversations SET updated='2020-01-01T00:00:00+00:00'")
        crm.prune(self.config)
        for table in ('crm_events', 'leads', 'conversations', 'conversation_messages'):
            self.assertEqual(self.count(table), 0, table)

    def test_expired_legacy_lead_never_delivered(self):
        lead_id, _ = crm.queue_lead(self.config, self.lead)
        with crm.database(self.config) as conn:
            conn.execute("UPDATE leads SET created='2020-01-01T00:00:00+00:00'")
            conn.execute('DELETE FROM crm_events')
        with patch('crm.telegram_call') as sender:
            self.assertFalse(crm.deliver(self.config, lead_id))
            sender.assert_not_called()
        with crm.database(self.config) as conn:
            crm.enqueue(conn, 'lead_created', 'legacy-fresh-event', {}, '', lead_id, trusted=True)
        with patch('crm.telegram_call') as sender:
            self.assertFalse(crm.deliver(self.config, lead_id))
            sender.assert_not_called()

    def deliver(self, message_id=101):
        with patch('crm.telegram_call', return_value={'ok': True, 'result': {'message_id': message_id}}):
            crm.deliver(self.config)

    def callback(self, lead_id, status='contacted', update_id=10, sender_id=42, chat_id=42, message_id=101):
        return {'update_id': update_id, 'callback_query': {'id': 'callback-' + str(update_id), 'from': {'id': sender_id}, 'data': 'lead:' + lead_id + ':' + status, 'message': {'message_id': message_id, 'chat': {'id': chat_id}}}}

    def test_consent_rejection_leaves_no_private_content(self):
        with self.assertRaises(ValueError):
            crm.queue_message(self.config, dict(self.message, consent=False))
        with self.assertRaises(ValueError):
            crm.queue_lead(self.config, dict(self.lead, consent=False))
        self.assertEqual(self.count('conversation_messages'), 0)
        self.assertEqual(self.count('crm_events'), 0)

    def test_anonymous_event_whitelist_and_session_dedup(self):
        body = {'event': 'chat_started', 'request_id': 'test-event-000001', 'session_id': self.sid, 'consent': True, 'consent_version': '2026-10-05.1', 'text': 'PRIVATE TEXT', 'contact': 'private@example.org', 'source': {'utm_source': 'search', 'referrer': 'PRIVATE URL'}}
        first = crm.queue_event(self.config, body)
        second = crm.queue_event(self.config, dict(body, request_id='test-event-000002'))
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.count('crm_events'), 1)
        with crm.database(self.config) as conn:
            payload = conn.execute('SELECT payload FROM crm_events').fetchone()[0]
        self.assertNotIn('PRIVATE', payload)
        self.assertNotIn('private@example.org', payload)
        self.assertEqual(json.loads(payload)['source'], {'utm_source': 'search'})

    def test_malformed_public_events(self):
        for body in ([], None, {'event': []}, {'event': 'message_sent', 'consent': True, 'consent_version': '2026-10-05.1'}, {'event': 'chat_started', 'session_id': self.sid, 'request_id': 'event-00000000', 'consent': False}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                crm.queue_event(self.config, body)

    def test_concurrent_lead_idempotence(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: crm.queue_lead(self.config, self.lead), range(16)))
        self.assertEqual(len({item[0] for item in results}), 1)
        self.assertEqual(self.count('leads'), 1)
        self.assertEqual(self.count('crm_events'), 1)

    def test_message_retry_and_isolation(self):
        first = crm.queue_message(self.config, self.message)
        again = crm.queue_message(dict(self.config), self.message)
        self.assertEqual(first, again)
        self.assertEqual(self.count('conversation_messages'), 1)
        with self.assertRaises(PermissionError):
            crm.queue_message(self.config, dict(self.message, request_id='test-message-000002'))
        with self.assertRaises(PermissionError):
            crm.conversation(self.config, self.sid, 'wrong-token')
        with self.assertRaises(PermissionError):
            crm.conversation(self.config, self.sid, 'Неверный токен')
        with self.assertRaises(PermissionError):
            crm.queue_message(self.config, dict(self.message, session_id='other-session-000001'))
        other = crm.queue_message(self.config, dict(self.message, session_id='other-session-000001', request_id='other-message-000001'))
        with self.assertRaises(PermissionError):
            crm.conversation(self.config, self.sid, other['conversation_token'])
        result = crm.conversation(self.config, self.sid, first['conversation_token'])
        self.assertEqual([item['text'] for item in result['messages']], [self.message['text']])

    def test_linking_existing_conversation_requires_token(self):
        message = crm.queue_message(self.config, self.message)
        body = dict(self.lead, session_id=self.sid)
        with self.assertRaises(PermissionError):
            crm.queue_lead(self.config, body)
        lead_id, sent = crm.queue_lead(self.config, dict(body, conversation_token=message['conversation_token']))
        self.assertFalse(sent)
        self.assertEqual(crm.conversation(self.config, self.sid, message['conversation_token'])['lead_status'], 'new')
        self.assertTrue(lead_id)

    def test_retry_persists_across_reopen_and_honors_delay(self):
        lead_id, _ = crm.queue_lead(self.config, self.lead)
        with patch('crm.telegram_call', side_effect=OSError('upstream-secret-token')):
            self.assertFalse(crm.deliver(self.config, lead_id))
        with crm.database(self.config) as conn:
            event = conn.execute('SELECT sent,attempts,next_try,error_code FROM crm_events').fetchone()
        self.assertEqual(event[:2], (0, 1))
        self.assertGreater(event[2], time.time())
        self.assertEqual(event[3], 'delivery_failed')
        with patch('crm.telegram_call') as api:
            crm.deliver(dict(self.config))
        api.assert_not_called()
        with crm.database(self.config) as conn:
            conn.execute('UPDATE crm_events SET next_try=0')
        self.deliver()
        self.assertTrue(crm.queue_lead(dict(self.config), self.lead)[1])

    def test_owner_only_stage_matching_chat_and_card(self):
        lead_id, _ = crm.queue_lead(self.config, self.lead)
        self.deliver()
        with patch('crm.telegram_call', return_value={'ok': True, 'result': {}}):
            for update in (self.callback(lead_id, update_id=1, sender_id=99), self.callback(lead_id, update_id=2, chat_id=99), self.callback(lead_id, update_id=3, message_id=999)):
                self.assertFalse(crm.process_update(self.config, update))
            self.assertTrue(crm.process_update(self.config, self.callback(lead_id, update_id=4)))
            self.assertFalse(crm.process_update(self.config, self.callback(lead_id, update_id=4)))
        with crm.database(self.config) as conn:
            self.assertEqual(conn.execute('SELECT status FROM leads').fetchone()[0], 'contacted')
            self.assertEqual(crm.meta(conn, 'telegram_update_offset'), '5')
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM crm_events WHERE event_type='lead_status_changed'").fetchone()[0], 1)
        with patch('crm.telegram_call', return_value={'ok': True, 'result': {'message_id': 101}}) as api:
            crm.deliver(self.config)
        edits = [call for call in api.call_args_list if call.args[1] == 'editMessageText']
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0].args[2]['message_id'], 101)
        self.assertIn('Связались', edits[0].args[2]['text'])

    def test_group_chat_cannot_authorize_other_sender(self):
        config = dict(self.config, telegram_chat_id='-900')
        with crm.database(config) as conn:
            self.assertTrue(crm.authorized(config, conn, {'id': 42}, {'id': -900}))
            self.assertFalse(crm.authorized(config, conn, {'id': 43}, {'id': -900}))
            self.assertFalse(crm.authorized(dict(config, telegram_owner_id=''), conn, {'id': 42}, {'id': -900}))

    def test_reply_isolated_and_long_reply_advances_offset(self):
        first = crm.queue_message(self.config, self.message)
        self.deliver(111)
        update = {'update_id': 7, 'message': {'message_id': 222, 'from': {'id': 99}, 'chat': {'id': 42}, 'reply_to_message': {'message_id': 111}, 'text': 'Не владелец'}}
        self.assertFalse(crm.process_update(self.config, update))
        update['update_id'], update['message']['from']['id'], update['message']['text'] = 8, 42, 'А' * 3000
        self.assertTrue(crm.process_update(self.config, update))
        update['update_id'], update['message']['text'] = 9, 'Подготовьте расчёт задолженности.'
        self.assertTrue(crm.process_update(self.config, update))
        result = crm.conversation(self.config, self.sid, first['conversation_token'])
        self.assertEqual([item['role'] for item in result['messages']], ['user', 'lawyer', 'lawyer'])
        self.assertEqual(len(result['messages'][1]['text']), 3000)
        with crm.database(self.config) as conn:
            self.assertEqual(crm.meta(conn, 'telegram_update_offset'), '10')

    def test_pairing_one_use_private_and_persistent(self):
        config = {'lead_db': self.config['lead_db'], 'telegram_token': 'test-token', 'telegram_pairing_code': 'test-pairing-code-not-real'}
        self.assertTrue(crm.capabilities(config)['capabilities']['human_chat'])
        self.assertFalse(crm.capabilities(config)['capabilities']['telegram_connected'])
        crm.queue_message(config, self.message)
        update = {'update_id': 1, 'message': {'from': {'id': 42}, 'chat': {'id': 42, 'type': 'private'}, 'text': '/start WRONG'}}
        self.assertFalse(crm.process_update(config, update))
        update['update_id'], update['message']['text'] = 2, 'Подключить сайт 9137'
        self.assertFalse(crm.process_update(config, update))
        update['update_id'], update['message']['text'], update['message']['chat']['type'] = 3, '/start test-pairing-code-not-real', 'group'
        self.assertFalse(crm.process_update(config, update))
        update['update_id'], update['message']['chat']['type'] = 4, 'private'
        self.assertTrue(crm.process_update(config, update))
        restored = {'lead_db': config['lead_db'], 'telegram_token': config['telegram_token'], 'telegram_pairing_code': config['telegram_pairing_code']}
        self.assertTrue(crm.capabilities(restored)['capabilities']['telegram_connected'])
        update['update_id'], update['message']['from']['id'], update['message']['chat']['id'] = 5, 99, 99
        self.assertFalse(crm.process_update(restored, update))
        with crm.database(restored) as conn:
            self.assertEqual(crm.recipient(restored, conn), '42')
            self.assertEqual(crm.owner(restored, conn), '42')
            self.assertEqual(crm.meta(conn, 'telegram_pairing_used'), '1')
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM crm_events WHERE event_type='owner_connected'").fetchone()[0], 1)
        with patch('crm.telegram_call', return_value={'ok': True, 'result': {'message_id': 111}}) as api:
            crm.deliver(restored)
        confirmations = [call.args[2]['text'] for call in api.call_args_list if 'Сайт подключён.' in call.args[2].get('text', '')]
        self.assertEqual(len(confirmations), 1)
        self.assertTrue(api.call_args_list[0].args[2]['text'].startswith('Сайт подключён.'))
        reply = {'update_id': 6, 'message': {'message_id': 222, 'from': {'id': 42}, 'chat': {'id': 42, 'type': 'private'}, 'reply_to_message': {'message_id': 111}, 'text': 'Здравствуйте! Подготовьте трудовой договор.'}}
        self.assertTrue(crm.process_update(restored, reply))
        with crm.database(restored) as conn:
            self.assertEqual(crm.meta(conn, 'telegram_update_offset'), '7')

    def test_contact_validation_and_telegram_text_bound(self):
        with self.assertRaises(ValueError):
            leads.validate(dict(self.lead, contact='Мой номер 1234567890 но это текст'))
        lead = leads.validate(dict(self.lead, description='Д' * 1500, name='Н' * 80, contact='a' * 100 + '@example.org', topic='Т' * 120, source={key: 'М' * 180 for key in crm.SOURCE_KEYS}))
        text = crm.notification('123456abcdef', lead, '2026-10-05T10:00:00+00:00')
        self.assertLessEqual(len(text), 4000)
        self.assertIn('14:00 (UTC+4)', text)


class HTTPTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = dict(server.CONFIG)
        server.CONFIG.clear()
        server.CONFIG.update({'lead_db': str(Path(self.tmp.name) / 'http.sqlite3'), 'telegram_token': 'mock', 'telegram_chat_id': '42', 'allowed_origins': ['https://public.example'], 'trust_proxy': True})
        server.REQUESTS.clear()
        server.LEAD_REQUESTS.clear()
        self.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.CONFIG.clear()
        server.CONFIG.update(self.original)
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=3)
        common = {'Content-Type': 'application/json', 'X-Legal-Chat': '1', 'Origin': 'https://public.example'}
        common.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, common)
        response = conn.getresponse()
        status, response_headers, data = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return status, response_headers, json.loads(data) if data else None

    def test_cors_allowlist_and_health(self):
        status, headers, value = self.request('GET', '/api/health')
        self.assertEqual(status, 200)
        self.assertTrue(value['capabilities']['human_chat'])
        self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://public.example')
        status, headers, _ = self.request('OPTIONS', '/api/messages')
        self.assertEqual(status, 204)
        self.assertIn('Authorization', headers['Access-Control-Allow-Headers'])
        status, headers, _ = self.request('OPTIONS', '/api/messages', headers={'Origin': 'https://stranger.example'})
        self.assertEqual(status, 403)
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_ai_requires_current_separate_consent(self):
        with patch('server.urllib.request.urlopen') as upstream:
            for extra in ({}, {'consent': False}, {'consent': True, 'consent_version': 'obsolete'}):
                status, _, _ = self.request('POST', '/api/chat', {'messages': [{'role':'user','content':'Вопрос'}], **extra})
                self.assertEqual(status, 400)
            upstream.assert_not_called()

    def test_http_conversation_requires_header_not_url_token(self):
        body = {'session_id': 'http-session-000001', 'request_id': 'http-message-000001', 'text': 'Задержали зарплату', 'consent': True, 'consent_version': '2026-10-05.1'}
        status, _, result = self.request('POST', '/api/messages', body)
        self.assertEqual(status, 200)
        self.assertEqual(result['delivery'], 'queued')
        path = '/api/conversation?session_id=' + body['session_id']
        status, _, _ = self.request('GET', path + '&token=' + result['conversation_token'])
        self.assertEqual(status, 403)
        status, _, value = self.request('GET', path, headers={'Authorization': 'Bearer ' + result['conversation_token']})
        self.assertEqual(status, 200)
        self.assertEqual(value['messages'][0]['text'], body['text'])

    def test_http_consent_and_malformed_reject(self):
        for body in ([], {'event': []}, {'event': 'chat_started', 'consent': False}):
            status, _, _ = self.request('POST', '/api/events', body)
            self.assertEqual(status, 400)
        status, _, _ = self.request('POST', '/api/messages', {'consent': False})
        self.assertEqual(status, 400)

    def test_proxy_clients_have_separate_rate_limits(self):
        body = {'request_id': 'proxy-lead-000001', 'name': 'Тест', 'contact': '@test_contact', 'goal': 'Консультация', 'consent': True, 'consent_version': '2026-10-05.1'}
        for _ in range(5):
            self.assertEqual(self.request('POST', '/api/lead', body, {'X-Forwarded-For': '192.0.2.1'})[0], 200)
        self.assertEqual(self.request('POST', '/api/lead', body, {'X-Forwarded-For': '192.0.2.1'})[0], 429)
        self.assertEqual(self.request('POST', '/api/lead', dict(body, request_id='proxy-lead-000002'), {'X-Forwarded-For': '192.0.2.2'})[0], 200)


if __name__ == '__main__':
    unittest.main()
