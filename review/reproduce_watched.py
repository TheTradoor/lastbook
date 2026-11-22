"""Require the focused regressions to fail on the integration before the fix."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = 'f734093f54be5af8c9bd2888c668571f65fc8c3f'
OUT = ROOT / 'review' / 'results' / 'before-fix'
OUT.mkdir(parents=True, exist_ok=True)
app = ROOT / 'web' / 'app.js'
original = app.read_bytes()
try:
    app.write_bytes(subprocess.check_output(['git','show',BASE+':web/app.js'],cwd=ROOT))
    node = subprocess.run(['node','app/tests/video_watched_test.mjs'],cwd=ROOT,capture_output=True,text=True)
    print(node.stdout,node.stderr,flush=True)
    (OUT/'node.log').write_text(node.stdout+node.stderr)
    assert node.returncode==1
    assert json.loads(node.stdout.splitlines()[-1])=={'checks':4,'failures':5}
    browser=subprocess.run([sys.executable,'review/watched_moments_browser.py'],cwd=ROOT,
                           env={**os.environ,'LASTBOOK_WATCHED_RESULTS':str(OUT)})
    report=json.loads((OUT/'watched-checks.json').read_text())
    expected={'fresh_saved_jump','fresh_player_jump','fresh_paused_scrub','legacy_completed_progress'}
    observed={r['scenario'] for r in report['results'] if not r['passed']}
    assert browser.returncode==1
    assert len(report['results'])==13 and observed==expected,(observed,report)
    assert not report['errors'] and not report['external_requests'],report
    assert all('Timeout' not in r.get('error','') for r in report['results']),report
    print('PASS: five storage regressions and four browser scenarios reproduce before the fix',flush=True)
finally:
    app.write_bytes(original)
