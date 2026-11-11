#!/usr/bin/env python3
"""気象庁「震度データベース検索」から地震回数のデータを取り直し、ページを作り直す。

GitHub Actions から週1回動かす（.github/workflows/update.yml）。
取得するもの（ページを作ったときと同じ条件）:
  1. 1990年1月1日〜データベース収録の最終日の、震度1以上の地震の年別・最大震度別の回数
  2. 同じ期間の、最大震度6弱以上（旧階級の震度6を含む）の地震の一覧
数字のつじつまが合わないときは、ファイルを書きかえずに終了する。
"""
import csv
import datetime
import io
import json
import pathlib
import sys
import urllib.request
import uuid
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
API = 'https://www.data.jma.go.jp/eqdb/data/shindo/api/'
DATE_JSON = 'https://www.data.jma.go.jp/eqdb/data/shindo/js/date.json'
UA = 'japan-earthquakes-updater (+https://github.com/Yoshihiro-Kitajima/japan-earthquakes)'
START = '1990-01-01'
JST = datetime.timezone(datetime.timedelta(hours=9))
KEYS = ['S1', 'S2', 'S3', 'S4', 'SA', 'SB', 'SC', 'SD', 'S7']
COLS = ['s1', 's2', 's3', 's4', 's5lower', 's5upper', 's6lower', 's6upper', 's7']
ZEN = str.maketrans('０１２３４５６７８９', '0123456789')


def fail(msg):
    print(f'中止: {msg}', file=sys.stderr)
    sys.exit(1)


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def post(fields):
    b = uuid.uuid4().hex
    body = b''.join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields)
    body += f'--{b}--\r\n'.encode()
    req = urllib.request.Request(API, data=body, headers={'Content-Type': f'multipart/form-data; boundary={b}', 'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def query(end, max_int, count):
    fields = [('mode', 'search'), ('dateTimeF[]', START), ('dateTimeF[]', '00:00'), ('dateTimeT[]', end), ('dateTimeT[]', '23:59'),
              ('mag[]', '0.0'), ('mag[]', '9.9'), ('dep[]', '000'), ('dep[]', '999'), ('epi[]', '99'), ('pref[]', '99'),
              ('city[]', '99'), ('station[]', '99'), ('obsInt', '1'), ('maxInt', max_int), ('additionalC', 'false'),
              ('Sort', 'S0'), ('Comp', 'C0'), ('seisCount', 'true' if count else 'false'), ('observed', 'false')]
    r = post(fields)
    if not isinstance(r.get('res'), list):
        fail(f'データベースの応答が想定と違います: {r.get("res")!r}')
    return r


def scale(y):
    return '旧階級' if y <= 1995 else ('1〜9月は旧階級、10月から現行' if y == 1996 else '現行')


def build_yearly(res, end):
    rows = [r for r in res if r.get('lb') != '合計']
    total = next((r for r in res if r.get('lb') == '合計'), None)
    if total is None:
        fail('年別回数に「合計」の行がありません')
    end_year = int(end[:4])
    years = [int(r['lb'].rstrip('年')) for r in rows]
    if years != list(range(1990, end_year + 1)):
        fail(f'年の並びが想定と違います: {years[:3]}…{years[-3:]}')
    out = []
    for r in rows:
        y = int(r['lb'].rstrip('年'))
        vals = [int(r[k]) for k in KEYS]
        if sum(vals) != int(r['SS']):
            fail(f'{y}年の最大震度別の合計が全体の数と合いません')
        per = f'{y}-01-01〜{end}' if y == end_year else f'{y}-01-01〜{y}-12-31'
        out.append([y] + vals + [int(r['SS']), per, scale(y)])
    for i, k in enumerate(KEYS + ['SS']):
        if sum(int(r[k]) for r in rows) != int(total[k]):
            fail(f'{k} の年の合計が「合計」の行と合いません')
    return out


def norm_int(s):
    s = s.replace('震度', '').translate(ZEN).strip()
    return s


def build_big(res, named):
    out = []
    for e in res:
        dt = e['ot'][:16]
        name = next((v for k, v in named.items() if dt.startswith(k)), '')
        out.append([dt.replace('/', '').replace(' ', '').replace(':', ''), dt[:4], dt, e['name'], e['lat'], e['lon'],
                    e['dep'].replace(' km', '').strip(), e['mag'], norm_int(e['maxI']), name])
    return out


def write_csv(path, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\r\n')
    w.writerow(header)
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding='utf-8', newline='')


def ja_date(d):
    y, m, dd = d.split('-')
    return f'{int(y)}年{int(m)}月{int(dd)}日'


def main():
    end = get_json(DATE_JSON)['en']
    datetime.date.fromisoformat(end)
    fetched = datetime.datetime.now(JST).date().isoformat()
    print(f'データベース収録の最終日: {end}　取得日: {fetched}')

    yr = query(end, '1', True)
    big = query(end, 'C', False)
    named = json.loads((DATA / 'named.json').read_text(encoding='utf-8'))
    yearly = build_yearly(yr['res'], end)
    bigrows = build_big(big['res'], named)

    # 年ごとの「6弱以上」の数と一覧の件数が合うか
    c = Counter(r[1] for r in bigrows)
    for r in yearly:
        y = str(r[0])
        if c.get(y, 0) != r[7] + r[8] + r[9]:
            fail(f'{y}年の最大震度6弱以上の数（{r[7] + r[8] + r[9]}）と一覧の件数（{c.get(y, 0)}）が合いません')
    if not bigrows:
        fail('大きな地震の一覧が空です')

    write_csv(DATA / 'yearly.csv', ['year'] + COLS + ['total', 'period', 'intensity_scale'], yearly)
    write_csv(DATA / 'big.csv', ['id', 'year', 'datetime', 'epicenter', 'lat', 'lon', 'depth_km', 'magnitude', 'max_intensity', 'jma_name'], bigrows)
    (DATA / 'meta.json').write_text(json.dumps({'source': '気象庁 震度データベース検索', 'start': START, 'end': end, 'fetched': fetched},
                                               ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    tpl = (ROOT / 'index.template.html').read_text(encoding='utf-8')
    html = (tpl.replace('{{END_YEAR}}', end[:4]).replace('{{END_DATE_JA}}', ja_date(end))
            .replace('{{FETCHED_JA}}', ja_date(fetched)))
    (ROOT / 'index.html').write_text(html, encoding='utf-8')
    (ROOT / 'sitemap.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url>\n    <loc>https://yoshihiro-kitajima.github.io/japan-earthquakes/</loc>\n'
        f'    <lastmod>{fetched}</lastmod>\n  </url>\n</urlset>\n', encoding='utf-8')
    print(f'年別 {len(yearly)} 年分、大きな地震 {len(bigrows)} 件、合計 {sum(r[10] for r in yearly)} 回')


if __name__ == '__main__':
    main()
