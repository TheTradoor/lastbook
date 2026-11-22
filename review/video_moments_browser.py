"""Fork-only browser verification. Starts the real server with synthetic media.

Requires Python Playwright, its Chromium browser, ffmpeg, and Lastbook's Linux
requirements. Does not run the AI or use a real person's library.
"""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'review' / 'results'
OUT.mkdir(parents=True, exist_ok=True)
checks = []
errors = []
external = []


def check(name, condition=True):
    assert condition, name
    checks.append(name)
    print('PASS', name, flush=True)


def build_library(data):
    lib = data / 'library-data'
    for name in ('videos', 'pages', 'transcripts', 'collections', 'assets'):
        (lib / name).mkdir(parents=True)
    (data / 'derived').mkdir()
    target = lib / 'videos' / 'demo.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                    'color=c=0x253447:s=640x360:r=12:d=90', '-vf',
                    "drawtext=text='Workshop demonstration':fontcolor=white:fontsize=28:x=(w-tw)/2:y=h/2-30,drawtext=text='Synthetic test video':fontcolor=0xadc0d0:fontsize=16:x=(w-tw)/2:y=h/2+20",
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)], check=True)
    records = [{'id': 'demo-video', 'kind': 'video', 'path': 'videos/demo.mp4',
                'title': 'Workshop demonstration', 'publisher': 'Demo library', 'duration': 90,
                'collection': 'Demonstrations', 'category': 'repair', 'bytes': target.stat().st_size,
                'captions': ['transcripts/demo.vtt']},
               {'id': 'demo-manual', 'kind': 'html', 'path': 'pages/demo.html',
                'title': 'Workshop notes', 'publisher': 'Demo library', 'category': 'repair',
                'collection': 'Demonstrations'}]
    (lib / 'catalog.json').write_text(json.dumps(records))
    (lib / 'summary.json').write_text('{"resources":2}')
    (lib / 'pages/demo.html').write_text('<!doctype html><title>Workshop notes</title><p>Synthetic test content.</p>')
    (lib / 'transcripts/demo.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:11.999\nIntroduction to the demonstration.\n\n00:00:12.000 --> 00:00:30.999\nThe tools used in this example.\n\n00:00:31.000 --> 00:01:29.999\nA closer look at the assembly.\n')
    with sqlite3.connect(lib / 'search.sqlite') as con:
        con.execute('CREATE VIRTUAL TABLE pages USING fts5(doc_id UNINDEXED,title,collection,category,path UNINDEXED,page UNINDEXED,body,tokenize="unicode61")')


def exercise_saved_read_errors(page, base):
    target = base + '/#/saved'
    page.goto(target)
    page.get_by_role('heading', name='Saved', exact=True).wait_for()
    page.locator('.moments').wait_for()
    original = page.evaluate('Object.fromEntries(["sg.saved","sg.recent","sg.vprog"].map(k=>[k,localStorage.getItem(k)]))')
    recent = [{'key': 'd:demo-manual', 'title': 'Workshop notes', 'href': '#/read/demo-manual', 'sub': 'Manual'}]
    progress = {'demo-video': {'t': 31, 'd': 90, 'title': 'Workshop demonstration', 'at': 1}}

    def independent_sections(p):
        return (p.get_by_role('heading', name='Continue watching', exact=True).is_visible()
                and p.locator('#main a.vcard').is_visible()
                and p.get_by_role('heading', name='Recently opened', exact=True).is_visible())

    blocked = None
    try:
        page.evaluate('([recent,progress])=>{localStorage.setItem("sg.recent",JSON.stringify(recent));localStorage.setItem("sg.vprog",JSON.stringify(progress))}', [recent, progress])
        for raw in ('{broken', '{}', 'null', '42', '"text"', 'true'):
            page.evaluate('(raw)=>localStorage.setItem("sg.saved",raw)', raw)
            page.reload()
            page.get_by_role('alert').wait_for()
            check('unreadable Saved keeps history and progress: ' + raw,
                  page.get_by_role('alert').inner_text() == 'Saved items could not be read. Nothing was changed.'
                  and independent_sections(page)
                  and page.locator('#main a.row[href="#/read/demo-manual"]').is_visible()
                  and page.get_by_text('Nothing saved yet', exact=True).count() == 0)
            check('unreadable Saved bytes are unchanged: ' + raw, page.evaluate('localStorage.getItem("sg.saved")') == raw)

        page.evaluate('(raw)=>localStorage.setItem("sg.saved",raw)', original['sg.saved'])
        blocked = page.context.new_page()
        blocked.on('pageerror', lambda e: errors.append(str(e)))
        blocked.add_init_script('''
            window.originalSavedGet = Storage.prototype.getItem;
            window.originalSavedSet = Storage.prototype.setItem;
            window.savedWrites = [];
            Storage.prototype.getItem = function(key) {
                if (key === 'sg.saved') throw new DOMException('denied', 'SecurityError');
                return window.originalSavedGet.call(this, key);
            };
            Storage.prototype.setItem = function(key, value) {
                if (key === 'sg.saved') window.savedWrites.push(value);
                return window.originalSavedSet.call(this, key, value);
            };
        ''')
        blocked.goto(target)
        blocked.get_by_role('alert').wait_for()
        check('denied Saved reads keep history and progress available',
              independent_sections(blocked)
              and blocked.locator('#main a.row[href="#/read/demo-manual"]').is_visible()
              and blocked.get_by_text('Nothing saved yet', exact=True).count() == 0)
        check('denied Saved reads preserve the original list without writing',
              blocked.evaluate('window.originalSavedGet.call(localStorage,"sg.saved")') == original['sg.saved']
              and blocked.evaluate('window.savedWrites.length') == 0)
        blocked.emulate_media(color_scheme='light')
        blocked.screenshot(path=str(OUT/'saved-read-error-light.png'), full_page=True)
        blocked.emulate_media(color_scheme='dark')
        blocked.screenshot(path=str(OUT/'saved-read-error-dark.png'), full_page=True)
        blocked.get_by_role('button', name='Clear recent list', exact=True).click()
        blocked.get_by_text('Pages you open will appear here.', exact=True).wait_for()
        check('Clear recent list still works while Saved cannot be read',
              independent_sections(blocked)
              and blocked.get_by_role('alert').is_visible()
              and blocked.evaluate('localStorage.getItem("sg.recent")') == '[]'
              and blocked.evaluate('window.originalSavedGet.call(localStorage,"sg.saved")') == original['sg.saved']
              and blocked.evaluate('window.savedWrites.length') == 0)
        blocked.locator('#main a.vcard').click()
        blocked.wait_for_function('document.querySelector("#vid")?.readyState >= 1')
        blocked.locator('#resYes').click()
        blocked.wait_for_function('document.querySelector("#vid").currentTime >= 31 && !document.querySelector("#vid").paused')
        check('Continue watching still resumes video while Saved cannot be read', blocked.locator('#vid').evaluate('(v)=>v.currentTime') < 34)
        blocked.locator('#vid').evaluate('(v)=>v.pause()')
        blocked.evaluate('() => {Storage.prototype.getItem=window.originalSavedGet}')
        blocked.goto(target)
        blocked.get_by_role('heading', name='Saved', exact=True).wait_for()
        blocked.locator('.moments').wait_for()
        check('reopening Saved after reads recover restores all original moments',
              blocked.locator('#momentList li').count() == 3
              and blocked.get_by_role('alert').count() == 0
              and blocked.evaluate('localStorage.getItem("sg.saved")') == original['sg.saved']
              and blocked.evaluate('window.savedWrites.length') == 0)
    finally:
        if blocked:
            blocked.close()
        page.evaluate('(items)=>{for(const [key,value] of Object.entries(items)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value)}}', original)


def exercise(context, base):
    page = context.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))

    def watch(t=None):
        target = base + '/#/watch/demo-video' + ('' if t is None else '?t=' + str(t))
        if page.url == target:
            page.reload()
        else:
            page.goto(target)
        page.wait_for_function('(suffix) => {const v=document.querySelector("#vid");return v?.readyState >= 1 && v.getAttribute("src") === "/videos/demo.mp4" + suffix}', arg='' if t is None else '#t=' + str(t))
        page.locator('#cueQ').wait_for()

    def saved():
        page.goto(base + '/#/saved')
        page.get_by_role('heading', name='Saved', exact=True).wait_for()

    def moments():
        return page.evaluate('VideoMoments.readSaved().filter(VideoMoments.isMoment)')

    def add(t, label):
        page.locator('#vid').evaluate('(v,t)=>{v.pause();v.currentTime=t}', t)
        page.locator('#saveMoment').click()
        page.locator('#momentName').fill(label)
        page.locator('.moment-form button[type=submit]').click()
        assert 'saved on this device' in page.locator('#momentStatus').inner_text()

    watch()
    check('save enabled after real media metadata', page.locator('#saveMoment').is_enabled())
    check('actual media duration', page.locator('#vid').evaluate('(v)=>v.duration') == 90)
    page.locator('[data-save]').click()
    add(0, 'Introduction')
    add(12.8, 'Tools needed')
    add(31, 'Assembly detail')
    check('three positions are sorted in the player', page.locator('[data-moment-play]').evaluate_all('(a)=>a.map(x=>+x.dataset.momentPlay)') == [0,12,31])
    check('whole-video Saved entry remains', page.evaluate('VideoMoments.readSaved().some(x=>x.key==="v:demo-video")'))
    add(12.1, 'Tools and parts')
    check('same second edits without duplicating', len(moments()) == 3 and any(x['title'] == 'Tools and parts' for x in moments()))
    page.get_by_role('button', name='Rename Tools and parts', exact=True).click()
    check('rename field receives focus', page.locator('#momentName').evaluate('(e)=>document.activeElement===e'))
    page.locator('#momentName').fill('Tools checklist')
    page.locator('#momentName').press('Enter')
    check('keyboard rename persists time', any(x['title'] == 'Tools checklist' and x['time'] == 12 for x in moments()))
    page.get_by_role('button', name='Rename Introduction', exact=True).click()
    page.locator('#momentName').fill('Discard this edit')
    page.locator('#momentName').press('Escape')
    check('Escape cancels without changing data', moments()[-1]['title'] == 'Introduction' and page.locator('#momentName').count() == 0)
    page.locator('[data-moment-play="12"]').click()
    page.wait_for_function('!document.querySelector("#vid").seeking && !document.querySelector("#vid").paused')
    check('click seeks to the saved time', 12 <= page.locator('#vid').evaluate('(v)=>v.currentTime') < 14)
    page.locator('#vid').evaluate('(v)=>v.pause()')
    page.locator('#videoSpeed').select_option('1.5')
    check('playback speed remains usable', page.locator('#vid').evaluate('(v)=>v.playbackRate') == 1.5)
    page.locator('.cue[data-t="31"]').click()
    page.wait_for_function('!document.querySelector("#vid").seeking && !document.querySelector("#vid").paused')
    check('transcript seeking remains usable', 31 <= page.locator('#vid').evaluate('(v)=>v.currentTime') < 33)
    page.locator('#vid').evaluate('(v)=>v.pause()')
    page.wait_for_function('JSON.parse(localStorage.getItem("sg.vprog") || "{}")["demo-video"]?.t >= 31')
    watch()
    check('ordinary video opening still offers Resume', page.locator('#resYes').is_visible())
    saved()
    page.locator('.moments').wait_for()
    check('Saved includes all three moments', page.locator('#momentList li').count() == 3)
    page.locator('.moment-open[href$="?t=0"]').click()
    page.wait_for_function('document.querySelector("#vid")?.readyState >= 1')
    check('zero opens the beginning instead of Resume', page.locator('#resume').count() == 0 and page.locator('#vid').evaluate('(v)=>v.currentTime') < .5)
    saved()
    page.locator('.moment-open[href$="?t=31"]').click()
    page.wait_for_function('document.querySelector("#vid")?.readyState >= 1')
    page.wait_for_function('document.querySelector("#vid").currentTime >= 31')
    check('Saved reopens the exact media fragment', page.locator('#vid').evaluate('(v)=>v.currentTime') < 31.5)
    page.reload()
    page.locator('#momentList li').first.wait_for()
    page.wait_for_function('document.querySelector("#vid")?.readyState >= 1 && !document.querySelector("#vid").seeking')
    check('page reload retains moments', len(moments()) == 3)
    page.evaluate('() => {window.beforeFailure=localStorage.getItem("sg.saved");window.realSet=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k==="sg.saved")throw new DOMException("full","QuotaExceededError");return window.realSet.call(this,k,v)}}')
    page.locator('#vid').evaluate('(v)=>{v.pause();v.currentTime=45}')
    page.locator('#saveMoment').click()
    page.locator('#momentName').fill('Should not save')
    page.locator('.moment-form button[type=submit]').click()
    check('failed save shows error and keeps editor', 'left unchanged' in page.locator('#momentStatus').inner_text() and page.locator('#momentName').is_visible())
    check('failed save keeps original bytes', page.evaluate('localStorage.getItem("sg.saved")===window.beforeFailure'))
    page.evaluate('() => {Storage.prototype.setItem=window.realSet}')
    page.locator('.moment-form button[type=submit]').click()
    check('retry succeeds once storage recovers', len(moments()) == 4)
    page.get_by_role('button', name='Remove Should not save', exact=True).click()
    check('remove affects only selected moment', len(moments()) == 3)
    hostile='<img src=x onerror="window.bad=true"> 測試 & café'
    add(60, hostile)
    check('labels render as text', page.locator('#momentList img').count() == 0 and page.evaluate('window.bad===undefined'))
    page.get_by_role('button', name='Remove '+hostile, exact=True).click()
    add(63, '')
    check('blank optional name gets readable default', any(x['title']=='Moment at 1:03' for x in moments()))
    page.get_by_role('button', name='Remove Moment at 1:03', exact=True).click()
    page.evaluate('VideoMoments.save({id:"missing-video",title:"Another library"},8,"A saved place")')
    saved()
    page.locator('.moment-open.unavailable').wait_for()
    check('missing video is retained without a broken link', 'Not in this library' in page.locator('.moment-open.unavailable').inner_text() and page.locator('.moment-open.unavailable').evaluate('(e)=>e.tagName') == 'SPAN')
    page.get_by_role('button', name='Rename A saved place', exact=True).click()
    page.locator('#momentName').fill('Keep for later')
    page.locator('#momentName').press('Enter')
    page.get_by_role('button', name='Remove Keep for later', exact=True).click()
    check('missing-video entries remain editable and removable', len(moments()) == 3)
    watch(999)
    check('out-of-range position is explained', 'beyond the end' in page.locator('#momentStatus').inner_text())
    watch(12)
    page.wait_for_function('document.querySelector("#vid").readyState >= 2 && !document.querySelector("#vid").seeking')
    for platform in ('mac', 'win'):
        page.evaluate('(p)=>{document.documentElement.classList.remove("plat-mac","plat-win");document.documentElement.classList.add("plat-"+p)}',platform)
        for theme in ('light','dark'):
            page.emulate_media(color_scheme=theme)
            page.set_viewport_size({'width':1440,'height':1050})
            page.screenshot(path=str(OUT / f'player-{platform}-{theme}.png'),full_page=True)
            check(f'{platform} {theme} desktop has no horizontal overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.emulate_media(color_scheme='light')
    saved()
    page.locator('.moments').wait_for()
    page.screenshot(path=str(OUT/'saved-light.png'),full_page=True)
    page.emulate_media(color_scheme='dark')
    page.screenshot(path=str(OUT/'saved-dark.png'),full_page=True)
    watch(12)
    page.get_by_role('button',name='Rename Tools checklist',exact=True).click()
    page.locator('#momentName').fill('A'*120)
    page.locator('#momentName').press('Enter')
    for width in (320,375,640):
        page.set_viewport_size({'width':width,'height':900})
        page.screenshot(path=str(OUT/f'player-narrow-{width}.png'),full_page=True)
        check(f'{width}px long-label layout has no horizontal overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.get_by_role('button',name='Rename '+'A'*120,exact=True).click()
    page.locator('#momentName').fill('Tools checklist')
    page.locator('#momentName').press('Enter')
    page.set_viewport_size({'width':1440,'height':1050})
    exercise_saved_read_errors(page, base)
    check('no JavaScript page errors',not errors)
    return page


def main():
    with tempfile.TemporaryDirectory(prefix='lastbook-moments-') as folder:
        data=Path(folder)
        build_library(data)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        with open(OUT/'server.log','w') as log:
            server=subprocess.Popen([sys.executable,'-B','server.py','--data',str(data),'--port',str(port),'--no-index'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try:
                        with urlopen(base+'/api/health',timeout=1) as response:
                            if response.status==200: break
                    except OSError: time.sleep(.1)
                else: raise RuntimeError('test server did not start')
                with sync_playwright() as p:
                    profile=data/'browser-profile'
                    context=p.chromium.launch_persistent_context(str(profile),headless=True,viewport={'width':1440,'height':1050})
                    def route(request):
                        if request.request.url.startswith(base+'/'): request.continue_()
                        else:
                            external.append(request.request.url); request.abort()
                    context.route('**/*',route)
                    try:
                        page=exercise(context,base)
                    except Exception:
                        for i,page in enumerate(context.pages):
                            page.screenshot(path=str(OUT/f'failure-{i}.png'),full_page=True)
                        raise
                    finally: context.close()
                    context=p.chromium.launch_persistent_context(str(profile),headless=True)
                    page=context.new_page()
                    page.goto(base+'/#/saved')
                    page.locator('.moments').wait_for()
                    check('browser restart retains all named positions',page.locator('#momentList li').count()==3)
                    context.close()
                check('no external requests from the application',not external)
            finally:
                server.terminate(); server.wait(timeout=10)
                (OUT/'checks.json').write_text(json.dumps({'checks':checks,'errors':errors,'external_requests':external},indent=2))
    print(json.dumps({'passed':len(checks)}))


if __name__ == '__main__':
    main()
