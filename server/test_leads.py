import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import leads

class LeadsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {'lead_db': str(Path(self.tmp.name)/'test.sqlite3'), 'telegram_token': 'test', 'telegram_chat_id':'1'}
        self.body = dict(request_id='test-request-001',name='Тест',contact='@test_contact',goal='Консультация',topic='Работа',description='Проверка',consent=True,consent_version='2026-10-05.1',source={'utm_campaign':'123'},channel='chat')
    def tearDown(self):
        self.tmp.cleanup()
    def test_consent_and_price(self):
        with self.assertRaises(ValueError):
            leads.validate(dict(self.body,consent=False))
        lead = leads.validate(dict(self.body,price='1'))
        self.assertEqual(lead['price'],'от 1 500 ₽')
        self.assertEqual(lead['source'],{'utm_campaign':'123'})
    def test_idempotence(self):
        first = leads.queue(self.config,self.body)
        self.assertEqual(first,leads.queue(self.config,self.body))
    def test_callback_requires_phone(self):
        with self.assertRaises(ValueError):
            leads.validate(dict(self.body,kind='callback',channel='callback'))
        lead=leads.validate(dict(self.body,contact='+7 (922) 123-45-67',kind='callback',channel='callback'))
        self.assertEqual(lead['channel'],'Обратный звонок')
    def test_delivery_failure_and_retry(self):
        lead_id,_=leads.queue(self.config,self.body)
        with patch('leads.urllib.request.urlopen',side_effect=OSError('offline')):
            self.assertFalse(leads.deliver(self.config,lead_id))
        with patch('leads.urllib.request.urlopen',return_value=io.BytesIO(b'{"ok":true}')):
            self.assertTrue(leads.deliver(self.config,lead_id))
        self.assertTrue(leads.queue(self.config,self.body)[1])
    def test_recipient_matches_owner_and_phrase(self):
        config=dict(self.config,telegram_owner='peacocheck')
        update={'result':[{'message':{'from':{'username':'stranger'},'chat':{'type':'private','id':2},'text':'Подключить сайт 9137'}}]}
        with patch('leads.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(update).encode())):
            self.assertFalse(leads.resolve_recipient(config))
        update['result'][0]['message']['from']['username']='peacocheck'
        with patch('leads.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(update).encode())):
            self.assertTrue(leads.resolve_recipient(config))
        self.assertEqual(config['telegram_chat_id'],'2')

if __name__ == '__main__': unittest.main()
