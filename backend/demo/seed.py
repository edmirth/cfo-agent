"""Give a demo company a fresh start: empty state, its own description, and
the morning's work already done.

    CFO_DEMO=lindeskar ./.venv/bin/python backend/demo/seed.py

Run before a presentation (demo.sh does it when the state is not from today).
It wipes only state-demo/<company>/, writes the company's company.md, and runs
the morning, the Monday brief and the health check, so every page opens on
finished work instead of a minute's wait in front of an audience. The model
calls are real: the text is written by Arvaka from the demo's books.
"""
import asyncio
import logging
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

log = logging.getLogger("cfo.demo.seed")


def wipe() -> None:
    state = config.STATE.resolve()
    demo_root = (config.ROOT / "state-demo").resolve()
    # The one directory this may delete: a demo company's own.
    if not config.DEMO or state.parent != demo_root:
        raise SystemExit(f"Nekter å slette {state}: ikke en demomappe.")
    if state.exists():
        shutil.rmtree(state)
    state.mkdir(parents=True)


async def run() -> int:
    from demo.companies import SPECS
    spec = SPECS[config.DEMO]
    wipe()
    (config.STATE / "company.md").write_text(spec.company_md, encoding="utf-8")

    import scheduler  # noqa: E402 — after the state folder exists
    failed = []
    for name in ("morning", "weekly_brief", "health_check"):
        log.info("%s: %s …", spec.name, name)
        try:
            result = await scheduler.run(scheduler.job(name), triggered_by="schedule")
            status = (result or {}).get("status")
            if status not in (None, "ok"):
                failed.append(f"{name} ({status})")
        except Exception as e:  # noqa: BLE001 — say which job, keep the rest
            log.exception("%s feilet", name)
            failed.append(f"{name} ({e})")
    if failed:
        print(f"! {spec.name}: {', '.join(failed)}")
        return 1
    # demo.sh starts without seeding again today; a failed seed leaves no stamp.
    (config.STATE / ".seeded").write_text(date.today().isoformat(), encoding="utf-8")
    print(f"✓ {spec.name} er klar")
    return 0


if __name__ == "__main__":
    if not config.DEMO:
        raise SystemExit("Sett CFO_DEMO til et demoselskap, f.eks. CFO_DEMO=lindeskar.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sys.exit(asyncio.run(run()))
