"""Real local HTTP checks for migrated URLs and honest 404 responses."""
import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
import server


class RouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def request(self, path, method='GET'):
        conn = http.client.HTTPConnection(*self.httpd.server_address, timeout=5)
        conn.request(method, path)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_migration_preserves_attribution_for_get_and_head(self):
        for method in ('GET', 'HEAD'):
            status, headers, body = self.request('/labor.html?utm_source=yandex&yclid=123', method)
            self.assertEqual(status, 301)
            self.assertEqual(headers['Location'], '/uslugi/trudovye-spory/?utm_source=yandex&yclid=123')
            self.assertEqual(body, b'')

    def test_directory_index_has_one_canonical_url(self):
        status, headers, _ = self.request('/uslugi/dogovory/index.html')
        self.assertEqual(status, 301)
        self.assertEqual(headers['Location'], '/uslugi/dogovory/')
        self.assertEqual(self.request('/uslugi/dogovory/')[0], 200)

    def test_missing_page_is_actual_404(self):
        status, _, body = self.request('/this-page-does-not-exist/')
        self.assertEqual(status, 404)
        self.assertIn('Эта страница не найдена.'.encode(), body)
        status, _, body = self.request('/this-page-does-not-exist/', 'HEAD')
        self.assertEqual(status, 404)
        self.assertEqual(body, b'')
