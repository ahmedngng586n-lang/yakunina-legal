"""Build the public, portable static site. Python standard library only."""
from pathlib import Path
import html
import json
import posixpath
import re
import shutil
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
VERSION = '3.0.0'
ORIGIN = 'https://obz-pravo.ru'
DATE = '2026-10-06'
source = (ROOT / 'content/home-original.html').read_text(encoding='utf-8')
services = sum([json.loads((ROOT / ('content/services-' + part + '.json')).read_text(encoding='utf-8')) for part in ('a', 'b')], [])
by_slug = {s['slug']: s for s in services}
for service in services:
    service['related'] = ['sudebnoe-predstavitelstvo' if s == 'pretenzii-i-sud' else s for s in service['related']]
E = html.escape

OLD = {'consultation.html': 'uslugi/konsultaciya/', 'labor.html': 'uslugi/trudovye-spory/',
       'contracts.html': 'uslugi/dogovory/', 'real-estate.html': 'uslugi/nedvizhimost/',
       'court.html': 'uslugi/sudebnoe-predstavitelstvo/', 'business.html': 'uslugi/biznes/',
       'privacy.html': 'politika-konfidencialnosti/', 'consent.html': 'soglasie/'}
PAGES = {'': ('Юрист в Бузулуке — Светлана Якунина', 'Юрист в Бузулуке: договоры, трудовые споры, недвижимость и судебная работа. Консультация от 1 500 ₽. Позвоните или запишитесь на приём.'),
         'uslugi/': ('Услуги юриста в Бузулуке — Светлана Якунина', 'Консультации, трудовые вопросы, договоры, недвижимость и судебное сопровождение в Бузулуке. Выберите услугу и запишитесь к юристу.'),
         'ob-yuriste/': ('О юристе Светлане Якуниной — Бузулук', 'Светлана Валерьевна Якунина: более 20 лет юридического опыта, образование и направления практики. Бузулук. Свяжитесь для консультации.'),
         'stoimost/': ('Цены на услуги юриста в Бузулуке — Якунина', 'Консультация от 1 500 ₽, проверка документа от 3 000 ₽, судебное сопровождение от 15 000 ₽. Узнайте объём помощи и запишитесь в Бузулуке.'),
         'zapis-na-priem/': ('Запись к юристу в Бузулуке — Светлана Якунина', 'Оставьте имя и телефон для согласования юридической консультации в Бузулуке. От 1 500 ₽. Можно позвонить или связаться через MAX.'),
         'kontakty/': ('Контакты юриста в Бузулуке — Светлана Якунина', 'Бузулук, ул. 1 Мая, 37а. Телефон +7 922 892-12-57, MAX и email Светланы Якуниной. Постройте маршрут и согласуйте время консультации.'),
         'voprosy/': ('Вопросы о консультации юриста — Бузулук', 'Какие документы подготовить, как узнать цену и записаться к юристу в Бузулуке. Ответы перед первым обращением. Задайте свой вопрос.'),
         'politika-konfidencialnosti/': ('Политика обработки данных — ОБЗ Право', 'Как сайт obz-pravo.ru обрабатывает обращения, переписку и статистику. Получатели, сроки хранения и способы связи по вопросам данных.'),
         'soglasie/': ('Согласие на обработку данных — ОБЗ Право', 'Отдельное согласие для заявки, переписки с юристом и автоматического помощника. Цели передачи данных и порядок отзыва согласия.'),
         'cookie/': ('Cookie и статистика посещений — ОБЗ Право', 'Как используются cookie Метрики и хранилище браузера на obz-pravo.ru. Аналитика включается с разрешения. Узнайте, как изменить выбор.')}
for s in services:
    PAGES['uslugi/' + s['slug'] + '/'] = (s['title'], s['description'])

def link(page, target):
    if target.startswith(('https:', 'http:', 'tel:', 'mailto:', 'sms:', '#')):
        return target
    path, sep, fragment = target.partition('#')
    rel = posixpath.relpath(path or '.', page.rstrip('/') or '.')
    if path.endswith('/') or not path:
        rel = './' if rel == '.' else rel + '/'
    return rel + (sep + fragment if sep else '')

def localize(fragment, page):
    def replace(match):
        attr, value = match.groups()
        if value.startswith(('http:', 'https:', 'tel:', 'mailto:', 'sms:', '#', 'data:')):
            return match.group(0)
        path, sep, anchor = value.partition('#')
        path = OLD.get(path, '' if path == 'index.html' else path)
        return attr + '="' + E(link(page, path + (sep + anchor if sep else '')), quote=True) + '"'
    return re.sub(r'(href|src)="([^"]*)"', replace, fragment).replace('v=2.2.3', 'v=' + VERSION)

def button(page, text='Записаться на консультацию', topic='', goal=''):
    attrs = (f' data-topic="{E(topic)}"' if topic else '') + (f' data-goal="{E(goal)}"' if goal else '')
    return f'<a class="button" href="{link(page, "zapis-na-priem/")}"{attrs}>{E(text)} <span aria-hidden="true">↗</span></a>'

def header(page):
    menu = [('Главная', ''), ('Услуги', 'uslugi/'), ('О юристе', 'ob-yuriste/'), ('Стоимость', 'stoimost/'), ('Запись на приём', 'zapis-na-priem/'), ('Контакты', 'kontakty/')]
    nav = ''.join(f'<a href="{link(page, url)}"' + (' aria-current="page"' if url == page else '') + f'>{text}</a>' for text, url in menu)
    return f'''<a class="skip" href="#main">Перейти к содержанию</a><header class="header site-header"><div class="header-top"><a class="brand" href="{link(page, '')}" aria-label="Светлана Якунина — главная"><span class="brand-mark" aria-hidden="true">Я.</span><span>Светлана Якунина<small>Юрист · Бузулук · 20+ лет практики</small></span></a><div class="header-meta"><a class="header-phone" href="tel:+79228921257">+7 922 892-12-57</a><span>Бузулук, ул. 1 Мая, 37а</span><a href="mailto:svetlana.veshta@mail.ru">svetlana.veshta@mail.ru</a></div><button class="menu-toggle" type="button" aria-expanded="false" aria-controls="navigation" aria-label="Открыть меню"><span></span><span></span></button></div><nav class="nav" id="navigation" aria-label="Основная навигация">{nav}</nav></header>'''

def footer(page):
    nav = [('Главная', ''), ('Услуги', 'uslugi/'), ('О юристе', 'ob-yuriste/'), ('Стоимость', 'stoimost/'), ('Запись', 'zapis-na-priem/'), ('Контакты', 'kontakty/'), ('Вопросы', 'voprosy/')]
    links = ''.join(f'<a href="{link(page, url)}">{text}</a>' for text, url in nav)
    legal = ''.join(f'<a href="{link(page, url)}">{text}</a>' for url, text in [('politika-konfidencialnosti/', 'Политика обработки данных'), ('soglasie/', 'Согласие на обработку данных'), ('cookie/', 'Cookie')])
    return f'''<footer class="footer site-footer"><div><a class="brand" href="{link(page, '')}"><span class="brand-mark" aria-hidden="true">Я.</span><span>Светлана Якунина<small>Частная юридическая практика</small></span></a><p>Бузулук, ул. 1 Мая, 37а · © 2026</p><nav class="footer-nav" aria-label="Меню в подвале">{links}</nav></div><div class="footer-right"><a class="footer-phone" href="tel:+79228921257">+7 922 892-12-57</a><a href="mailto:svetlana.veshta@mail.ru">svetlana.veshta@mail.ru</a><a data-profile-max href="https://web.max.ru/46523588" target="_blank" rel="noopener noreferrer">Связаться в MAX</a>{legal}</div></footer>'''

chat = re.search(r'<dialog.*?</dialog>', source, re.S).group(0)
contact = re.search(r'<section class="section contact".*?</section>', source, re.S).group(0)
faq_source = re.search(r'<section class="section faq".*?</section>', source, re.S).group(0)

def contact_block(page, only_form=False):
    block = contact
    block = block.replace('Телефон, Telegram или email', 'Ваш телефон').replace('placeholder="+7… или @username"', 'type="tel" inputmode="tel" data-phone-only placeholder="+7 (___) ___-__-__"')
    block = block.replace('id="lawyer-photo" class="lawyer-photo"', 'id="lawyer-photo" class="lawyer-photo" width="360" height="450" loading="lazy"')
    block = block.replace('Начнём с короткого<br> обращения.', 'Записаться на<br> консультацию.')
    block = block.replace('Оставьте контакт — свяжусь с вами, чтобы уточнить вопрос и согласовать консультацию.', 'Оставьте имя и телефон — свяжусь с вами, чтобы уточнить вопрос и согласовать консультацию.')
    if only_form:
        block = block[block.index('<div class="contact-card"'):].removesuffix('</section>')
    return localize(block, page)

def breadcrumbs(page, name, service=False):
    middle = f'<a href="{link(page, "uslugi/")}">Услуги</a><span aria-hidden="true">/</span>' if service else ''
    return f'<nav class="breadcrumbs" aria-label="Хлебные крошки"><a href="{link(page, "")}">Главная</a><span aria-hidden="true">/</span>{middle}<span aria-current="page">{E(name)}</span></nav>'

def faq(items):
    return '<div class="faq-list">' + ''.join(f'<details><summary>{E(item["q"])}</summary><p>{E(item["a"])}</p></details>' for item in items) + '</div>'

def sidebar(page):
    group = ''.join(f'<a href="{link(page, "uslugi/" + s["slug"] + "/")}"' + (' aria-current="page"' if page == 'uslugi/' + s['slug'] + '/' else '') + f'>{E(s["name"])}</a>' for s in services)
    types = ''.join(f'<a href="{link(page, "uslugi/sudebnoe-predstavitelstvo/#" + anchor)}">{title}</a>' for title, anchor in [('Досудебное урегулирование', 'dosudebnoe'), ('Подготовка к суду', 'podgotovka'), ('Ведение дела в суде', 'vedenie')])
    return f'''<aside class="service-sidebar"><details class="service-menu" open><summary>Все услуги</summary><div><h2>Консультация и ведение дел</h2><nav aria-label="Направления права">{group}</nav><h2>Виды юридической помощи</h2><nav aria-label="Виды помощи">{types}</nav></div></details><div class="sidebar-contact"><p>Светлана Якунина</p><a href="tel:+79228921257">+7 922 892-12-57</a><p>Бузулук, ул. 1 Мая, 37а</p>{button(page)}</div></aside>'''

def quick_cards(page):
    items = [('trudovye-spory', 'Трудовой спор', 'M5 6h14v14H5z M9 6V3h6v3 M5 11h14'), ('dogovory', 'Проверить договор', 'M6 3h9l4 4v14H6z M14 3v5h5 M9 12h7 M9 16h7'), ('nedvizhimost', 'Недвижимость', 'M3 11l9-8 9 8 M6 9v12h12V9 M10 21v-7h4v7'), ('sudebnoe-predstavitelstvo', 'Претензия или суд', 'M12 3v18 M5 21h14 M4 7h16 M6 7l-3 7h6z M18 7l-3 7h6z')]
    return '<nav class="quick-services" aria-label="Быстрый выбор услуги">' + ''.join(f'<a class="quick-service" href="{link(page, "uslugi/" + slug + "/")}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="{path}"/></svg><span>{text}</span><span aria-hidden="true">↗</span></a>' for slug, text, path in items) + '</nav>'

def map_block():
    address = quote('Бузулук, улица 1 Мая, 37а')
    # Building coordinates verified in Yandex Maps for 1 Maya 37A on 2026-10-06.
    url = 'https://yandex.ru/maps/?rtext=~52.795892%2C52.266337&rtt=auto'
    embed = 'https://yandex.ru/map-widget/v1/?ll=52.266337%2C52.795892&z=17&pt=52.266337%2C52.795892%2Cpm2gnm'
    return f'''<section class="map-panel" aria-labelledby="map-title"><h2 id="map-title">Как добраться</h2><p>Бузулук, ул. 1 Мая, 37а. Время приёма уточняйте по телефону.</p><div class="map-placeholder"><p>Карта Яндекса загрузится по нажатию.</p><button class="button button-outline" type="button" data-show-map>Показать карту</button></div><iframe title="Карта: Бузулук, ул. 1 Мая, 37а" width="1000" height="340" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" data-src="{E(embed)}" hidden></iframe><a class="text-link" href="{E(url)}" target="_blank" rel="noopener noreferrer">Построить маршрут в Яндекс Картах ↗</a></section>'''

def home(page):
    hero = re.search(r'<section class="hero".*?</section>', source, re.S).group(0)
    hero = re.sub(r'<h1.*?</h1>', '<h1 id="hero-title"><span class="hero-line"><span>Юрист в Бузулуке.</span></span><span class="hero-line"><em>Светлана Якунина.</em></span></h1>', hero, flags=re.S)
    hero = re.sub(r'<p class="hero-description">.*?</p>', '<p class="hero-description">Договоры, трудовые споры, недвижимость и судебная работа. Более 20 лет опыта — разберём ваш вопрос и определим следующие действия.</p>', hero)
    hero = hero.replace('Обсудить мою ситуацию', 'Записаться на консультацию')
    hero = hero.replace('<div class="hero-visual">', '<div class="hero-visual"><img data-lawyer-portrait class="hero-portrait" alt="Светлана Валерьевна Якунина — юрист в Бузулуке" width="600" height="750" hidden>')
    hero = hero.replace('<img src="assets/legal-editorial.webp"', '<img data-portrait-placeholder src="assets/legal-editorial.webp"')
    pieces = [hero, quick_cards(page)]
    trust = re.search(r'<div class="trust-strip">.*?</div>', source, re.S).group(0)
    pieces.append(trust)
    for name in ('about', 'practice', 'approach', 'pricing', 'faq'):
        match = re.search(r'<section class="section [^"]*\b' + name + r'\b[^"]*".*?</section>', source, re.S)
        block = match.group(0)
        if name == 'about':
            block = block.replace('04 / Ваш юрист', '01 / Ваш юрист')
            block = block.replace('id="lawyer-photo" class="lawyer-photo"', 'id="lawyer-photo" class="lawyer-photo" width="360" height="450" loading="lazy"')
            block = block.replace('<a href="#contact" class="text-link">Связаться', '<a href="ob-yuriste/" class="text-link">Образование и практика')
        if name == 'practice':
            block = block.replace('01 / С чем помогу', '02 / С чем помогу')
        if name == 'pricing':
            block = block.replace('02 / Стоимость и результат', '04 / Стоимость и результат')
        if name == 'approach':
            block = block.replace('</ol>', '<li><span class="step-number">04</span><h3>Выполним согласованный этап</h3><p>Подготовим документы или продолжим работу по выбранному плану и обсудим следующий шаг.</p></li></ol>')
        pieces.append(block)
    pieces.append(contact_block(page))
    # The map lives on its own contact page to keep the mobile homepage short.
    pieces.append(f'<div class="home-route"><a href="{link(page, "kontakty/")}">Адрес, контакты и маршрут →</a></div>')
    return localize(''.join(pieces), page)

def service_body(page, s):
    sections = ''
    for index, section in enumerate(s['sections']):
        paragraphs = ''.join('<p>' + E(p) + '</p>' for p in section['paragraphs'])
        bullets = '<ul>' + ''.join('<li>' + E(p) + '</li>' for p in section.get('bullets', [])) + '</ul>' if section.get('bullets') else ''
        sections += f'<details class="service-section" open><summary><h2>{E(section["heading"])}</h2></summary><div class="service-section-copy">{paragraphs}{bullets}</div></details>'
    if s['slug'] == 'sudebnoe-predstavitelstvo':
        sections += '''<section class="help-types"><h2>Виды помощи по спору</h2><h3 id="dosudebnoe">Досудебное урегулирование</h3><p>Разбор требований и переписки, подготовка претензии или ответа, обсуждение возможного соглашения. Сначала нужно проверить, применим ли обязательный претензионный порядок к вашему вопросу.</p><h3 id="podgotovka">Подготовка к суду</h3><p>Оценка документов, определение предмета требований и подготовка процессуальных материалов в согласованном объёме. Важны даты, доказательства и полномочия представителя.</p><h3 id="vedenie">Ведение дела в суде</h3><p>Участие в согласованных этапах дела. До начала работы проверяются требования к представителю для конкретного суда и процесса. Результат рассмотрения определяет суд.</p></section>'''
    related = ''.join(f'<a href="{link(page, "uslugi/" + slug + "/")}">{E(by_slug[slug]["name"])} →</a>' for slug in s['related'] if slug in by_slug and slug != s['slug'])
    return f'''<div class="service-layout">{sidebar(page)}<article class="service-article">{breadcrumbs(page, s['name'], True)}<header class="service-intro"><p class="eyebrow">Светлана Якунина · Юрист · 20+ лет практики</p><h1>{E(s['h1'])}</h1><p class="detail-intro">{E(s['intro'])}</p><p class="service-price">{E(s['price'])}</p>{button(page, topic=s['topic'])}</header><div class="service-copy">{sections}</div><section class="service-faq"><h2>Вопросы перед обращением</h2>{faq(s['faq'])}</section><section class="related-services"><h2>Смежные услуги</h2>{related}</section><div class="service-bottom-cta"><h2>Обсудим ваш вопрос</h2><p>В первом обращении достаточно темы. Документы и время консультации согласуем отдельно.</p>{button(page, topic=s['topic'])}</div><p class="detail-author">Материал подготовлен для сайта Светланы Валерьевны Якуниной. Обновлено 6 октября 2026. Это описание услуги; выводы по вашей ситуации требуют изучения документов.</p></article></div>'''

def about_body(page):
    return '''<h1>Юрист Светлана Якунина в Бузулуке</h1><p class="detail-intro">Светлана Валерьевна Якунина. Более 20 лет юридического опыта в коммерческих и бюджетных организациях.</p><div class="about-profile"><img data-lawyer-portrait alt="Светлана Валерьевна Якунина" width="360" height="450" loading="lazy" hidden><div><h2>Практика</h2><p>Трудовые вопросы, договорная работа, недвижимость, подготовка претензий и процессуальных документов, судебное представительство в согласованном объёме. Опыт в строительстве, транспорте, государственном и частном здравоохранении помогает учитывать содержание документов и практические последствия решений.</p><p>Для организаций — договорные и кадровые документы, юридическое сопровождение задач, связанных с закупками по 44-ФЗ и 223-ФЗ. Объём работы определяется после разбора запроса.</p></div></div><h2>Образование</h2><dl class="credentials"><dt>Оренбургский государственный университет</dt><dd>Юрист. Гражданско-правовая специализация.</dd><dt>Бузулукский строительный колледж</dt><dd>Правоведение. Диплом с отличием.</dd></dl><h2>Как строится работа</h2><p>Сначала — обстоятельства и документы, затем — обоснованные действия. На первой консультации важно определить задачу, проверить исходные материалы и согласовать следующий шаг. По сложному вопросу требуется изучение документов; мгновенный вывод по одному сообщению может быть неполным.</p><h2>Участие в судебном деле</h2><p>На сайте указан статус юриста. Возможность участия в конкретном деле, требования к образованию и полномочиям представителя, состав документов и этапы сопровождения проверяются до заключения соглашения. Подготовка документов и участие в заседаниях могут быть разными задачами.</p>''' + button(page)

def prices_body(page):
    rows = [('Консультация', 'от 1 500 ₽', 'Первичный разбор вопроса и возможных действий.', 'konsultaciya'), ('Проверка документа', 'от 3 000 ₽', 'Разбор условий и рисков до принятия решения.', 'dogovory'), ('Судебное сопровождение', 'от 15 000 ₽', 'Работа по делу в согласованном объёме.', 'sudebnoe-predstavitelstvo')]
    table = ''.join(f'<tr><th scope="row"><a href="{link(page, "uslugi/" + slug + "/")}">{name}</a></th><td>{price}</td><td>{text}</td></tr>' for name, price, text, slug in rows)
    return f'''<h1>Стоимость услуг юриста в Бузулуке</h1><p class="detail-intro">Начальные цены — ориентир для первого обращения. Итоговую стоимость узнаете до начала работы.</p><div class="price-table-wrap"><table class="price-table"><caption>Основные форматы юридической помощи</caption><thead><tr><th scope="col">Услуга</th><th scope="col">Стоимость</th><th scope="col">Что обсуждаем</th></tr></thead><tbody>{table}</tbody></table></div><h2>От чего зависит стоимость</h2><p>От сложности задачи, количества и состояния документов, объёма подготовки, числа согласованных этапов и участия в деле. Подготовка отдельного документа и ведение дела не входят автоматически в цену первичной консультации.</p><h2>Внешние расходы</h2><p>Госпошлины, нотариальные услуги и другие внешние расходы оплачиваются отдельно. До начала работы уточняются необходимые действия и их объём. Отправка заявки не обязывает заказывать услугу и не назначает встречу автоматически.</p>{button(page)}'''

def questions_body(page):
    items = [{'q': 'Какие документы нужны для первой консультации?', 'a': 'В первом обращении достаточно темы. Для разбора подготовьте относящиеся к вопросу договоры, переписку, претензии и документы с важными датами. Конкретный список зависит от задачи.'},
             {'q': 'Что делать, если не выплатили зарплату?', 'a': 'Запишите даты, периоды и суммы, соберите трудовой договор, расчётные документы и переписку. Возможный порядок действий зависит от обстоятельств; его нужно определить после разбора материалов.'},
             {'q': 'Что проверить перед подписанием договора?', 'a': 'Условия оплаты, сроки, объём обязательств, порядок передачи результата, ответственность и приложения. Если формулировки непонятны, удобно обсудить проект до подписания.'},
             {'q': 'Как подготовиться к сделке с недвижимостью?', 'a': 'Соберите доступные документы об объекте, проект договора и информацию об участниках сделки. Перечень проверки зависит от объекта, сделки и вашей роли.'},
             {'q': 'Как узнать цену?', 'a': 'Опишите задачу и объём документов. Начальные цены опубликованы на странице стоимости, итоговый состав услуги согласуется до начала работы.'},
             {'q': 'Можно ли записаться через сайт?', 'a': 'Да. Оставьте имя и телефон, подтвердите согласие на передачу обращения. Получение заявки не означает автоматического назначения встречи: время согласуем в разговоре.'},
             {'q': 'Можно написать без формы?', 'a': 'Можно позвонить, связаться через MAX или email. Если используете чат сайта, сообщение передаётся юристу, а ответ может прийти позже.'}]
    return '<h1>Вопросы о юридической консультации в Бузулуке</h1><p class="detail-intro">Как подготовиться, выбрать услугу и согласовать работу.</p>' + faq(items) + f'<div class="service-bottom-cta">{button(page, "Задать свой вопрос")}</div>', items

def cookie_body(page):
    return f'''<h1>Cookie и статистика посещений</h1><p>На obz-pravo.ru используется Яндекс Метрика, счётчик № 113437050. Загрузка аналитики начинается только после отдельного разрешения в баннере. Отказ не ограничивает звонок, запись или переписку.</p><h2>Для чего нужна Метрика</h2><p>Для оценки посещений и действий на сайте: открытия чата, нажатия на телефон, MAX или email, отправки заявки и сообщения. Сайт не передаёт в параметры целей имя, телефон, содержание вопроса и закрытый ключ диалога. Вебвизор, карта кликов и запись форм выключены в инициализации счётчика.</p><h2>Хранилище текущей вкладки</h2><p>В sessionStorage сохраняются случайный идентификатор диалога, ключ доступа к собственной переписке, метки UTM/yclid, выбранная услуга и выбор аналитики. Это помогает продолжить обращение при переходе между страницами. Текст переписки не переносится в аналитические события.</p><h2>Как изменить выбор</h2><p>Нажмите «Настройки аналитики» в подвале и выберите «Разрешить» или «Без аналитики». После отказа новые цели сайта не отправляются. Если счётчик уже загрузился, для прекращения его работы в текущей странице обновите её после изменения выбора. Cookie внешнего сервиса можно удалить в настройках браузера.</p><h2>Внешняя карта</h2><p>Карта Яндекса загружается после нажатия «Показать карту» на странице контактов. При её открытии браузер обращается к сервису Яндекса. Вместо виджета можно воспользоваться ссылкой на маршрут.</p><p>Подробнее об обращениях и получателях: <a href="{link(page, 'politika-konfidencialnosti/')}">политика обработки персональных данных</a>. Информация о сервисе: <a href="https://yandex.ru/support/metrica/ru/general/cookie-usage" target="_blank" rel="noopener noreferrer">cookie Яндекс Метрики</a>.</p>'''

def page_schema(page, faq_items):
    person = {'@type': 'Person', '@id': ORIGIN + '/#person', 'name': 'Светлана Валерьевна Якунина', 'jobTitle': 'Юрист', 'url': ORIGIN + '/ob-yuriste/', 'alumniOf': [{'@type': 'CollegeOrUniversity', 'name': 'Оренбургский государственный университет'}, {'@type': 'EducationalOrganization', 'name': 'Бузулукский строительный колледж'}]}
    business = {'@type': 'LegalService', '@id': ORIGIN + '/#practice', 'name': 'Светлана Якунина — частная юридическая практика', 'url': ORIGIN + '/', 'telephone': '+79228921257', 'email': 'svetlana.veshta@mail.ru', 'address': {'@type': 'PostalAddress', 'streetAddress': 'ул. 1 Мая, 37а', 'addressLocality': 'Бузулук', 'addressRegion': 'Оренбургская область', 'addressCountry': 'RU'}, 'areaServed': {'@type': 'City', 'name': 'Бузулук'}, 'sameAs': ['https://web.max.ru/46523588'], 'founder': {'@id': ORIGIN + '/#person'}}
    graph = [business, person, {'@type': 'WebPage', '@id': ORIGIN + '/' + page, 'url': ORIGIN + '/' + page, 'name': PAGES[page][0], 'inLanguage': 'ru', 'dateModified': DATE, 'about': {'@id': ORIGIN + '/#practice'}}]
    business['geo'] = {'@type': 'GeoCoordinates', 'latitude': 52.795892, 'longitude': 52.266337}
    if page.startswith('uslugi/') and page != 'uslugi/':
        service = by_slug[page.split('/')[1]]
        graph.append({'@type': 'Service', '@id': ORIGIN + '/' + page + '#service', 'name': service['h1'], 'url': ORIGIN + '/' + page, 'serviceType': service['name'], 'provider': {'@id': ORIGIN + '/#practice'}, 'areaServed': {'@type': 'City', 'name': 'Бузулук'}})
    if page:
        crumbs = [{'@type': 'ListItem', 'position': 1, 'name': 'Главная', 'item': ORIGIN + '/'}]
        if page.startswith('uslugi/') and page != 'uslugi/': crumbs.append({'@type': 'ListItem', 'position': 2, 'name': 'Услуги', 'item': ORIGIN + '/uslugi/'})
        crumbs.append({'@type': 'ListItem', 'position': len(crumbs) + 1, 'name': PAGES[page][0].split(' — ')[0], 'item': ORIGIN + '/' + page})
        graph.append({'@type': 'BreadcrumbList', 'itemListElement': crumbs})
    if faq_items:
        graph.append({'@type': 'FAQPage', 'mainEntity': [{'@type': 'Question', 'name': x['q'], 'acceptedAnswer': {'@type': 'Answer', 'text': x['a']}} for x in faq_items]})
    return json.dumps({'@context': 'https://schema.org', '@graph': graph}, ensure_ascii=False).replace('</', '<\\/')

def document(page, body, has_form=False, faq_items=None, noindex=False):
    title, description = PAGES[page]
    assets = link(page, 'assets/')
    scripts = ['site-config.js', 'marketing.js', 'mobile-compact.js', 'app.js', 'site-ui.js', 'motion-native.js']
    if has_form: scripts += ['phone.js', 'callback.js']
    script_tags = ''.join(f'<script defer src="{assets}{name}?v={VERSION}"></script>' for name in scripts)
    icons = ''.join(f'<link rel="{rel}" href="{link(page, name)}?v={VERSION}"{extra}>' for rel, name, extra in [('icon', 'favicon.ico', ' sizes="any"'), ('icon', 'favicon.svg', ' type="image/svg+xml"'), ('icon', 'favicon-32.png', ' type="image/png" sizes="32x32"'), ('apple-touch-icon', 'apple-touch-icon.png', ' sizes="180x180"')])
    mobile = f'<nav class="mobile-actions" aria-label="Быстрая связь"><a href="tel:+79228921257">Позвонить</a><a data-profile-max href="https://web.max.ru/46523588" target="_blank" rel="noopener noreferrer">MAX</a><a href="{link(page, "zapis-na-priem/")}">Записаться <span aria-hidden="true">↗</span></a></nav>'
    root = link(page, '')
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>{E(title)}</title><meta name="description" content="{E(description)}"><link rel="canonical" href="{ORIGIN}/{page}"><meta name="robots" content="{'noindex,follow' if noindex else 'index,follow'}"><meta name="theme-color" content="#173f35"><meta property="og:type" content="website"><meta property="og:locale" content="ru_RU"><meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(description)}"><meta property="og:url" content="{ORIGIN}/{page}"><meta property="og:image" content="{ORIGIN}/assets/legal-editorial.webp"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{E(title)}"><meta name="twitter:description" content="{E(description)}"><meta name="twitter:image" content="{ORIGIN}/assets/legal-editorial.webp">{icons}<link rel="stylesheet" href="{assets}style.css?v={VERSION}"><script type="application/ld+json">{page_schema(page, faq_items or [])}</script>{script_tags}</head><body data-site-root="{root}" data-booking-url="{link(page, 'zapis-na-priem/')}" data-cookie-url="{link(page, 'cookie/')}">{header(page)}<main id="main">{body}</main>{localize(chat, page)}{mobile}{footer(page)}</body></html>'''

seo_text = []
for page in PAGES:
    faq_items = []
    has_form = page in ('', 'zapis-na-priem/', 'kontakty/')
    if not page:
        body = home(page)
        faq_items = [{'q': html.unescape(q), 'a': re.sub('<[^>]+>', '', html.unescape(a))} for q, a in re.findall(r'<summary>(.*?)</summary><p>(.*?)</p>', faq_source, re.S)]
    elif page.startswith('uslugi/') and page != 'uslugi/':
        s = by_slug[page.split('/')[1]]
        body, faq_items = service_body(page, s), s['faq']
        seo_text.append('# ' + s['h1'] + '\n\n' + s['intro'] + '\n\n' + '\n\n'.join('## ' + item['heading'] + '\n\n' + '\n\n'.join(item['paragraphs'] + item.get('bullets', [])) for item in s['sections']) + '\n\n## Вопросы\n\n' + '\n\n'.join('### ' + item['q'] + '\n\n' + item['a'] for item in s['faq']))
    else:
        if page == 'uslugi/':
            cards = ''.join(f'<article class="directory-card"><h2><a href="{link(page, "uslugi/" + s["slug"] + "/")}">{E(s["name"])}</a></h2><p>{E(s["intro"])}</p><p class="directory-price">{E(s["price"])}</p><a class="text-link" href="{link(page, "uslugi/" + s["slug"] + "/")}">Подробнее об услуге →</a></article>' for s in services)
            content = '<h1>Юридические услуги в Бузулуке</h1><p class="detail-intro">Выберите близкую ситуацию. Если пока не знаете, какая помощь нужна, начните с консультации.</p><div class="directory-grid">' + cards + '</div>'
        elif page == 'ob-yuriste/': content = about_body(page)
        elif page == 'stoimost/': content = prices_body(page)
        elif page == 'voprosy/': content, faq_items = questions_body(page)
        elif page == 'zapis-na-priem/': content = '<h1>Запись на консультацию юриста в Бузулуке</h1><p class="detail-intro">Оставьте имя и телефон. Время, формат и стоимость консультации согласуем при общении.</p><div class="booking-layout">' + contact_block(page, True) + '</div>'
        elif page == 'kontakty/': content = '<h1>Контакты юриста в Бузулуке</h1>' + contact_block(page) + map_block()
        elif page == 'cookie/': content = cookie_body(page)
        else:
            name = 'privacy' if page == 'politika-konfidencialnosti/' else 'consent'
            original = (ROOT / ('content/' + name + '-original.html')).read_text(encoding='utf-8')
            content = re.search(r'<main[^>]*>(.*?)</main>', original, re.S).group(1)
            content = re.sub(r'<a class="back-link".*?</a>', '', content, flags=re.S)
            content = content.replace('Метрика по умолчанию выключена. Если оператор подключит счётчик, аналитика применяется только после отдельного разрешения посетителя.', 'На сайте подключён счётчик Яндекс Метрики. Загрузка аналитики начинается только после отдельного разрешения посетителя.')
            content = localize(content, page)
        cls = 'utility-page form-page' if has_form else 'utility-page'
        body = f'<div class="section {cls}">{breadcrumbs(page, PAGES[page][0].split(" — ")[0])}{content}</div>'
    filename = DIST / page / 'index.html'
    filename.parent.mkdir(parents=True, exist_ok=True)
    filename.write_text(document(page, body, has_form, faq_items, page in ('politika-konfidencialnosti/', 'soglasie/', 'cookie/')), encoding='utf-8')

# Old HTML addresses work on the application server (301) and static Pages (refresh).
for old, new in OLD.items():
    (DIST / old).write_text(f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="robots" content="noindex,follow"><link rel="canonical" href="{ORIGIN}/{new}"><meta http-equiv="refresh" content="0;url={new}"><title>Страница переехала</title></head><body><p><a href="{new}">Перейти на актуальную страницу</a></p></body></html>', encoding='utf-8')
(DIST / 'redirects.json').write_text(json.dumps({'/' + old: '/' + new for old, new in OLD.items()} | {'/index.html': '/'}, ensure_ascii=False, indent=2), encoding='utf-8')
urls = [ORIGIN + '/' + page for page in PAGES if page not in ('politika-konfidencialnosti/', 'soglasie/', 'cookie/')]
(DIST / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + '\n'.join(f'<url><loc>{url}</loc><lastmod>{DATE}</lastmod></url>' for url in urls) + '\n</urlset>', encoding='utf-8')
(DIST / 'robots.txt').write_text('User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /server/\nDisallow: /private/\nDisallow: /redirects.json\nSitemap: https://obz-pravo.ru/sitemap.xml\n', encoding='utf-8')
(DIST / '404.html').write_text('''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Страница не найдена — ОБЗ Право</title><meta name="robots" content="noindex,follow"><link rel="icon" href="/favicon.svg"><style>body{margin:0;padding:10vh 24px;background:#f7f5ef;color:#173f35;font:17px/1.7 Arial}main{max-width:620px;margin:auto}h1{font:40px/1.2 Georgia}a{color:inherit}nav{display:flex;flex-wrap:wrap;gap:24px}</style></head><body><main><p>404</p><h1>Эта страница не найдена.</h1><p>Выберите услугу или свяжитесь с юристом по телефону +7 922 892-12-57.</p><nav><a href="https://obz-pravo.ru/">Главная</a><a href="https://obz-pravo.ru/uslugi/">Услуги</a><a href="tel:+79228921257">Позвонить</a></nav></main></body></html>''', encoding='utf-8')
home_text = home('')
home_text = re.sub(r'<form.*?</form>', '', home_text, flags=re.S)
home_text = re.sub(r'<h([1-3])[^>]*>', lambda m: '\n\n' + '#' * int(m[1]) + ' ', home_text)
home_text = re.sub(r'</(?:h[1-3]|p|li|section)>', '\n\n', home_text)
home_text = html.unescape(re.sub('<[^>]+>', ' ', home_text))
home_text = re.sub(r'[^\S\n]+', ' ', home_text)
home_text = re.sub(r'\n\s*\n(?:\s*\n)+', '\n\n', home_text).strip()
seo_text.insert(0, '# Главная — готовый текст\n\n' + home_text)
(ROOT / 'content/seo-texts-v3.md').write_text('\n\n---\n\n'.join(seo_text), encoding='utf-8')
template = '''{header}
<main id="main"><div class="service-layout">{sidebar}<article class="service-article">{breadcrumbs}
<h1>{h1}</h1><p>{intro}</p><p>{price}</p>{booking_cta}
{sections}<section><h2>Вопросы перед обращением</h2>{faq}</section>{related_services}{booking_cta}
</article></div></main>{chat}{mobile_actions}{footer}
'''
(ROOT / 'content/service-template.html').write_text(template, encoding='utf-8')
shutil.copytree(DIST, ROOT / 'docs', dirs_exist_ok=True)
print('Built', len(PAGES), 'canonical pages;', len(urls), 'indexable URLs; portable dist/docs synchronized.')
