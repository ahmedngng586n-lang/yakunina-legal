"""Check the public build, canonical metadata, navigation and service content."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, unquote
import json
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
ORIGIN = 'https://obz-pravo.ru'


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.elements, self.ids, self.scripts, self.text = [], set(), [], []
        self.title, self.in_title, self.in_json = '', False, False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        self.elements.append((tag, data))
        if 'id' in data:
            assert data['id'] not in self.ids, 'Duplicate id: ' + data['id']
            self.ids.add(data['id'])
        if tag == 'title': self.in_title = True
        if tag == 'script' and data.get('type') == 'application/ld+json': self.in_json = True

    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
        if tag == 'script': self.in_json = False

    def handle_data(self, text):
        if self.in_title: self.title += text
        if self.in_json: self.scripts.append(text)
        else: self.text.append(text)

    def matches(self, tag, **attrs):
        return [a for t, a in self.elements if t == tag and all(a.get(k) == v for k, v in attrs.items())]


def verify():
    pages = {('/' + str(p.parent.relative_to(DIST)).replace('\\', '/').strip('.') + '/').replace('//', '/'): Page(p.read_text(encoding='utf-8')) for p in DIST.rglob('index.html')}
    assert len(pages) == 16, f'Expected 16 canonical pages, got {len(pages)}'
    titles, descriptions = set(), set()
    for path, page in pages.items():
        assert len(page.matches('h1')) == 1, path + ': exactly one H1'
        assert page.matches('html', lang='ru'), path + ': language'
        assert 1 <= len(page.title) <= 60 and page.title not in titles, path + ': title'
        titles.add(page.title)
        meta = page.matches('meta', name='description')
        assert len(meta) == 1 and 1 <= len(meta[0]['content']) <= 160, path + ': description length'
        assert meta[0]['content'] not in descriptions, path + ': repeated description'
        descriptions.add(meta[0]['content'])
        assert page.matches('link', rel='canonical') == [{'rel': 'canonical', 'href': ORIGIN + path}], path + ': canonical'
        assert page.matches('meta', property='og:url')[0]['content'] == ORIGIN + path, path + ': OG URL'
        assert page.matches('meta', name='twitter:card'), path + ': Twitter'
        assert page.matches('link', rel='icon'), path + ': favicon'
        graphs = [json.loads(s)['@graph'] for s in page.scripts]
        assert graphs and any(x['@type'] == 'LegalService' for x in graphs[0]), path + ': LegalService'
        assert any(x['@type'] == 'Person' for x in graphs[0]), path + ': Person'
        if path != '/': assert any(x['@type'] == 'BreadcrumbList' for x in graphs[0]), path + ': breadcrumbs'
        for tag, attrs in page.elements:
            if tag == 'script' and attrs.get('src'): assert 'defer' in attrs, path + ': blocking JS'
            if tag == 'img':
                assert attrs.get('alt') and attrs.get('width') and attrs.get('height'), path + ': image dimensions/alt'
            for attr in ('href', 'src'):
                value = attrs.get(attr)
                if not value or value.startswith(('tel:', 'mailto:', 'sms:', 'data:')): continue
                url = urlsplit(urljoin(ORIGIN + path, value))
                if url.netloc != 'obz-pravo.ru': continue
                target = unquote(url.path)
                file = DIST / target.lstrip('/')
                if target.endswith('/'): file /= 'index.html'
                assert file.is_file(), f'{path}: missing {value}'
                if url.fragment:
                    target_page = pages.get(target)
                    assert target_page is not None and unquote(url.fragment) in target_page.ids, f'{path}: missing anchor {value}'
    sitemap = ET.parse(DIST / 'sitemap.xml')
    urls = [el.text for el in sitemap.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    indexable = [ORIGIN + p for p, data in pages.items() if not any('noindex' in x['content'] for x in data.matches('meta', name='robots'))]
    assert len(urls) == len(set(urls)) == 13 and set(urls) == set(indexable), 'Sitemap must match the 13 indexable canonical pages'
    all_services = []
    for part in ('a', 'b'): all_services += json.loads((ROOT / f'content/services-{part}.json').read_text(encoding='utf-8'))
    for service in all_services:
        text = service['intro'] + ' ' + ' '.join(' '.join(x['paragraphs'] + x.get('bullets', [])) for x in service['sections']) + ' ' + ' '.join(x['q'] + ' ' + x['a'] for x in service['faq'])
        assert len(re.findall(r'\S+', text)) >= 800, service['slug'] + ': less than 800 words'
        assert 5 <= len(service['faq']) <= 8, service['slug'] + ': FAQ count'
        graph = json.loads(pages['/uslugi/' + service['slug'] + '/'].scripts[0])['@graph']
        faq = next(x for x in graph if x['@type'] == 'FAQPage')['mainEntity']
        assert len(faq) == len(service['faq']), service['slug'] + ': FAQ schema mismatch'
    for source in DIST.rglob('*'):
        if source.is_file():
            target = ROOT / 'docs' / source.relative_to(DIST)
            assert target.is_file() and source.read_bytes() == target.read_bytes(), 'Static preview differs: ' + str(source)
    print('Verified: 16 pages, 13 sitemap URLs, 6 full service texts, metadata, schema, all local links/assets/anchors, dist/docs match.')


if __name__ == '__main__': verify()
