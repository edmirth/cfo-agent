import asyncio

import industry


def test_a_refresh_shows_the_new_classification_at_once():
    """The refresh paid for a new industry, then served tiles cached for up
    to ten minutes on the old one — and gathered the evidence twice."""
    kpi = next(iter(industry.BY_ID))
    saved = {"bransje": "Renhold", "nokkeltall": [{"id": kpi}]}
    calls = {"gather": 0, "classify": 0}

    async def gather(today):
        calls["gather"] += 1
        return {}, {}

    async def classify(ctx, evidence):
        calls["classify"] += 1
        return {"bransje": "Eiendomsdrift", "nokkeltall": [{"id": kpi}]}

    originals = (industry._gather, industry.classify, industry._load_profile,
                 industry._save_profile, dict(industry._values_cache))
    industry._gather, industry.classify = gather, classify
    industry._load_profile = lambda: saved
    industry._save_profile = lambda data: saved.update(data)
    industry._values_cache.clear()
    try:
        assert asyncio.run(industry.dashboard())["industry"] == "Renhold"
        assert calls == {"gather": 1, "classify": 0}

        fresh = asyncio.run(industry.dashboard(refresh=True))
        assert fresh["industry"] == "Eiendomsdrift"         # not the cached tiles
        assert calls == {"gather": 2, "classify": 1}        # one gather, not two

        # And the next ordinary load reads the new tiles from cache.
        assert asyncio.run(industry.dashboard())["industry"] == "Eiendomsdrift"
        assert calls["gather"] == 2
    finally:
        (industry._gather, industry.classify, industry._load_profile,
         industry._save_profile, cache) = originals
        industry._values_cache.clear()
        industry._values_cache.update(cache)
