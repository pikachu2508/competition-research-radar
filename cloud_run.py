from __future__ import annotations

import os
from radar import run
from daily_digest import main as send_digest


mode = os.environ.get("RADAR_MODE", "daily")
code = run(False, False)
if code:
    raise SystemExit(code)
raise SystemExit(send_digest(force_test=(mode == "test")))
