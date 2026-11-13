"""The forecast said in words: for the agent, the email and the cards."""
import bankcat
import company
import payment_habits

from .common import DOUBTFUL_DAYS, LATE_DAYS, LEVEL_MONTHS, MONTH_NAMES, PAY_LAG_DAYS, RECURRING_MONTHS, RUN_ACTIVE, RUN_MONTHS, SLOW_WEEKS, _kr


# A Norwegian payroll fact that breaks the twelve-identical-months assumption
# (the other, the feriepenger month, is in payroll.py).
#
# **Half tax in December.** The tax tables take half the usual trekk from the
# December run, so staff take home more. It does not move the company's cash:
# since 2026 the trekk leaves on pay day with the salary, so net plus trekk is
# the same gross in December as in March — the split between the employee and
# Skatteetaten is all that changes, and the other half is never withheld later.
# Modelled as what it is, a declaration rather than a number, because inflating
# December's outflow would be the old pre-2026 regime in disguise.

HALF_TAX_MONTH = 12


def rules(data: dict | None) -> dict:
    """The company's rules, with the floor resolved against this forecast.

    Resolved on every read and never stored in the forecast: the forecast is
    cached for ten minutes, and a floor changed in Selskapet has to count the
    next time anyone looks, not after the cache happens to expire.
    """
    wages = ((data or {}).get("assumptions") or {}).get("monthly_wages")
    return company.rules(wages)


def below_floor(data: dict, floor: float) -> dict | None:
    """The first week the committed line closes under the floor, if any."""
    return next(({"label": w["label"], "start": w["start"],
                  "amount": w["committed_close"]}
                 for w in data.get("weeks") or []
                 if w["committed_close"] < floor), None)


def _opening_note(bank: dict | None) -> str:
    """Where the opening figure comes from, said every time.

    The adjustment is the point of the opening balance being right, and an
    adjustment nobody is told about is a number that disagrees with the books
    for no stated reason. Said with the count and the date, so the owner can
    find the lines in Bankavstemming himself.
    """
    if not bank:
        return ""
    booked = _kr(bank["booked"])
    if bank.get("adjustment") is None:
        return (f"  — det er den **bokførte** saldoen. Bankavstemmingen kunne "
                f"ikke leses, så om banken står høyere eller lavere er ukjent.")
    adj = bank["adjustment"]
    if abs(adj) < 1:
        note = (f"  — banken og bøkene er like, {booked} kr. Ingen banklinjer "
                f"venter på å bli bokført.")
    else:
        latest = f", siste {bank['latest']}" if bank.get("latest") else ""
        note = (f"  — det er **pengene i banken**, ikke den bokførte saldoen på "
                f"{booked} kr. Banken har {bank['lines']} transaksjoner som "
                f"ikke er bokført ennå ({_kr(bank['in'])} kr inn, "
                f"{_kr(-bank['out'])} kr ut{latest})")
        if bank.get("postings"):
            note += (f", og bøkene har {bank['postings']} posteringer på "
                     f"{_kr(bank['postings_sum'])} kr som ikke finnes i banken")
        note += (f". Til sammen står banken {_kr(abs(adj))} kr "
                 f"{'høyere' if adj > 0 else 'lavere'} enn bøkene.")
        if bank.get("settled_ar_count"):
            note += (f" {bank['settled_ar_count']} kundefakturaer på "
                     f"{_kr(bank['settled_ar'])} kr er betalt i banken og er "
                     f"derfor tatt ut av innbetalingene, så de ikke telles to "
                     f"ganger.")
        if bank.get("settled_ap_count"):
            note += (f" {bank['settled_ap_count']} leverandørfakturaer på "
                     f"{_kr(bank['settled_ap'])} kr er betalt og tatt ut av "
                     f"utbetalingene.")
        if bank.get("stale"):
            note += (f" Bankfeeden stopper {bank['latest']}, så dette er "
                     f"saldoen per den dagen, ikke i dag.")
        note += (" Say this when you quote the opening balance: the books will "
                 "show the lower figure until the bookkeeper catches up.")
    if not bank.get("known"):
        note += (" Deler av bankavstemmingen er ukjent — se det som svekker "
                 "prognosen under.")
    return note


def _floor_line(data: dict) -> str:
    """The low point against the company's floor, and whose floor it is.

    The floor is what "tight" means for this company. Measured against our own
    default, the CEO must be told it is ours — otherwise a guess at his
    comfort level reads as his rule, and he never learns he can set it.
    """
    floor = rules(data)["likviditetsgulv_kr"]
    whose = ("satt av selskapet i Selskapet" if not floor["assumed"] else
             f"{company.said(floor)}. Say it is assumed whenever you measure "
             f"against it, and that he can set his own floor under Selskapet")
    hit = below_floor(data, floor["value"])
    where = (f"Den bundne linjen er under gulvet første gang i {hit['label']} "
             f"({hit['start']}), med {_kr(hit['amount'])} kr."
             if hit else "Den bundne linjen holder seg over gulvet alle 13 "
                         "ukene.")
    return (f"- **Gulvet** er **{_kr(floor['value'])} kr** — {whose}. {where} "
            f"Weigh the low point against this floor, not against zero alone: "
            f"under it is tight even while the balance is still positive.\n")


EDGE_WEEKS = 3   # a low point in the last this many weeks gets the line after


def at_edge(data: dict, start: str | None) -> bool:
    """Whether the week starting `start` is one of the last EDGE_WEEKS of the
    window and money comes in after it."""
    weeks = data.get("weeks") or []
    starts = [w["start"] for w in weeks[-EDGE_WEEKS:]]
    return bool(data.get("after")) and start in starts


def after_text(after: dict | None) -> str:
    """One sentence on the money in after week 13, for the page, the email,
    the card and the briefing alike."""
    if not after:
        return ""
    weeks = (f"uke {after['first_week']}" if after["first_week"] == after["last_week"]
             else f"uke {after['first_week']}–{after['last_week']}")
    if round(after["in"]) <= 0:
        return (f"Etter uke 13 kommer {_kr(after['expected_in'])} kr inn i "
                f"{weeks} hvis faktureringen før da går ut som vanlig.")
    text = (f"Etter uke 13 kommer {_kr(after['in'])} kr inn i {weeks} fra "
            f"fakturaer som er sendt eller sendes før da")
    if round(after["expected_in"]) > 0:
        text += (f", {_kr(after['in'] + after['expected_in'])} kr med resten "
                 f"av den vanlige faktureringen")
    return text + "."


def _bank_cost_words(bank: dict) -> str:
    """The running costs from the bank, said as the briefing says them."""
    odd = [m for m in bank["maneder"] if m["unusual"]]
    shares = ", ".join(f"{bankcat.LABELS.get(c, c).lower()} {round(v * 100)} %"
                       for c, v in list(bank["andeler"].items())[:4])
    return (f"driftskostnader {_kr(bank['nivaa_mnd'])} kr i måneden fra banken "
            f"(medianen av {len(bank['maneder'])} hele måneder, med moms; {shares}"
            + (f"; holdt utenfor som uvanlige: "
               + ", ".join(f"{m['month']} ({_kr(m['amount'])} kr)" for m in odd) if odd else "")
            + f"), hvorav {_kr(bank['betalt_denne_maneden'])} kr alt har gått ut denne "
              f"måneden og bare resten lagt inn")


def briefing(data: dict | None) -> str:
    """The forecast block injected into the system prompt."""
    if not data or not data.get("weeks"):
        return ""
    low_c, low_e = data["low_committed"], data["low_expected"]
    a = data["assumptions"]

    out = ["## De neste 13 ukene\n",
           f"Built {data.get('as_of')} from open invoices, the tax calendar and "
           f"this company's own run-rates. No model was involved in the "
           f"arithmetic, but the second line is a forecast and must always be "
           f"presented as one.\n",
           f"- Starter på **{_kr(data['opening'])} kr**",
           _opening_note(data.get("bank")),
           f"- **Bundet linje** — det som allerede er fakturert inn og ut, "
           f"de faste kundene som faktureres hver måned, de faste regningene, "
           f"lønn og skattedatoer: lavest **{_kr(low_c['amount'])} kr** i "
           f"{low_c['label']} ({low_c['start']}).",
           f"- **Forventet linje** — med resten av den vanlige faktureringen og "
           f"driften: lavest "
           f"**{_kr(low_e['amount'])} kr** i {low_e['label']} "
           f"({low_e['start']}).",
           _floor_line(data)]

    # Said per line, never as one verdict. The floor and the forecast go dry
    # in different weeks and for different reasons, and "kontoen går i minus"
    # without saying which line means nothing he can act on.
    neg_e, neg_c = data.get("goes_negative"), data.get("goes_negative_committed")
    if neg_c and neg_e:
        out.append(f"**Kontoen går i minus i begge linjene.** Den bundne i "
                   f"{neg_c['label']} ({neg_c['start']}), den forventede i "
                   f"{neg_e['label']} ({neg_e['start']}). That is the finding. "
                   f"Lead with the bundne week — it is the one that needs no "
                   f"forecast to happen — say what it would take to avoid it, "
                   f"and do not bury either in the table.\n")
    elif neg_c:
        out.append(f"**Den bundne linjen går i minus i {neg_c['label']} "
                   f"({neg_c['start']}).** What is already invoiced in and out, "
                   f"the contract customers' monthly invoicing, wages and the "
                   f"tax dates do not keep the account above zero. The "
                   f"forventede line stays positive, but only if the rest of "
                   f"the invoicing actually goes out and gets paid. That is "
                   f"the finding: lead with the week, name the invoicing the "
                   f"comfort depends on, and never say the account stays "
                   f"positive without that condition attached.\n")
    elif neg_e:
        out.append(f"**Den forventede linjen går i minus i {neg_e['label']} "
                   f"({neg_e['start']}),** selv om den bundne holder seg over "
                   f"null. Ordinary trading is what takes it under — the VAT "
                   f"and the running costs on invoicing not yet sent. Lead "
                   f"with it, and say it is a forecast failing, not a bill "
                   f"already agreed.\n")
    else:
        out.append("Ingen av de to linjene går i minus i perioden. Say that "
                   "plainly when asked; do not manufacture alarm from a low "
                   "point that is still comfortably positive.\n")

    out.append("| Uke | Fra | Inn | Ut | Bundet saldo | Forventet saldo |")
    out.append("|---|---|---:|---:|---:|---:|")
    for w in data["weeks"]:
        out.append(f"| {w['label']} | {w['start']} | {_kr(w['in'] + w['expected_in'])} | "
                   f"{_kr(-(w['out'] + w['expected_out']))} | "
                   f"{_kr(w['committed_close'])} | {_kr(w['expected_close'])} |")
    if data.get("after"):
        out.append("")
        out.append(f"{after_text(data['after'])} Only the money in is counted "
                   f"after the window, not what goes out then, so never add it "
                   f"to a balance. Say it when the last weeks look low: the "
                   f"invoicing that pays for them lands after week 13.")
    out.append("")
    out.append(f"**Forutsetningene** — these are his to change, and saying them "
               f"out loud is what separates a forecast from a guess: fakturering "
               f"{_kr(a['monthly_revenue'])} kr i måneden, lønn "
               f"{_kr(a['monthly_wages'])} kr, "
               + (_bank_cost_words(bank) if (bank := a.get("kostnader_fra_banken")) else
                  f"driftskostnader {_kr(a['monthly_opex'])} kr"
                  + (f" ({_kr(a['monthly_opex_cash'])} kr ut av kontoen med "
                     f"{_kr(a['mva_paa_kostnader'])} kr inngående moms)"
                     if a.get("mva_paa_kostnader") else "")
                  + (f", hvorav {_kr(a['kostnader_bokfort_denne_maneden'])} kr "
                     f"alt er bokført denne måneden og bare resten lagt inn"
                     if a.get("kostnader_bokfort_denne_maneden") else ""))
               + f", kredittid {a['credit_days']} dager "
               f"pluss {a['pay_lag_days']} dagers forsinkelse, forfalte fakturaer "
               f"fordelt over {a['late_spread_weeks']} uker.\n")

    # How far the overdue book is counted on, by age. Said whenever any of it
    # is held back, because the owner will otherwise count it himself.
    ages = a.get("forfalte_grupper") or {}
    if ages.get("31_90") or ages.get("over_90"):
        parts = []
        if ages.get("31_90"):
            parts.append(f"{_kr(ages['31_90'])} kr er {LATE_DAYS + 1}–"
                         f"{DOUBTFUL_DAYS} dager på overtid og ligger bare i den "
                         f"forventede linjen, fordelt over uke {SLOW_WEEKS[0]}–"
                         f"{SLOW_WEEKS[1]}")
        if ages.get("over_90"):
            named = ", ".join(
                f"{i['name']} {_kr(i['amount'])} kr ({i['days_overdue']} dager)"
                for i in (data.get("ar_doubtful") or [])[:5])
            parts.append(f"{_kr(ages['over_90'])} kr er mer enn {DOUBTFUL_DAYS} "
                         f"dager på overtid og er ikke regnet med i noen av "
                         f"linjene: {named}")
        out.append(f"**Forfalte kundefakturaer, etter alder** — det som er "
                   f"inntil {LATE_DAYS} dager på overtid er vanlig forsinkelse "
                   f"og ligger i begge linjene. " + "; ".join(parts) + ". "
                   f"Kommer de gamle pengene inn, er det en gevinst prognosen "
                   f"ikke har lovet. Say this when he asks what is owed to him: "
                   f"the money is still his to chase, it is just not counted "
                   f"on.\n")

    # When the customers' money comes: their own habits, said with the slowest.
    h = data.get("betalingsvaner") or {}
    if h.get("measured"):
        slow = sorted(((n, c["days"]) for n, c in (h.get("customers") or {}).items()
                       if c["days"] > 0), key=lambda x: -x[1])[:3]
        named = (" De tregeste: " + ", ".join(f"{n} {d} dager" for n, d in slow) + "."
                 if slow else "")
        overall = (f"kundene betaler vanligvis {h['company']} dager etter "
                   f"forfall, og " if h.get("company") is not None else "")
        out.append(f"**Når kundene betaler** — målt på et år med innbetalinger: "
                   f"{overall}hver kunde med minst {payment_habits.MIN_CUSTOMER} betalte "
                   f"fakturaer er lagt inn med sin egen vane.{named} Fakturaer "
                   f"som ikke er forfalt, er lagt på forfall pluss kundens vane.\n")
        # Who is always late, against the company's own reminder rule (card 20).
        try:
            late_days = rules(data)["purring_etter_dager"]["value"]
        except Exception:  # noqa: BLE001 — the rest of the briefing still holds
            late_days = None
        habitual = sorted(((n, c["days"]) for n, c in (h.get("customers") or {}).items()
                           if late_days is not None and c["days"] >= late_days),
                          key=lambda x: -x[1])
        if habitual:
            out.append(f"**Faste sene betalere** — vanen deres er forbi purreregelen "
                       f"på {late_days} dager: "
                       + ", ".join(f"{n} ({d} dager)" for n, d in habitual)
                       + ". De får en påminnelse, men det er ikke et nytt "
                       f"problem: prognosen venter pengene deres sent. En kunde "
                       f"som vanligvis betaler i tide og nå er over regelen, er "
                       f"det som bør tas opp; Saker har kortene og dagens "
                       f"innkrevingsliste. Etter to påminnelser uten betaling er "
                       f"neste steg (inkassovarsel, samtale, nedbetaling) eierens "
                       f"eget: foreslå det, men skriv det ikke.\n")
    else:
        out.append(f"**Når kundene betaler** — det er for få innbetalinger å se "
                   f"et mønster i, så alle kunder er lagt inn med "
                   f"{PAY_LAG_DAYS} dager etter forfall.\n")

    # When the sales not yet invoiced come in, and what that rests on.
    sp = a.get("fakturaprofil") or {}
    if sp.get("measured"):
        spread = ", ".join(f"{round(p['share'] * 100)} % fakturert "
                           f"{p['from']}.–{min(p['to'], 31)}. med {p['terms']} "
                           f"dagers frist" for p in sp["periods"])
        out.append(f"**Ny fakturering** — lagt på måneden slik selskapet "
                   f"pleier å fakturere, målt på {sp['bills']} fakturaer: "
                   f"{spread}, betalt {sp['forsinkelse_dager']} dager etter "
                   f"forfall. Det som betales etter de 13 ukene, er ikke med.\n")
    else:
        out.append(f"**Ny fakturering** — for få fakturaer til å se når i "
                   f"måneden selskapet fakturerer, så den er lagt på siste dag "
                   f"i måneden med {a['credit_days']} dagers kredittid og "
                   f"{sp.get('forsinkelse_dager', PAY_LAG_DAYS)} dagers "
                   f"forsinkelse.\n")

    # The months are not alike, and the owner should hear which ones are not.
    seasons = a.get("sesong") or {}
    if seasons.get("revenue"):
        months = [m["month"] for m in a.get("omsetning_per_maned") or []]
        said = ", ".join(
            f"{m} {round((seasons['revenue'][m] - 1) * 100):+d} %" for m in months
            if m in seasons["revenue"])
        sales = ", ".join(f"{m['month']} {_kr(m['amount'])} kr"
                          for m in a.get("omsetning_per_maned") or [])
        out.append(f"**Sesong** — omsetningen følger fjorårets mønster, tatt "
                   f"med halv styrke fordi ett år er et tynt grunnlag: {said} "
                   f"mot en vanlig måned. Nivået er de siste {LEVEL_MONTHS} "
                   f"avsluttede månedene med sesongen trukket ut, så vekst eller "
                   f"nedgang siden i fjor er med. Lagt inn: {sales}. "
                   + ("Driftskostnadene har sitt eget mønster fra fjorårets "
                      "kostnader." if seasons.get("opex") else
                      "Driftskostnadene ligger flatt — fjoråret har ikke tolv "
                      "måneder med kostnader å lese et mønster av.") + "\n")
    else:
        out.append("**Sesong** — fjoråret har ikke tolv måneder med omsetning "
                   "å lese et mønster av, så hver måned er lagt inn likt. Er "
                   "noen måneder normalt stillere, er prognosen for snill i "
                   "dem.\n")

    # The receivables nobody can explain: never in the floor, and only in the
    # forecast when the invoice list is known to be short.
    unknown = a.get("ukjente_fordringer") or {}
    if unknown.get("behandlet") == "ikke_regnet_med":
        out.append(f"**Kundefordringer uten faktura** — konto 1500 har "
                   f"{_kr(unknown['belop'])} kr mer enn de åpne fakturaene. "
                   f"Ingen vet hva det er, så det er ikke regnet med i noen av "
                   f"linjene. Do not promise this money; say the accountant "
                   f"should find out what it is.\n")
    elif unknown.get("behandlet") == "forventet":
        out.append(f"**Kundefordringer uten faktura** — konto 1500 har "
                   f"{_kr(unknown['belop'])} kr mer enn fakturalista som ble "
                   f"lest, og lista er ikke hel. Det er trolig vanlige fakturaer, "
                   f"så det ligger i den forventede linjen, men ikke i den "
                   f"bundne.\n")

    # When the running costs leave, and what that rests on: it moves which week
    # is the tight one, so it is said either way.
    prof = a.get("kostnadsprofil") or {}
    if prof.get("measured"):
        spread = ", ".join(f"{round(p['share'] * 100)} % fakturert "
                           f"{p['from']}.–{min(p['to'], 31)}. og betalt etter "
                           f"{p['terms']} dager" for p in prof["periods"])
        out.append(f"**Når driftskostnadene går ut** — fordelt på måneden etter "
                   f"når selskapets egne leverandørfakturaer pleier å komme og "
                   f"betales, målt på {prof['bills']} fakturaer det siste året: "
                   f"{spread}. Det som betales etter de 13 ukene, er ikke med.\n")
    else:
        out.append("**Når driftskostnadene går ut** — det finnes for få "
                   "leverandørfakturaer til å se et mønster, så de løpende "
                   "kostnadene er lagt på siste dag i hver måned.\n")

    # The floor's newest part, named bill by bill so the owner can check it
    # against what he knows he pays — and what it cannot see, said every time.
    fixed = data.get("fixed_costs") or []
    gap = ("Husleie eller leasing som trekkes direkte fra banken uten "
           "leverandørfaktura, og regninger som kommer én gang i året, er ikke "
           "med — de finnes ikke som gjentatte fakturaer.")
    if fixed:
        named = ", ".join(
            f"{f['name']} {_kr(f['amount'])} kr {f['cadence']}" for f in fixed[:8])
        more = f" og {len(fixed) - 8} til" if len(fixed) > 8 else ""
        out.append(f"**Faste regninger i den bundne linjen** — funnet på at "
                   f"leverandøren fakturerer det samme hver måned eller hvert "
                   f"kvartal, lagt på vanlig forfallsdag: {named}{more}. Til "
                   f"sammen {_kr(a.get('faste_regninger_mnd'))} kr i måneden. "
                   f"De er trukket fra driftskostnadene i den forventede "
                   f"linjen, så de telles ikke to ganger. {gap}\n")
    else:
        out.append(f"**Ingen faste regninger funnet** — ingen leverandør "
                   f"fakturerer det samme beløpet jevnlig, så den bundne linjen "
                   f"har ingen husleie, leasing eller forsikring i seg. {gap} "
                   f"Say so if he asks how safe the bundne line is.\n")

    # The other side of the same floor: the invoicing it now counts on before
    # anything is sent, named customer by customer so he can strike one out.
    everyone = data.get("recurring_sales") or []
    contracts = [f for f in everyone if f.get("committed", True)]
    aside = [f for f in everyone if not f.get("committed", True)]
    if aside:
        out.append("**Faste kunder utenfor den bundne linjen** — "
                   + "; ".join(f"{f['name']}: {f['why']}"
                               + (" (holdt utenfor prognosen)" if f.get("excluded")
                                  else " (vanlig måned i den forventede linjen)")
                               for f in aside[:8])
                   + ". Say so if he asks why a regular customer is not in the "
                     "safe line, and what would put him back.\n")
    if contracts:
        named = ", ".join(f"{f['name']} {_kr(f['amount'])} kr" for f in contracts[:8])
        more = f" og {len(contracts) - 8} til" if len(contracts) > 8 else ""
        out.append(f"**Fast fakturering i den bundne linjen** — kunder som er "
                   f"fakturert i minst {RUN_ACTIVE} av de siste {RUN_MONTHS} "
                   f"månedene og hver av de siste {RECURRING_MONTHS}, lagt inn med "
                   f"den laveste av de tre siste, på kundens egne fakturadager og "
                   f"betalingsfrister og betalt så sent som kunden pleier: "
                   f"{named}{more}. Til sammen "
                   f"{_kr(a.get('fast_fakturering_mnd'))} kr i måneden; en vanlig "
                   f"måned (medianen) er {_kr(a.get('fast_fakturering_vanlig_mnd'))} "
                   f"kr, og forskjellen ligger i den forventede linjen. Momsen "
                   f"og den samme andelen av driftskostnadene ligger i den bundne "
                   f"linjen sammen med dem, og alt er trukket fra den forventede "
                   f"linjen, så ingenting telles to ganger. Say this whenever he "
                   f"asks how safe the bundne line is: it assumes these customers "
                   f"stay, and a contract that ends must come out of it.\n")
    else:
        out.append("**Ingen fast fakturering funnet** — ingen kunde er "
                   f"fakturert hver av de siste {RECURRING_MONTHS} månedene, "
                   "så den bundne linjen har ingen ny "
                   "fakturering i seg. All framtidig fakturering ligger i den "
                   "forventede linjen. Say so when the bundne line goes dry: "
                   "it is what happens if nothing new is invoiced, not a "
                   "prediction that nothing will be.\n")

    other = a.get("annen_fakturering")
    if a.get("fakturering_fra") == "fakturaregisteret" and other:
        odd = other.get("uvanlige") or []
        out.append(
            f"**Annen fakturering, i den forventede linjen** — kunder som ikke "
            f"faktureres hver måned, lagt inn med en vanlig måned (medianen av de "
            f"siste {RUN_MONTHS}): {_kr(other['nivaa_mnd'])} kr. "
            + (("Uvanlige måneder, holdt utenfor som engangstilfeller: "
                + ", ".join(f"{u['month']} ({_kr(u['amount'])} kr)" for u in odd)
                + ". Say so if he asks why a strong month is not in the "
                  "forecast, and ask whether it really was a one-off. ")
               if odd else "")
            + "Pengene som kommer inn er lest fra fakturaene, kunde for kunde, "
              "ikke fra inntektene i regnskapet.\n")

    cats = data.get("bank_categories")
    if cats and cats.get("months"):
        closed = sorted(cats["months"])[:-1] or sorted(cats["months"])
        per: dict = {}
        for month in closed:
            for cat, sides in cats["months"][month].items():
                per[cat] = per.get(cat, 0.0) - sides.get("ut", 0.0)
        out_lines = ", ".join(f"{bankcat.LABELS.get(c, c)} {_kr(v / len(closed))} kr"
                              for c, v in sorted(per.items(), key=lambda kv: -kv[1]) if v >= 1)
        odd = ", ".join(f"{u['name']} ({_kr(-u['amount'])} kr)" for u in cats["unknown"][:5]
                        if u["amount"] < 0)
        out.append(f"**Det som gikk ut av banken, per måned i snitt "
                   f"({len(closed)} hele måneder):** {out_lines}. "
                   f"{round(cats['unknown_share_out'] * 100)} % av utbetalingene har ingen "
                   f"kategori ennå" + (f"; de største: {odd}" if odd else "") + ". "
                   f"This is the bank, not the accounts: use it when he asks what the "
                   f"business really spends, and ask him about the unknown ones.\n")

    # The half of the forecast that is easy to leave out, because it is a bill
    # arriving for money that already came in.
    out.append(
        f"**Ny fakturering tar med seg sin egen regning.** Momsen på det som "
        f"faktureres framover er lagt ut på terminforfallet sitt, ikke på den "
        f"dagen kunden betaler — og de to er sjelden samme uke. Satsen er "
        f"{round(a['mva_sats'] * 100)} %, med "
        + (f"{round(a['mva_fradrag_andel'] * 100)} % fradrag for inngående "
           f"moms, målt på konto 2700 mot 2710."
           if a.get("mva_fradrag_malt") else
           "ingen fradrag for inngående moms, fordi forholdet ikke lot seg "
           "måle — det er for strengt, ikke for snilt.")
        + (f" Av denne månedens moms er {_kr(a['mva_bokfort_denne_maneden'])} "
           f"kr alt bokført og ligger i forpliktelsene, så bare resten er lagt "
           f"inn her — ellers ville den samme kronen gått ut to ganger."
           if a.get("mva_bokfort_denne_maneden") else "")
        + f" Arbeidsgiveravgift på lønn som ennå ikke er kjørt ligger på samme "
          f"måte på sitt eget terminforfall, {_kr(a['monthly_aga'])} kr i "
          f"måneden. Begge deler er anslag som følger av omsetnings- og "
          f"lønnsraten over: endrer han den ene, endrer han disse.\n")

    # The two months that do not behave like the other ten. Only said when one
    # of them is actually inside the window: a note about December in February
    # is noise, and noise is what gets the real notes skimmed past.
    months = set(a.get("lonnskjoringer") or ())
    ferie = a.get("feriepenger_maned", "")
    ferie_month = next((i + 1 for i, n in enumerate(MONTH_NAMES) if n == ferie),
                       None)
    if ferie_month in months and a.get("ferie_lonn_holdt_igjen"):
        held = a["ferie_lonn_holdt_igjen"]
        run = (f"holdt helt tilbake — feriepengene er hele utbetalingen"
               if held >= 1 else
               f"satt ned til {_kr(a['ferie_lonn_utbetalt'])} kr fra "
               f"{_kr(a['monthly_wages_cash'])} kr")
        # Whether this rests on their word or on ours decides how hard he is
        # allowed to lean on it, so it is said either way, not only when weak.
        source = ("Både måneden og de "
                  f"{a['ferie_uker']} ukene ferie står i company.md."
                  if a.get("feriepenger_maned_oppgitt")
                  and a.get("ferie_uker_oppgitt") else
                  f"Måneden er antatt til {ferie} og ferien til "
                  f"{a['ferie_uker']} uker — det står ikke i company.md, og "
                  f"det flytter en hel månedslønn mellom to uker, så det er "
                  f"verdt å få bekreftet.")
        out.append(
            f"**Feriemåneden ligger i perioden.** I {ferie} tar de ansatte ut "
            f"feriepenger i stedet for vanlig lønn, og lønnskjøringen den "
            f"måneden er derfor {run}. Feriepengene selv ligger i den bundne "
            f"linjen, med beløpet fra konto 2940. {source}\n")
    if HALF_TAX_MONTH in months:
        out.append(
            f"**Halv skatt i desember.** De ansatte får mer netto i desember, "
            f"men trekket betales til Skatteetaten samme dag som lønnen, så "
            f"beløpet ut av bedriftens konto er den samme bruttolønnen som i "
            f"en vanlig måned. Si det hvis han venter en tyngre desember av "
            f"den grunn — desember er tung av andre grunner, ikke denne.\n")

    if data.get("warnings"):
        out.append("**Det som svekker prognosen** — say these in the owner's "
                   "words whenever you quote a figure that rests on them:\n")
        out += [f"- {w}" for w in data["warnings"]]
        out.append("")

    out.append("How to use it. The low point and its week are the answer to "
               "\"will I make it\" — give the week by name and date, not a "
               "reassurance. Any question about spending, hiring or buying is "
               "answered against the low point, not against today's balance. "
               "Always say which of the two lines you are quoting.")
    return "\n".join(out)
