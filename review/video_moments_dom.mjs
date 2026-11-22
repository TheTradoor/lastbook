// Supplementary DOM/event checks with the shipped HTML and JavaScript.
// Run after npm install --no-save jsdom@26.1.0. No network is used by this test.
// Media metadata/playback and layout observers are stubbed. This is not a
// substitute for the real-browser verification in video_moments_browser.py.
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { JSDOM, VirtualConsole } from 'jsdom';
import { runInContext } from 'node:vm';

const source = name => readFileSync(new URL('../web/' + name, import.meta.url), 'utf8');
const results = [], faults = [], requests = [];
const video = { id: 'demo-video', title: 'Workshop demonstration', kind: 'video', path: 'videos/demo.mp4', duration: 90, publisher: 'Demo library' };
const legacy = { key: 'v:demo-video', title: video.title, href: '#/watch/demo-video', sub: 'Video' };
const records = {
  '/api/doc/demo-video': video,
  '/api/topics': [],
  '/api/transcript/demo-video': { source: 'captions', cues: [{ t: 0, text: 'Introduction' }, { t: 12, text: 'Tools' }, { t: 31, text: 'Assembly' }] },
  '/api/videos/related/demo-video': [],
};
const console = new VirtualConsole();
console.on('jsdomError', e => faults.push(e.message));
let dom, w, d;
function check(name, value = true) {
  assert.ok(value, name); results.push(name); process.stdout.write('PASS ' + name + '\n');
}
async function open(saved = [legacy], progress = {}) {
  dom?.window.close();
  dom = new JSDOM(source('index.html'), { url: 'http://lastbook.test/#/watch/demo-video', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: console });
  w = dom.window; d = w.document;
  w.localStorage.setItem('sg.saved', JSON.stringify(saved));
  w.localStorage.setItem('sg.vprog', JSON.stringify(progress));
  w.MapView = { stop() {} };
  w.ResizeObserver = w.IntersectionObserver = class { observe() {} disconnect() {} };
  w.matchMedia = () => ({ matches: true, addEventListener() {} });
  w.scrollTo = () => {};
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.fetch = async url => {
    requests.push(String(url));
    if (!String(url).startsWith('/api/')) throw Error('Unexpected request: ' + url);
    return new Response(JSON.stringify(records[url] ?? {}), { status: url in records ? 200 : 404, headers: { 'content-type': 'application/json' } });
  };
  const proto = w.HTMLMediaElement.prototype;
  Object.defineProperties(proto, { duration: { get() { return 90 } }, readyState: { get() { return this._ready ?? 1 } } });
  proto.play = function () { this.dispatchEvent(new w.Event('play')); return Promise.resolve() };
  proto.pause = function () { this.dispatchEvent(new w.Event('pause')) };
  for (const script of ['plat.js', 'words.js', 'video-moments.js', 'app.js'])
    runInContext(source(script), dom.getInternalVMContext(), { filename: script });
  for (let i = 0; i < 50 && !d.querySelector('#cueQ'); i++) await new Promise(r => setTimeout(r, 2));
  assert.ok(d.querySelector('#cueQ'), d.querySelector('#main').textContent);
  await new Promise(r => setTimeout(r, 15));
}
const $ = selector => d.querySelector(selector);
const moments = () => w.VideoMoments.readSaved().filter(w.VideoMoments.isMoment);
const submit = () => $('.moment-form').dispatchEvent(new w.Event('submit', { bubbles: true, cancelable: true }));
const click = selector => { assert.ok($(selector), selector); $(selector).click() };
async function go(hash) { w.history.replaceState({}, '', hash); await w.eval('route()') }
function add(time, name) {
  $('#vid').currentTime = time; click('#saveMoment'); $('#momentName').value = name; submit();
}

await open();
check('save enabled with ready media metadata', !$('#saveMoment').disabled);
add(0, 'Introduction'); add(12.8, 'Tools needed'); add(31, 'Assembly detail');
check('multiple moments are ordered by position', [...d.querySelectorAll('[data-moment-play]')].map(x => +x.dataset.momentPlay).join() === '0,12,31');
check('whole-video entry stays unchanged', JSON.stringify(w.VideoMoments.readSaved().at(-1)) === JSON.stringify(legacy));
add(12.1, 'Tools checklist');
check('same second opens rename without creating a duplicate', moments().length === 3 && moments().find(x => x.time === 12).title === 'Tools checklist');
click('[data-moment-edit="m:demo-video:12"]');
check('name field gets keyboard focus', d.activeElement === $('#momentName'));
$('#momentName').value = 'Replacement';
$('.moment-form').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
check('Escape cancels editing and returns focus', !$('#momentName') && d.activeElement.dataset.momentEdit === 'm:demo-video:12' && moments().find(x => x.time === 12).title === 'Tools checklist');
click('[data-moment-edit="m:demo-video:12"]'); $('#momentName').value = 'Tools and parts'; submit();
check('renaming keeps the position', moments().find(x => x.time === 12).title === 'Tools and parts');
click('[data-moment-play="31"]');
check('player row requests the exact seek', $('#vid').currentTime === 31);
$('#videoSpeed').value = '1.5'; $('#videoSpeed').dispatchEvent(new w.Event('change'));
check('playback speed handler still works', $('#vid').playbackRate === 1.5);
click('.cue[data-t="12"]');
check('transcript seek handler still works', $('#vid').currentTime === 12);
$('#vid').currentTime = 31;
await go('#/saved');
check('Saved lists all moments', d.querySelectorAll('#momentList li').length === 3);
check('Saved links retain exact times including zero', [...d.querySelectorAll('.moment-open')].map(x => x.getAttribute('href')).sort().join() === ['#/watch/demo-video?t=0', '#/watch/demo-video?t=12', '#/watch/demo-video?t=31'].sort().join());
await go('#/watch/demo-video');
check('ordinary opening still offers Resume', !!$('#resYes'));
await go('#/watch/demo-video?t=0');
check('explicit zero is kept instead of Resume', !$('#resume') && $('#vid').getAttribute('src').endsWith('#t=0'));
await go('#/watch/demo-video?t=31');
check('explicit nonzero time reaches the media URL', $('#vid').getAttribute('src').endsWith('#t=31'));
const bytes = w.localStorage.getItem('sg.saved');
const realSet = w.Storage.prototype.setItem;
w.Storage.prototype.setItem = function (key, value) { if (key === 'sg.saved') throw Error('quota'); return realSet.call(this, key, value) };
add(45, 'Failed save');
check('write failure stays visible with the editor', $('#momentStatus').textContent.includes('left unchanged') && !!$('#momentName'));
check('failed save keeps original data', w.localStorage.getItem('sg.saved') === bytes);
click('#cancelMoment'); click('[data-moment-remove="m:demo-video:31"]');
check('failed remove retains its row and data', !!$('[data-moment-play="31"]') && w.localStorage.getItem('sg.saved') === bytes);
click('[data-moment-edit="m:demo-video:12"]'); $('#momentName').value = 'Failed rename'; submit();
check('failed rename retains its old name', moments().find(x => x.time === 12).title === 'Tools and parts');
w.Storage.prototype.setItem = realSet; $('#momentName').value = 'Tools checklist'; submit();
check('retry succeeds after storage recovers', !$('#momentName') && moments().find(x => x.time === 12).title === 'Tools checklist');
const hostile = '<img src=x onerror="bad()"> 測試 & café';
add(60, hostile);
check('HTML-like label is literal text', !$('#momentList img') && $('#momentList').textContent.includes(hostile));
click('[data-moment-remove="m:demo-video:60"]');
check('remove preserves the other moments and whole-video Save', moments().length === 3 && w.VideoMoments.readSaved().some(x => x.key === legacy.key));
add(63, '');
check('blank optional name gets a timestamp default', moments().find(x => x.time === 63).title === 'Moment at 1:03');
click('[data-moment-remove="m:demo-video:63"]');
w.VideoMoments.save({ id: 'missing-video', title: 'Another library' }, 8, 'Keep for later');
await go('#/saved');
check('missing video is retained without a broken link', $('.moment-open.unavailable')?.tagName === 'SPAN' && $('.moment-open.unavailable').textContent.includes('Not in this library'));
click('[data-moment-edit="m:missing-video:8"]'); $('#momentName').value = 'Still saved'; submit();
check('missing video can be renamed', moments().find(x => x.videoId === 'missing-video').title === 'Still saved');
click('[data-moment-remove="m:missing-video:8"]');
check('missing video can be removed', moments().length === 3);
await go('#/watch/demo-video?t=999');
check('out-of-range opening is explained', $('#momentStatus').textContent.includes('beyond the end'));
w.VideoMoments.save(video, 999, 'Past the end');
await go('#/watch/demo-video'); click('[data-moment-play="999"]');
check('out-of-range saved row refuses an invalid seek', $('#momentStatus').textContent.includes('beyond the end'));
click('[data-moment-remove="m:demo-video:999"]');
$('#vid')._ready = 0; $('#vid').dispatchEvent(new w.Event('loadedmetadata'));
check('unready media disables saving', $('#saveMoment').disabled);
const saved = JSON.parse(w.localStorage.getItem('sg.saved'));
await open(saved);
check('new page context rehydrates all saved positions', moments().length === 3 && d.querySelectorAll('[data-moment-play]').length === 3);
check('no DOM script errors', faults.length === 0);
check('all application requests stayed inside fixture API', requests.every(x => x.startsWith('/api/')));
dom.window.close();
mkdirSync(new URL('./results/', import.meta.url), { recursive: true });
writeFileSync(new URL('./results/dom-checks.json', import.meta.url), JSON.stringify({ passed: results.length, checks: results, faults, media: 'stubbed', rendering: 'not tested' }, null, 2));
process.stdout.write(JSON.stringify({ passed: results.length }) + '\n');
