"""Fork-only compatibility checks for PR #344 on main with saved moments.

Uses real Chromium media events and a synthetic library. No simulated media
events, personal library, AI runner, or external application requests.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
from video_moments_browser import build_library

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('LASTBOOK_WATCHED_RESULTS', ROOT / 'review' / 'results'))
OUT.mkdir(parents=True, exist_ok=True)
results, errors, external = [], [], []


def check(label, condition):
    assert condition, label


def boot(page, base):
    page.goto(base + '/#/videos/all')
    page.locator('#vg a.vcard').first.wait_for()


def watch(page, base, stamp=None):
    target = base + '/#/watch/demo-video' + ('' if stamp is None else '?t=' + str(stamp))
    if page.url == target:
        page.reload()
    else:
        page.goto(target)
    page.locator('#markWatched').wait_for()
    page.wait_for_function('document.querySelector("#vid")?.readyState >= 1 && !document.querySelector("#vid").seeking')
    page.locator('.cue[data-t="31"]').wait_for()


def seek(page, value):
    page.locator('#vid').evaluate('(v,t)=>{v.pause();v.currentTime=t}', value)
    page.wait_for_function('(t)=>{const v=document.querySelector("#vid");return !v.seeking && Math.abs(v.currentTime-t)<0.1}', arg=value)


def watched(page):
    return page.locator('#markWatched').get_attribute('aria-pressed') == 'true'


def mark_unwatched(page):
    if not watched(page):
        page.locator('#markWatched').click()
    page.locator('#markWatched').click()
    check('manual unwatched choice is explicit', page.evaluate('vwatched()["demo-video"] === false'))


def saved_moments(page):
    return page.evaluate('localStorage.getItem("sg.saved")')


def seed_moments(page):
    page.evaluate('''() => {
        const v={id:'demo-video',title:'Workshop demonstration'};
        VideoMoments.save(v,0,'Introduction');
        VideoMoments.save(v,31,'Assembly detail');
        VideoMoments.save(v,85,'Final detail');
    }''')


def open_saved(page, base, stamp):
    page.goto(base + '/#/saved')
    page.locator('.moment-open[href$="?t=' + str(stamp) + '"]').click()
    page.locator('#markWatched').wait_for()
    page.wait_for_function('(t)=>{const v=document.querySelector("#vid");return v?.readyState>=1 && !v.seeking && Math.abs(v.currentTime-t)<0.2}', arg=stamp)
    page.locator('.cue[data-t="31"]').wait_for()


def play_through(page, start, target):
    seek(page, start)
    page.locator('#vid').evaluate('(v)=>{v.playbackRate=4;return v.play()}')
    page.wait_for_function('(t)=>document.querySelector("#vid").currentTime>=t', arg=target)
    page.locator('#vid').evaluate('(v)=>v.pause()')


def assert_still_unwatched_after_reload(page, base):
    check('current button stays unwatched', not watched(page))
    check('no completion was stored', page.evaluate('vwatched()["demo-video"] !== true'))
    page.reload()
    page.locator('#markWatched').wait_for()
    page.wait_for_function('document.querySelector("#vid")?.readyState>=1')
    page.locator('.cue[data-t="31"]').wait_for()
    check('reload stays unwatched', not watched(page))
    page.goto(base + '/#/videos/all')
    page.locator('a.vcard').first.wait_for()
    check('video card stays unwatched', page.locator('a.vcard .vcheck').count() == 0)


def fresh_saved_jump(page, base):
    seed_moments(page)
    original = saved_moments(page)
    open_saved(page, base, 85)
    check('Saved opens at exact near-end time while paused', page.locator('#vid').evaluate('(v)=>v.paused && v.currentTime>=85 && v.currentTime<85.2'))
    assert_still_unwatched_after_reload(page, base)
    check('saved moments are unchanged', saved_moments(page) == original)


def fresh_player_jump(page, base):
    seed_moments(page)
    original = saved_moments(page)
    watch(page, base)
    page.locator('[data-moment-play="85"]').click()
    page.wait_for_function('!document.querySelector("#vid").seeking && document.querySelector("#vid").currentTime>=85')
    page.locator('#vid').evaluate('(v)=>v.pause()')
    check('jump did not reach the end', page.locator('#vid').evaluate('(v)=>v.currentTime<88'))
    assert_still_unwatched_after_reload(page, base)
    check('saved moments are unchanged', saved_moments(page) == original)


def fresh_paused_scrub(page, base):
    watch(page, base)
    seek(page, 85)
    check('video remains paused', page.locator('#vid').evaluate('(v)=>v.paused'))
    assert_still_unwatched_after_reload(page, base)


def explicit_paused_scrub(page, base):
    watch(page, base)
    mark_unwatched(page)
    seek(page, 85)
    assert_still_unwatched_after_reload(page, base)


def paused_scrub_to_end(page, base):
    watch(page, base)
    mark_unwatched(page)
    seek(page, 90)
    assert_still_unwatched_after_reload(page, base)


def crossing_by_playback(page, base):
    seed_moments(page)
    original = saved_moments(page)
    watch(page, base)
    play_through(page, 79, 83)
    check('playback crossing marks watched', watched(page) and page.evaluate('vwatched()["demo-video"] === true'))
    check('completion preserves saved moments', saved_moments(page) == original)
    page.goto(base + '/#/videos/all')
    page.locator('a.vcard .vcheck').wait_for()
    check('card shows watched', page.locator('a.vcard .vcheck').count() == 1)


def rewatch_after_manual_choice(page, base):
    watch(page, base)
    mark_unwatched(page)
    seek(page, 85)
    check('paused skip respects manual unwatched', not watched(page))
    play_through(page, 79, 83)
    check('rewinding then playing rearms completion', watched(page))


def end_by_playback(page, base):
    watch(page, base)
    mark_unwatched(page)
    seek(page, 87)
    page.locator('#vid').evaluate('(v)=>{v.playbackRate=2;return v.play()}')
    page.wait_for_function('document.querySelector("#vid").ended')
    check('playback to end marks watched', watched(page) and page.evaluate('vwatched()["demo-video"] === true'))


def manual_choice_and_saved_zero(page, base):
    seed_moments(page)
    original = saved_moments(page)
    watch(page, base)
    page.locator('#markWatched').click()
    open_saved(page, base, 0)
    check('zero moment starts at the beginning without Resume', page.locator('#resume').count() == 0 and page.locator('#vid').evaluate('(v)=>v.currentTime<0.2'))
    check('zero moment preserves explicit watched choice', watched(page))
    page.locator('#markWatched').click()
    open_saved(page, base, 31)
    check('later moment preserves explicit unwatched choice', not watched(page))
    check('manual choices preserve saved moments', saved_moments(page) == original)


def legacy_completed_progress(page, base):
    page.evaluate('localStorage.setItem("sg.vprog",JSON.stringify({"demo-video":{t:85,d:90,title:"Workshop demonstration",at:1}}))')
    watch(page, base)
    check('legacy completed progress remains watched', watched(page))
    seek(page, 31)
    page.goto(base + '/#/videos/all')
    page.locator('a.vcard').first.wait_for()
    check('rewinding does not erase legacy completion', page.locator('a.vcard .vcheck').count() == 1)


def persistence_beyond_recent_limit(page, base):
    seed_moments(page)
    original = saved_moments(page)
    watch(page, base)
    page.locator('#markWatched').click()
    seek(page, 31)
    page.goto(base + '/#/saved')
    page.locator('.moments').wait_for()
    page.evaluate('''() => {
        localStorage.setItem('sg.vprog','{}');
        for(let i=0;i<61;i++)setVprog('synthetic-'+i,{t:20,d:90,title:'Synthetic clip',at:i});
    }''')
    check('video is absent from the 60-item resume list', page.evaluate('!vprog()["demo-video"]'))
    open_saved(page, base, 31)
    check('watched survives resume-history pruning', watched(page))
    check('moments survive resume-history pruning', saved_moments(page) == original)


def readonly_saved(page, base):
    seed_moments(page)
    original = saved_moments(page)
    page.evaluate('''() => {
        window.savedSet=Storage.prototype.setItem;
        Storage.prototype.setItem=function(k,v){if(k==='sg.saved')throw new DOMException('full','QuotaExceededError');return window.savedSet.call(this,k,v)};
    }''')
    watch(page, base)
    page.locator('#markWatched').click()
    check('watched works while Saved is read-only', watched(page))
    page.locator('[data-moment-play="31"]').click()
    page.wait_for_function('document.querySelector("#vid").currentTime>=31')
    page.locator('#vid').evaluate('(v)=>v.pause()')
    check('moment jump works while Saved is read-only', page.locator('#vid').evaluate('(v)=>v.currentTime<34'))
    check('original saved bytes remain intact', saved_moments(page) == original)


def layout(page, base):
    seed_moments(page)
    watch(page, base, 31)
    for platform in ('mac','win'):
        page.evaluate('(p)=>{document.documentElement.classList.remove("plat-mac","plat-win");document.documentElement.classList.add("plat-"+p)}', platform)
        for theme in ('light','dark'):
            page.emulate_media(color_scheme=theme)
            page.set_viewport_size({'width':1440,'height':1050})
            page.screenshot(path=str(OUT/f'watched-{platform}-{theme}.png'), full_page=True)
            check(platform+' '+theme+' has both controls', page.locator('#markWatched').is_visible() and page.locator('#saveMoment').is_visible())
    for width in (320,375,640):
        page.set_viewport_size({'width':width,'height':900})
        page.screenshot(path=str(OUT/f'watched-narrow-{width}.png'), full_page=True)
        check(str(width)+' has no horizontal overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))


SCENARIOS = [fresh_saved_jump, fresh_player_jump, fresh_paused_scrub,
             explicit_paused_scrub, paused_scrub_to_end, crossing_by_playback,
             rewatch_after_manual_choice, end_by_playback, manual_choice_and_saved_zero,
             legacy_completed_progress, persistence_beyond_recent_limit, readonly_saved, layout]


def recording(browser, base):
    context=browser.new_context(viewport={'width':880,'height':1280},color_scheme='light',record_video_dir=str(OUT/'recordings'),record_video_size={'width':880,'height':1280})
    def route(r):
        if r.request.url.startswith(base+'/'):r.continue_()
        else:external.append(r.request.url);r.abort()
    context.route('**/*',route)
    page=context.new_page()
    page.on('pageerror',lambda e:errors.append(str(e)))
    boot(page,base)
    seed_moments(page)
    watch(page,base,31)
    page.locator('#markWatched').click()
    page.wait_for_timeout(900)
    page.locator('#markWatched').click()
    seek(page,85)
    check('recorded paused scrub stays unwatched',not watched(page))
    page.locator('#vid').hover()
    page.wait_for_timeout(1200)
    page.locator('[data-moment-play="31"]').click()
    page.wait_for_function('document.querySelector("#vid").currentTime>=31')
    page.locator('#vid').hover()
    page.wait_for_timeout(1000)
    seek(page,87)
    page.locator('#vid').hover()
    page.locator('#vid').evaluate('(v)=>v.play()')
    page.wait_for_function('document.querySelector("#vid").ended')
    check('recorded playback completion marks watched',watched(page))
    page.wait_for_timeout(1000)
    video=page.video
    context.close()
    video.save_as(str(OUT/'watched-moments-demo.webm'))
    video.delete()


def main(record_only=False):
    with tempfile.TemporaryDirectory(prefix='lastbook-watched-') as folder:
        data=Path(folder)
        build_library(data)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        with open(OUT/'watched-server.log','w') as log:
            server=subprocess.Popen([sys.executable,'-B','server.py','--data',str(data),'--port',str(port),'--no-index'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try:
                        with urlopen(base+'/api/health',timeout=1) as response:
                            if response.status==200:break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError('test server did not start')
                with sync_playwright() as p:
                    browser=p.chromium.launch(headless=True)
                    for scenario in ([] if record_only else SCENARIOS):
                        context=browser.new_context(viewport={'width':1440,'height':1050})
                        def route(r):
                            if r.request.url.startswith(base+'/'):r.continue_()
                            else:external.append(r.request.url);r.abort()
                        context.route('**/*',route)
                        page=context.new_page()
                        page.set_default_timeout(10000)
                        page.on('pageerror',lambda e:errors.append(str(e)))
                        boot(page,base)
                        try:
                            scenario(page,base)
                            results.append({'scenario':scenario.__name__,'passed':True})
                            print('PASS',scenario.__name__,flush=True)
                        except Exception as e:
                            results.append({'scenario':scenario.__name__,'passed':False,'error':str(e)})
                            print('FAIL',scenario.__name__,str(e),flush=True)
                            page.screenshot(path=str(OUT/(scenario.__name__+'-failure.png')),full_page=True)
                        finally:context.close()
                    recording(browser,base)
                    browser.close()
            finally:
                server.terminate();server.wait(timeout=10)
                (OUT/'watched-checks.json').write_text(json.dumps({'results':results,'errors':errors,'external_requests':external,'recording_only':record_only},indent=2))
    passed=sum(r['passed'] for r in results)
    print(json.dumps({'passed':passed,'total':len(results),'page_errors':len(errors),'external_requests':len(external)}))
    if passed!=len(results) or errors or external:raise SystemExit(1)


if __name__=='__main__':
    main('--record-only' in sys.argv)
