# Saved video moments: Lastbook 1.1.14 integration

These screenshots and check results use a synthetic local library and a 90-second test video. They contain no personal library data.

- Feature PR: https://github.com/Immortal-Protocols/lastbook/pull/310
- Tested feature revision: `1927770107c057b97867523a002a5a296cca552a`
- Feature tree: `39195c91c3f3b57d22987299ce30f1de16c9a055`
- Upstream main: `dd9bff82a7defbe88c0005a723c47294a21673ff`
- Verification revision: `5eb2eee32a9437d8decd9116b88236c3ba995472`
- Successful workflow: https://github.com/TheTradoor/lastbook/actions/runs/44877614272
- Workflow artifact: `saved-video-moments-browser-evidence`
- Artifact ZIP SHA-256: `d1dc8260fcc8466329aff0d039f537d89a12c497c89cfef9be07635d34a22f10`

## Results

All 52 real Chromium checks in `checks.json` passed against the actual Lastbook HTTP server. No JavaScript page errors or external application requests were recorded.

The run also passes 13 focused Python feature/package tests, including 21 storage scenarios and 12 Saved-page regression scenarios executed through Node. These counts describe different levels of checks and should not be added together.

The full contributor suite was run locally with Python 3.12 and Node 24 in the same environment for this revision and clean upstream main. It ran 503 tests for this feature and 501 on main. Both report 4 skips, 13 expected failures, and the same 2 failures plus 2 errors:

- `Downloads.test_roots_only`: CA certificate count.
- `Jobs.test_first_run_end_to_end`: recommended pack.
- `AddressIndexes.test_space_counts_the_map`: missing `map_need_bytes`.
- `Maps.test_space_counts_the_map`: missing `map_need_bytes`.

No new failing test identity was introduced. The full suite is not green.

## Screenshots

The player screenshots cover light and dark themes with Mac and Windows CSS variants. Narrow screenshots use widths of 320, 375, and 640 pixels with long moment labels. Saved-page screenshots show ordinary moments and deliberately inaccessible Saved storage while Continue watching and Recently opened remain available.

These checks ran in Linux Chromium. Native macOS and Windows WebViews have not been tested.

The verification workflow and this evidence are kept on separate fork branches; they are not part of the feature PR.
