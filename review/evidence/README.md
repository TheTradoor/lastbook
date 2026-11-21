# Saved video moments: browser evidence

Feature commit: 89fb793a23458cdb77b4713ba688d70fae2310a6

Feature tree: d9cec7846861564548fa30d29e01db4850aa8eab

Successful browser verification: https://github.com/TheTradoor/lastbook/actions/runs/44856502786

Verification commit: 860ce5db3de4d7e8a0d4808da9d0587b437200b2

All 52 checks in checks.json passed. The run used Linux Chromium, the real Lastbook HTTP server and a synthetic 90-second video. It recorded no JavaScript page errors or external application requests during the test.

The Saved read-error screenshots show the compatibility fix requested in https://github.com/Immortal-Protocols/lastbook/pull/310#issuecomment-7053732426. Malformed or inaccessible Saved data leaves Continue watching and Recently opened available. The checks exercise clearing recent history, actually resuming video, keeping the original Saved bytes, and reopening Saved after reads recover.

The mac and win filenames refer to Lastbook's CSS variants, not native macOS or Windows execution. Native WebViews have not been tested. Narrow screenshots exercise a 120-character unbroken label; full-page screenshots retain the fixed navigation at its viewport position.

The feature and package checks pass (13 Python tests, including 21 storage scenarios and 12 Saved-page regression scenarios). The full contributor suite reports 454 tests on this feature and 452 on the unchanged upstream base 26ea623ec7eed6ed8d0592e5bd4c7cfe7ebad2f6 in the same local environment. Both have the same 2 failures, 2 errors, 4 skips and 13 expected failures. The existing outcomes are Downloads.test_roots_only, Jobs.test_first_run_end_to_end, AddressIndexes.test_space_counts_the_map and Maps.test_space_counts_the_map.

These screenshots and results are review evidence only. They are not included in the application feature diff.
