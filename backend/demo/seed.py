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
from datetime import date, timedelta
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


def _describe(spec, only_missing: bool = False) -> list[str]:
    """Write the company's own company.md and industry profile. Returns what it wrote."""
    wrote = []
    config.STATE.mkdir(parents=True, exist_ok=True)
    rulebook = config.STATE / "company.md"
    if not (only_missing and rulebook.exists()):
        rulebook.write_text(spec.company_md, encoding="utf-8")
        wrote.append("company.md")
    store = config.STATE / "profile.json"
    if spec.profile and not (only_missing and store.exists()):
        import json
        import industry
        profile = {**spec.profile, "bestemt": date.today().isoformat(),
                   "vurderte": [k.id for k in industry.CATALOGUE], "bevis": {}}
        store.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
        wrote.append("profile.json")
    return wrote


def prepare() -> list[str]:
    """At a demo server's start: the company's description, if its folder lacks it.

    A hosted demo (render.yaml) starts on an empty disk and is never seeded,
    because seeding wipes the folder under the running server. Without this it
    would open on no rulebook at all, with the wrong floor and an industry
    guessed by the model. Nothing is wiped and no job is run; the front page's
    «Kjør nå» writes the brief.
    """
    from demo.companies import SPECS
    wrote = _describe(SPECS[config.DEMO], only_missing=True)
    if wrote:
        log.info("Demoselskapet fikk sin egen beskrivelse: %s", ", ".join(wrote))
    return wrote


async def run() -> int:
    from demo.companies import SPECS
    spec = SPECS[config.DEMO]
    wipe()
    _describe(spec)

    import scheduler  # noqa: E402 — after the state folder exists
    failed = []
    # A week of history: the figures as they stood seven days ago, from the
    # same books. Without it a fresh demo has nothing to compare against, and
    # the brief's «Hva endret seg» stays empty.
    try:
        import memory
        import overview
        week_ago = date.today() - timedelta(days=7)
        then = await overview.build(week_ago)
        memory.snapshot(then["kpis"], on=week_ago.isoformat())
    except Exception as e:  # noqa: BLE001 — the brief still works without it
        log.exception("Fikk ikke lagret forrige ukes tall")
        failed.append(f"forrige uke ({e})")
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
