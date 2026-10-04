import re

import config
import industry


def _frontend_statuses() -> set[str]:
    api = (config.ROOT / "frontend-react" / "src" / "lib" / "api.ts").read_text()
    kpi = api[api.index("export type Kpi"):]
    union = re.search(r"status:\s*([^\n]+)", kpi).group(1)
    return set(re.findall(r'"(\w+)"', union))


def test_between_target_and_alarm_is_watch():
    # Wage ratio, lower is better: target 45 %, alarm 55 %.
    assert industry._status(40, 45, 55, "low") == "good"
    assert industry._status(50, 45, 55, "low") == "watch"
    assert industry._status(60, 45, 55, "low") == "bad"


def test_every_status_the_backend_sends_is_one_the_frontend_knows():
    # The backend said "watch" and the frontend listened for "warn", so an
    # off-target KPI fell through to green and never became a signal.
    sent = {industry._status(*args) for args in (
        (40, 45, 55, "low"), (50, 45, 55, "low"), (60, 45, 55, "low"),
        (None, 45, 55, "low"), (50, None, 55, "low"), (50, 45, None, "high"))}
    assert sent <= _frontend_statuses(), sent - _frontend_statuses()
