"""Pull hourly electricity (SCE) and gas (SoCalGas) use into JSON files for HA.

Neither utility has an API for customers, so this drives the account websites in
a real Chrome with a saved profile per site, waits for the page's own usage
request, and replays that request for the hours it is missing. Results go to
OUT_DIR/<site>.json, which the utility_usage component imports as hourly
statistics for the Energy dashboard.

  fetch_usage.py run [--site sce|socalgas] [--backfill-days N]
  fetch_usage.py login sce|socalgas      # interactive; for SCE's MFA code
  fetch_usage.py import-sce FILE...      # SCE CSV ("Download my data") or Excel (usage view) exports

`run` logs in with SITE_USERNAME / SITE_PASSWORD when the session has expired.
If the site then asks for anything else (an MFA code), it stops and records
status "needs_login"; run `login` over `ssh -t` to finish by hand.
"""
import argparse
import csv
import html
import json
import os
import pathlib
import re
import shutil
import sys
import time
import urllib.parse
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Los_Angeles')
HOME = pathlib.Path(os.environ.get('UTILITY_USAGE_HOME', pathlib.Path.home() / 'utility-usage'))
OUT_DIR = pathlib.Path(os.environ.get('UTILITY_USAGE_OUT', pathlib.Path.home() / 'homeassistant/utility-usage'))

SCE_PAGE = 'https://www.sce.com/mysce/usage'
SCE_API = 'dms.sce.com/myaccount/v1/usage'
SOCALGAS_PAGE = 'https://myaccount.socalgas.com/ui/ways-to-save/analyze-usage'
SOCALGAS_API = 'connectorsso/api/usage/daily'
SOCALGAS_FRAME = '/myAccount/wts/usage'
EYEONWATER_PAGE = 'https://www.eyeonwater.com/dashboard/'  # + the account email
EYEONWATER_API = '/api/2/residential/consumption'
EYEONWATER_SEARCH = 'https://www.eyeonwater.com/api/2/residential/new_search'

SITES = {
    'sce': {'unit': 'kWh', 'name': 'SCE electricity'},
    'socalgas': {'unit': 'CCF', 'name': 'SoCalGas gas'},
    'eyeonwater': {'unit': 'gal', 'name': 'Water'},
}
# SoCalGas answers ranges of up to ~90 days; stay well under it.
SOCALGAS_CHUNK_DAYS = 45
# Re-read the last few days on every run: both sites fill in late hours.
REFETCH_DAYS = 3

JS_POST = """async ([url, headers, body, credentials]) => {
  const r = await fetch(url, {method: 'POST', credentials, headers, body: JSON.stringify(body)});
  return {status: r.status, text: await r.text()};
}"""


class NeedsLogin(Exception):
    pass


def iso_hour(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:00:00Z')


def local_midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=TZ)


def hours_in_day(day):
    start = local_midnight(day).astimezone(timezone.utc)
    end = local_midnight(day + timedelta(days=1)).astimezone(timezone.utc)
    return int((end - start).total_seconds() // 3600)


def sce_day_points(day, rows):
    """SCE lists a day's hours in order (23 or 25 on DST days) with local, ambiguous
    times, so place them by position from local midnight."""
    rows = [r for r in rows if r.get('serviceMeasurementTypeCode', 'KWH_DEL') == 'KWH_DEL']
    if not rows or not rows[0].get('startDateTime', '').endswith(' 00:00'):
        return {}
    start = local_midnight(day).astimezone(timezone.utc)
    points = {}
    for i, row in enumerate(rows[:hours_in_day(day)]):
        try:
            value = float(row['value'])
        except (KeyError, TypeError, ValueError):
            continue
        points[iso_hour(start + timedelta(hours=i))] = round(value, 4)
    return points


def sce_csv_points(lines):
    """SCE's CSV export: preamble, then Date, period start, period end, Delivered,
    Received. Times are local and ambiguous at DST, so place each day's rows by
    position like the API's."""
    days = {}
    header = False
    for row in csv.reader(lines):
        row = [c.strip() for c in row]
        if not header:
            header = len(row) > 3 and row[0] == 'Date' and row[3] == 'Delivered'
            continue
        if len(row) < 4:
            continue
        try:
            day = datetime.strptime(row[0], '%m/%d/%Y').date()
            start = datetime.strptime(row[1], '%m/%d/%Y %I:%M%p')
        except ValueError:
            continue
        days.setdefault(day, []).append({'startDateTime': start.strftime('%Y-%m-%d %H:%M'), 'value': row[3]})
    if not header:
        raise ValueError('not an SCE usage CSV (no Date/Delivered header)')
    points = {}
    for day, rows in days.items():
        points.update(sce_day_points(day, rows))
    return points


def socalgas_points(payload):
    """SoCalGas pads the range with zero hours after LastUsage; drop those. Its
    local times skip DST changes, so hours that land on one UTC hour are added."""
    last = payload.get('LastUsage')
    points = {}
    for row in payload.get('HourlyUsage') or []:
        stamp = row.get('ForDate')
        if not stamp or (last and stamp > last):
            continue
        local = datetime.fromisoformat(stamp).replace(tzinfo=TZ)
        key = iso_hour(local)
        points[key] = round(points.get(key, 0) + float(row.get('Usage') or 0), 4)
    return points


def load(site):
    path = OUT_DIR / f'{site}.json'
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault('hours', {})
    data.update(site=site, unit=SITES[site]['unit'], name=SITES[site]['name'])
    return data


def save(site, data):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data['hours'] = dict(sorted(data['hours'].items()))
    tmp = OUT_DIR / f'.{site}.json.tmp'
    tmp.write_text(json.dumps(data, indent=0))
    tmp.replace(OUT_DIR / f'{site}.json')


def first_day_to_fetch(hours, today, backfill_days):
    if not hours:
        return today - timedelta(days=backfill_days)
    last = datetime.fromisoformat(max(hours).replace('Z', '+00:00')).astimezone(TZ).date()
    return min(last, today) - timedelta(days=REFETCH_DAYS)


# ---- Browser -----------------------------------------------------------------

def open_browser(pw, site, headless):
    profile = HOME / 'profiles' / site
    profile.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        str(profile), channel='chrome', headless=headless, locale='en-US',
        timezone_id='America/Los_Angeles', viewport={'width': 1280, 'height': 900})


def wait_for(predicate, seconds, page):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        page.wait_for_timeout(500)
    return predicate()


def visible(locator):
    try:
        return locator.first.is_visible()
    except Exception:
        return False


def fill_credentials(page, site):
    user = os.environ.get(f'{site.upper()}_USERNAME')
    password = os.environ.get(f'{site.upper()}_PASSWORD')
    if not user or not password:
        raise NeedsLogin(f'{site.upper()}_USERNAME / {site.upper()}_PASSWORD are not set')
    # Visible only: Cognito's hosted page carries a hidden second copy of its form.
    user_box = page.locator(':is(input[type=email], input[autocomplete=username], input[name*=user i], '
                            'input[name*=email i], input[id*=user i], input[id*=email i]) >> visible=true')
    pass_box = page.locator('input[type=password] >> visible=true')
    submit = page.get_by_role('button', name=re.compile(r'^\s*(log ?in|sign ?in|next|continue)\s*$', re.I))
    if not wait_for(lambda: visible(user_box) or visible(pass_box), 20, page):
        raise NeedsLogin('login form not found')
    # EyeOnWater hands off to Badger Meter's sign-in page, which asks again.
    for _ in range(3):
        if visible(user_box) and not user_box.first.input_value():
            user_box.first.fill(user)
            if not visible(pass_box):  # Okta can ask for the user name first
                submit.first.click()
                wait_for(lambda: visible(pass_box), 15, page)
        if not visible(pass_box):
            return
        pass_box.first.fill(password)
        remember = page.get_by_label(re.compile('remember', re.I))
        try:  # styled checkboxes hide the real input
            if remember.count() and not remember.first.is_checked():
                remember.first.check(force=True, timeout=5000)
        except Exception:
            pass
        next(b for b in submit.all() if b.is_visible()).click()
        page.wait_for_timeout(8000)


def reach_usage(page, site, url, captured):
    """Load the usage page and wait for its usage request, prodding the page
    (SITE_TRIGGERS) when it only asks on a click."""
    page.goto(url, wait_until='domcontentloaded')
    trigger = SITE_TRIGGERS.get(site)
    if wait_for(lambda: captured or 'login' in page.url.lower(), 30, page) and captured:
        return True
    for _ in range(4 if trigger else 0):
        if 'login' in page.url.lower():
            break
        trigger(page)
        if wait_for(lambda: captured, 10, page):
            return True
    return bool(captured)


def open_usage(page, site, url, captured, interactive):
    """Load the usage page; log in if it doesn't produce a usage request."""
    if reach_usage(page, site, url, captured):
        return
    if interactive:
        print(f'{site}: not logged in; trying saved credentials')
    try:
        fill_credentials(page, site)
    except NeedsLogin:
        if not interactive:
            raise
    if reach_usage(page, site, url, captured):
        return
    if not interactive:
        raise NeedsLogin(f'still not logged in after entering credentials ({page.url})')
    if sys.stdin.isatty():
        repl(page)
    else:
        enter_code_from_file(page)
    if not reach_usage(page, site, url, captured):
        raise NeedsLogin('usage request never appeared')


def post(frame, url, headers, body, credentials):
    result = frame.evaluate(JS_POST, [url, headers, body, credentials])
    if result['status'] in (401, 403):
        raise NeedsLogin(f'HTTP {result["status"]} from {url}')
    if result['status'] != 200:
        raise RuntimeError(f'HTTP {result["status"]} from {url}: {result["text"][:200]}')
    return json.loads(result['text'])


def pick_headers(headers, keep):
    return {k: v for k, v in headers.items() if k.lower() in keep}


# ---- SCE -----------------------------------------------------------------------

def fetch_sce(page, since, today, interactive, data):
    captured = {}

    def on_request(req):
        if SCE_API in req.url and req.method == 'POST' and not captured:
            captured.update(url=req.url, headers=req.headers, body=req.post_data_json)

    page.on('request', on_request)
    open_usage(page, 'sce', SCE_PAGE, captured, interactive)
    headers = pick_headers(captured['headers'], {'accept', 'content-type', 'oktauid'})
    base = dict(captured['body'], numberOfDays=None, frequencyField=60, usageDemandIndicator='usage')
    points = {}
    day = since
    while day < today:
        headers['X-Request-ID'] = str(uuid.uuid4())
        stamp = day.isoformat()
        payload = post(page, captured['url'], headers, dict(base, startDate=stamp, endDate=stamp), 'include')
        rows = payload.get('viewUsageDetails') or []
        if not rows and day >= today - timedelta(days=REFETCH_DAYS + 1):
            break  # not published yet
        points.update(sce_day_points(day, rows))
        day += timedelta(days=1)
        page.wait_for_timeout(400)
    return points


# ---- SoCalGas ----------------------------------------------------------------

def socalgas_frame(page):
    return next((f for f in page.frames if SOCALGAS_FRAME in f.url), None)


def socalgas_click_daily(page):
    """The analyze-usage iframe only calls usage/daily when Daily is chosen. Its
    icon is a font ligature, so without the font the link reads "calendar_today Daily"."""
    frame = socalgas_frame(page)
    if frame:
        frame.evaluate("""() => {
          const link = [...document.querySelectorAll('a')]
            .find(a => /\\bDaily\\s*$/.test(a.innerText) && a.offsetParent);
          if (link) link.click();
        }""")


SITE_TRIGGERS = {'socalgas': socalgas_click_daily}


def fetch_socalgas(page, since, today, interactive, data):
    captured = {}

    def on_request(req):
        if SOCALGAS_API in req.url and req.method == 'POST' and not captured:
            captured.update(url=req.url, headers=req.headers, body=req.post_data_json)

    page.on('request', on_request)
    open_usage(page, 'socalgas', SOCALGAS_PAGE, captured, interactive)
    frame = socalgas_frame(page)
    headers = pick_headers(captured['headers'], {'accept', 'content-type', 'accesstoken', 'portaltype', 'module'})
    base = dict(captured['body'])
    cycle = dict(base.pop('BillCycle') or {})
    # CCF scales the readings (therms per CCF); 1 returns plain CCF.
    cycle.update(CCF=1)
    cycle.pop('Title', None)
    points = {}
    start = since
    while start < today:
        end = min(start + timedelta(days=SOCALGAS_CHUNK_DAYS), today)
        body = dict(base, BillCycle=dict(cycle, FromDate=f'{start}T00:00:00', ToDate=f'{end}T00:00:00',
                                         BillDays=str((end - start).days)))
        payload = post(frame, captured['url'], headers, body, 'same-origin')
        code = payload.get('Code')
        if code not in (None, 200):
            # 701: the range is older than the tool keeps. Anything else is unexpected.
            if code != 701:
                raise RuntimeError(f'SoCalGas code {code}: {payload.get("Message")}')
        else:
            points.update(socalgas_points(payload))
        start = end
        page.wait_for_timeout(400)
    return points


# ---- EyeOnWater ----------------------------------------------------------------

def eyeonwater_points(payload):
    """Hourly gallons, newest first, in local time. The repeated fall-back hour
    is already one row; a skipped spring hour lands on the next and is added."""
    points = {}
    for series in (payload.get('timeseries') or {}).values():
        for row in series.get('series') or []:
            if row.get('value') is None or row.get('unit', 'GAL') != 'GAL':
                continue
            local = datetime.strptime(row['date'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ)
            key = iso_hour(local)
            points[key] = round(points.get(key, 0) + float(row['value']), 3)
    return points


def fetch_eyeonwater(page, since, today, interactive, data):
    captured = {}

    def on_request(req):
        if EYEONWATER_API in req.url and req.method == 'POST' and not captured:
            captured.update(url=req.url, body=req.post_data_json)

    page.on('request', on_request)
    url = EYEONWATER_PAGE + urllib.parse.quote(os.environ.get('EYEONWATER_USERNAME', ''), safe='')
    open_usage(page, 'eyeonwater', url, captured, interactive)
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
    body = captured['body']
    for key in ('perma_link', 'title'):
        body['params'].pop(key, None)
    body['params'].update(aggregate='hourly', units='GAL', perspective='billing', compare=False)
    # Meter flags (Leak, ReverseFlow, Tamper, ...) and battery, as the integration reads them.
    found = post(page, EYEONWATER_SEARCH, headers, {'query': body['query']['query']}, 'include')
    register = found['elastic_results']['hits']['hits'][0]['_source'].get('register_0') or {}
    data['flags'] = register.get('flags') or {}
    data['battery'] = (register.get('battery') or {}).get('level')
    points = {}
    day = since
    while day <= today:
        body['params']['date'] = f'{day.month}/{day.day}/{day.year}'
        points.update(eyeonwater_points(post(page, captured['url'], headers, body, 'include')))
        day += timedelta(days=1)
        page.wait_for_timeout(300)
    return points


FETCHERS = {'sce': fetch_sce, 'socalgas': fetch_socalgas, 'eyeonwater': fetch_eyeonwater}


# ---- Interactive login ---------------------------------------------------------

CODE_FILE = HOME / 'mfa-code'


def enter_code_from_file(page, minutes=10):
    """Without a terminal (e.g. Claude Code's `!`), wait for the MFA code in
    CODE_FILE, type it, and submit."""
    # Okta names both the password and the code field credentials.passcode;
    # only the code one is visible text.
    box = page.locator(':is(input[autocomplete=one-time-code], input[name*=code i], input[placeholder*=code i])'
                       ':not([type=password]) >> visible=true')
    if not wait_for(lambda: visible(box), 20, page):
        page.screenshot(path=str(HOME / 'login.png'))
        print('  fields:', page.evaluate(JS_LIST)[:40], flush=True)
        raise NeedsLogin(f'no code field on {page.url}')
    CODE_FILE.unlink(missing_ok=True)
    print(f'Waiting {minutes} min for the code: echo CODE > {CODE_FILE}', flush=True)
    if not wait_for(lambda: CODE_FILE.exists() and CODE_FILE.read_text().strip(), minutes * 60, page):
        raise NeedsLogin('no MFA code given')
    code = CODE_FILE.read_text().strip()
    CODE_FILE.unlink(missing_ok=True)
    box.first.fill(code)
    remember = page.get_by_label(re.compile('remember|trust|don.t ask', re.I))
    try:
        if remember.count() and not remember.first.is_checked():
            remember.first.check(force=True, timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(2000)
    verify = page.get_by_role('button', name=re.compile(r'verify|submit|continue', re.I))
    if visible(verify):  # some forms submit as soon as the last digit is in
        verify.first.click()
    elif visible(box):
        box.first.press('Enter')
    page.wait_for_timeout(10000)
    page.screenshot(path=str(HOME / 'login.png'))
    print(f'Code submitted; now at {page.url.split("?")[0]}', flush=True)
    text = page.inner_text('body')
    for line in text.splitlines():
        if re.search(r'invalid|incorrect|expired|error|try again|code', line, re.I):
            print('  page:', line.strip()[:120], flush=True)
    # Session-only cookies (expires -1) vanish when the browser closes.
    jar = page.context.cookies()
    session = sorted({c['name'] for c in jar if c['expires'] == -1 and 'sce' in c['domain']})
    print(f'  {len(jar)} cookies; session-only on sce: {", ".join(session[:20])}', flush=True)


JS_LIST = """() => {
  const out = [];
  document.querySelectorAll('input, button, a, select, [role=button]').forEach(el => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility === 'hidden') return;
    if (el.type === 'hidden') return;
    el.setAttribute('data-uu', out.length);
    const label = (el.labels && el.labels[0] && el.labels[0].innerText) || el.getAttribute('aria-label')
      || el.placeholder || el.innerText || el.value || el.name || '';
    out.push(`${el.tagName.toLowerCase()}${el.type ? '[' + el.type + ']' : ''} ${label.trim().replace(/\\s+/g, ' ').slice(0, 70)}`);
  });
  return out;
}"""


def repl(page):
    shot = HOME / 'login.png'
    print('Finish logging in. Commands: c N (click), t N TEXT (type), enter, wait, done.')
    print(f'A screenshot of the page is saved to {shot} after each step.')
    while True:
        page.wait_for_timeout(1500)
        page.screenshot(path=str(shot))
        print(f'\n{page.title()} — {page.url.split("?")[0]}')
        for i, item in enumerate(page.evaluate(JS_LIST)):
            if i < 60:
                print(f'  {i:2} {item}')
        try:
            cmd = input('> ').strip()
        except EOFError:
            return
        if cmd == 'done':
            return
        if cmd == 'enter':
            page.keyboard.press('Enter')
        elif cmd == 'wait':
            page.wait_for_timeout(5000)
        elif m := re.fullmatch(r'c (\d+)', cmd):
            page.locator(f'[data-uu="{m[1]}"]').click()
        elif m := re.fullmatch(r't (\d+) (.+)', cmd):
            page.locator(f'[data-uu="{m[1]}"]').fill(m[2])
        else:
            print('?')


# ---- Main ------------------------------------------------------------------------

def run_site(pw, site, backfill_days, interactive):
    data = load(site)
    today = datetime.now(TZ).date()
    since = first_day_to_fetch(data['hours'], today, backfill_days)
    data['checked'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    # SoCalGas turns headless Chrome away at login, so run a headed one; main()
    # supplies a virtual display (Xvfb) when there's no real one.
    context = open_browser(pw, site, headless=not os.environ.get('DISPLAY'))
    try:
        page = context.pages[0] if context.pages else context.new_page()
        points = FETCHERS[site](page, since, today, interactive, data)
        data['hours'].update(points)
        data.update(status='ok', message=f'{len(points)} hours read from {since}')
        if data['hours']:
            data['data_through'] = max(data['hours'])
        data['last_success'] = data['checked']
    except NeedsLogin as exc:
        data.update(status='needs_login', message=str(exc))
    except Exception as exc:  # keep the old hours; report the failure to HA
        data.update(status='error', message=f'{type(exc).__name__}: {exc}'[:300])
    finally:
        context.close()
    save(site, data)
    print(f'{site}: {data["status"]} — {data["message"]}')
    return data['status'] == 'ok'


def load_secrets():
    """systemd passes secrets.env as the environment; read it for manual runs too."""
    try:
        lines = (HOME / 'secrets.env').read_text().splitlines()
    except OSError:
        return
    for line in lines:
        key, sep, value = line.partition('=')
        if sep and key.strip() and not key.lstrip().startswith('#'):
            os.environ.setdefault(key.strip(), value.strip().strip('\'"'))


def xlsx_rows(path):
    """Cell text of an .xlsx's first sheet, row by row (the usage exports are tiny)."""
    book = zipfile.ZipFile(path)
    names = book.namelist()
    strings = []
    if 'xl/sharedStrings.xml' in names:
        for item in re.findall(r'<si>(.*?)</si>', book.read('xl/sharedStrings.xml').decode(), re.S):
            strings.append(html.unescape(''.join(re.findall(r'<t[^>]*>([^<]*)</t>', item))))
    rows = []
    for row in re.findall(r'<row[^>]*>(.*?)</row>', book.read('xl/worksheets/sheet1.xml').decode(), re.S):
        cells = []
        for attrs, body in re.findall(r'<c([^>]*)>(.*?)</c>', row, re.S):
            value = re.search(r'<v>([^<]*)</v>', body)
            if value:
                cells.append(strings[int(value[1])] if 't="s"' in attrs else value[1])
            else:
                text = re.search(r'<t[^>]*>([^<]*)</t>', body)
                cells.append(html.unescape(text[1]) if text else '')
        rows.append(cells)
    return rows


def sce_xlsx_points(rows):
    """SCE's usage-view Excel export: "Range : Aug-04-2026 Sep-01-2026", then either
    Date/Total Usage (daily kWh) or, for one day, Time/Total Usage (hourly).
    Returns (hourly points, {day: daily kWh})."""
    rng = next((r[0] for r in rows if r and r[0].startswith('Range')), '')
    ends = [datetime.strptime(d, '%b-%d-%Y').date() for d in re.findall(r'[A-Z][a-z]{2}-\d{2}-\d{4}', rng)]
    if not ends:
        raise ValueError('not an SCE usage export (no Range line)')
    kind = next((r[0] for r in rows if r and r[0] in ('Date', 'Time')), None)
    data = [r for r in rows if len(r) > 1 and re.match(r'^([A-Z][a-z]{2} \d{2}|\d{1,2}:\d{2} [AP]M)', r[0])]
    if kind == 'Time':
        ordered = [{'startDateTime': datetime.strptime(r[0].strip(), '%I:%M %p').strftime(f'{ends[0]} %H:%M'), 'value': r[1]}
                   for r in data]
        # On the fall-back day the export lists 1 AM once but its Totals row counts
        # both; put the difference back as the second 1 AM.
        total = next((r[1] for r in rows if r and r[0] == 'Totals' and len(r) > 1), '')
        if hours_in_day(ends[0]) == 25 and len(ordered) == 24 and re.match(r'[\d.]+', total):
            missing = float(re.match(r'[\d.]+', total)[0]) - sum(float(r['value']) for r in ordered)
            ordered.insert(2, {'startDateTime': f'{ends[0]} 01:00', 'value': f'{max(missing, 0):.3f}'})
        return sce_day_points(ends[0], ordered), {}
    daily = {}
    for r in data:
        label = r[0][:6]
        for year in sorted({d.year for d in ends}):
            day = datetime.strptime(f'{label} {year}', '%b %d %Y').date()
            if ends[0] <= day <= ends[-1]:
                daily[day] = round(float(r[1]), 3)
    return {}, daily


def import_sce(paths):
    """Hourly rows replace what's there. A daily-only total goes in as one value at
    local midnight, and only for a day with no hourly data."""
    data = load('sce')
    points, daily = {}, {}
    for path in paths:
        if str(path).lower().endswith('.xlsx'):
            hourly, days = sce_xlsx_points(xlsx_rows(path))
            points.update(hourly)
            daily.update(days)
        else:
            points.update(sce_csv_points(pathlib.Path(path).read_text(encoding='utf-8-sig').splitlines()))
    data['hours'].update(points)
    per_day = {}
    for stamp in data['hours']:
        local = datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(TZ).date()
        per_day[local] = per_day.get(local, 0) + 1
    added = 0
    for day, kwh in daily.items():
        if per_day.get(day, 0) <= 1:
            data['hours'][iso_hour(local_midnight(day))] = kwh
            added += 1
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    data.update(status='ok', checked=now, last_success=now, data_through=max(data['hours']),
                message=f'{len(points)} hours and {added} daily totals imported from {len(paths)} file(s)')
    save('sce', data)
    print(f'sce: {data["message"]}; {len(data["hours"])} values in total, through {data["data_through"]}')
    return 0


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ['import-sce']:
        return import_sce(args[1:])
    if not os.environ.get('DISPLAY') and shutil.which('xvfb-run'):
        os.execvp('xvfb-run', ['xvfb-run', '-a', '-s', '-screen 0 1280x900x24',
                               sys.executable, '-u', os.path.abspath(__file__), *args])
    load_secrets()
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='cmd', required=True)
    run = sub.add_parser('run')
    run.add_argument('--site', choices=SITES, action='append')
    run.add_argument('--backfill-days', type=int, default=365)
    login = sub.add_parser('login')
    login.add_argument('site', choices=SITES)
    login.add_argument('--backfill-days', type=int, default=365)
    args = parser.parse_args(argv)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        if args.cmd == 'login':
            return 0 if run_site(pw, args.site, args.backfill_days, interactive=True) else 1
        ok = [run_site(pw, site, args.backfill_days, interactive=False) for site in (args.site or SITES)]
    return 0 if all(ok) else 1


if __name__ == '__main__':
    sys.exit(main())
