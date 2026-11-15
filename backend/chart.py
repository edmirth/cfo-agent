"""Where a company keeps what: its account roles and its tax terms.

The forecast and the commitments both read a company's accounts by role —
receivables, output VAT, employer's contribution — never by number, and both
read the same roles from here, so the two cannot disagree about where the VAT
sits or when it falls due. The default is the standard Norwegian chart (NS
4102) and the ordinary bi-monthly terms; the company's data map overrides a
role where the books confirm it (datamap.py).
"""
from dataclasses import dataclass, field, fields, replace
from typing import Any

Range = tuple[int, int]
Ranges = tuple[Range, ...]
# ((first month, last month), (due month, due day)) for each term of the year.
Terms = tuple[tuple[tuple[int, int], tuple[int, int]], ...]


@dataclass(frozen=True)
class Chart:
    """A company's accounts by role, as ranges of account numbers."""
    bank: Ranges = ((1900, 1949),)
    restricted: Ranges = ((1950, 1959),)          # bundet skattetrekkskonto
    receivables: Ranges = ((1500, 1509),)
    payables: Ranges = ((2400, 2409),)
    loans: Ranges = ((2200, 2249),)
    owners_staff: Ranges = ((2250, 2259), (2910, 2919))
    corporate_tax: Ranges = ((2500, 2540),)
    withholding: Ranges = ((2600, 2619),)
    withholding_paid: Ranges = ((2600, 2609),)    # trekk a pay run leaves owing
    output_vat: Ranges = ((2700, 2709),)
    input_vat: Ranges = ((2710, 2719),)
    vat_running: Ranges = ((2700, 2739),)         # the running term, accrued
    vat_settlement: Ranges = ((2740, 2749),)      # a closed term, owed
    aga: Ranges = ((2770, 2779),)
    aga_holiday: Ranges = ((2780, 2789),)
    net_pay: Ranges = ((2910, 2939),)             # net pay a pay run leaves owing
    holiday_pay: Ranges = ((2940, 2944),)
    accrued_wages: Ranges = ((2945, 2949),)
    other_debt: Ranges = ((2990, 2999),)
    revenue: Ranges = ((3000, 3999),)
    wages: Ranges = ((5000, 5099),)
    # What leaves on pay day: feriepenger (5020) accrues monthly but is paid
    # next summer, and commitments dates it there.
    wages_cash: Ranges = ((5000, 5019), (5030, 5099))
    # 5401 stays out, being the feriepenger's own.
    aga_cost: Ranges = ((5400, 5400),)
    # Every krone that leaves the account in exactly one range, and none that
    # never leaves it. The gaps on purpose: 5200-5299 fordel i
    # arbeidsforhold (no money moves); 5400/5401 arbeidsgiveravgift (dated by
    # commitments); 6000-6099 avskrivning (an asset already paid for);
    # 7800-7899 tap på fordringer (money that did not come in).
    opex: Ranges = ((4000, 4999),     # varekjøp og underentreprise
                    (5100, 5199),
                    (5300, 5399),     # annen opplysningspliktig godtgjørelse
                    (5402, 5999),     # pensjon, yrkesskade, personalkostnad
                    (6100, 7799),     # ordinære driftskostnader
                    (7900, 7999))

    vat_terms: Terms = (((1, 2), (4, 10)), ((3, 4), (6, 10)), ((5, 6), (8, 31)),
                        ((7, 8), (10, 10)), ((9, 10), (12, 10)), ((11, 12), (2, 10)))
    aga_terms: Terms = (((1, 2), (3, 15)), ((3, 4), (5, 15)), ((5, 6), (7, 15)),
                        ((7, 8), (9, 15)), ((9, 10), (11, 15)), ((11, 12), (1, 15)))

    # Where each role came from: "default", or the data map's "verified".
    sources: dict[str, str] = field(default_factory=dict, compare=False)

    def source(self, role: str) -> str:
        return self.sources.get(role, "default")


DEFAULT = Chart()
ROLES = tuple(f.name for f in fields(Chart) if f.name not in ("sources",))
ACCOUNT_ROLES = tuple(r for r in ROLES if not r.endswith("_terms"))

# Roles a data map may not move yet, because something still reads the
# default: the bank range is bankgap's and bankcat's too, and they do not
# take the company's chart. Moving it here alone would have the opening
# balance and the forecast on different accounts.
NOT_PER_COMPANY_YET = frozenset({"bank"})


def within(account: int | None, ranges: Ranges) -> bool:
    return account is not None and any(lo <= account <= hi for lo, hi in ranges)


def for_company(company_id: Any = None) -> Chart:
    """The company's chart: the defaults, with every role its data map gives
    and the books confirmed. No map, or nothing confirmed, is the default."""
    import datamap
    m = datamap.load(company_id)
    if m is None:
        return DEFAULT
    roles = {role: entry.value for role, entry in m.accounts.items()
             if entry.check == "verified" and role not in NOT_PER_COMPANY_YET}
    if not roles:
        return DEFAULT
    sources = {role: "verified" for role in roles}
    return replace(DEFAULT, **roles, sources=sources)
