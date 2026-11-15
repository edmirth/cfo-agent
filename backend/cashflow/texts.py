"""Every sentence the forecast says to a person, in Norwegian, in one place.

The calculation modules decide what is true; these say it. Each function
takes the values its sentence quotes and returns the sentence, word for
word as it was written beside the calculation. The briefing for the agent
is narrative.py, which is all text."""
import bankcat

from .common import BANK_UNKNOWN_MAX, DOUBTFUL_DAYS, LATE_DAYS, LATE_SPREAD_WEEKS, MONTH_NAMES, PAY_LAG_DAYS, SLOW_WEEKS, _kr, _term_step


def week_label(start) -> str:
    return (f"Uke {start.isocalendar().week}")


def costs_from_accounts(bank_categories) -> str:
    return ("Driftskostnadene er regnet fra regnskapet, ikke fra banken: "
            + ("for mange utbetalinger i banken har ingen kategori ennå "
               f"({round(bank_categories.get('unknown_share_out', 0) * 100)} %)."
               if bank_categories.get("unknown_share_out", 0) > BANK_UNKNOWN_MAX
               else f"færre enn {bankcat.COST_MIN_MONTHS} hele måneder å lese."))


def fixed_bill(supplier: str) -> str:
    return f"Fast regning fra {supplier}"


def register_against_accounts(invoiced, nxt) -> str:
    return (f"Fakturaene sier {_kr(invoiced)} kr i {nxt['month']} med moms, "
            f"regnskapet {_kr(nxt['regnskapet'])} kr. Prognosen følger "
            f"fakturaene, kunde for kunde. Er forskjellen inntekter som ikke "
            f"faktureres i Tripletex, eller fakturering som har endret seg, "
            f"er det verdt å vite.")


def aside_month_without_invoice() -> str:
    return ("en av de siste månedene uten faktura")


def aside_behind(behind) -> str:
    return (f"{_kr(behind)} kr over {LATE_DAYS} dager på overtid")


def aside_stalled(last_day) -> str:
    return (f"ingen faktura ennå denne måneden, vanligvis den {last_day}.")


def run_label(terms, mo) -> str:
    return (f"Fakturering {MONTH_NAMES[mo - 1]} (ikke sendt), "
            f"{_term_step(terms)} dager")


def other_invoicing_label(terms, mo) -> str:
    return (f"Annen fakturering {MONTH_NAMES[mo - 1]} "
            f"(ikke sendt), {terms} dager")


def rate_said(name, average, seasonal) -> str:
    return (f"{name} er lagt inn med {_kr(average)} kr i måneden"
            f"{' før sesong' if seasonal else ''}.")


def rate_unmeasured(name) -> str:
    return (f"{name} kunne ikke beregnes — det finnes ingen "
            f"avsluttede måneder å regne snittet på, så den er "
            f"satt til 0 i prognosen.")


def bill_label(supplier: str) -> str:
    return f"Regning fra {supplier}"


def wages_withheld(withheld) -> str:
    return (f"Lønn, {round(withheld * 100)} % holdt igjen mot "
            f"feriepengene")


def payroll_vouchers_unread() -> str:
    return ("Lønnsbilagene kunne ikke leses, så lønningsdagen er regnet fra "
            "lønnskontoene i stedet for det tidligere lønningsdager har betalt. "
            "Det kan være for mye, fordi kontoene også har periodisering og "
            "feriepenger i seg.")


def aga_label(month) -> str:
    return (f"Arbeidsgiveravgift på lønn "
            f"{MONTH_NAMES[month.month - 1]}")


def vat_share_unmeasured() -> str:
    return ("Forholdet mellom utgående og inngående merverdiavgift lot seg "
            "ikke måle — konto 2700 er tom eller nettopp gjort opp. Prognosen "
            "legger derfor ut hele den utgående momsen på ny fakturering, uten "
            "fradrag for moms på det dere selv kjøper. Det er for strengt, ikke "
            "for snilt, men det er verdt å vite.")


def invoice_label(customer: str) -> str:
    return f"Faktura til {customer}"


def overdue_label(count: int) -> str:
    return (f"Forfalte fakturaer ({count} stk), "
            f"fordelt over {LATE_SPREAD_WEEKS} uker")


def slow_label(first: int, last: int, count: int) -> str:
    return (f"Fakturaer {LATE_DAYS + 1}–{DOUBTFUL_DAYS} "
            f"dager på overtid ({count} stk), "
            f"fordelt over uke {first}–{last}")


def ar_unmatched_label() -> str:
    return ("Kundefordringer uten kjent faktura, "
            "trolig fra en avkortet fakturaliste")


def ar_residual(gl_ar: float, ar_total: float, residual: float, counted: bool) -> str:
    head = (f"Konto 1500 viser {_kr(gl_ar)} kr i kundefordringer, men de "
            f"åpne fakturaene summerer bare til {_kr(ar_total)} kr. ")
    return (head + (f"Fakturalista er ikke lest helt, så de resterende "
                    f"{_kr(residual)} kr er trolig vanlige fakturaer som ikke "
                    f"ble lest. De ligger bare i den forventede linjen, fordelt "
                    f"over uke {SLOW_WEEKS[0]}–{SLOW_WEEKS[1]}."
                    if counted else
                    f"De resterende {_kr(residual)} kr er ikke regnet med i "
                    f"prognosen før noen har funnet ut hva de består av — "
                    f"gamle fakturaer, posteringer rett på kontoen eller "
                    f"innbetalinger som ikke er koblet til fakturaen."))


def ap_residual_short(gl_ap, ap_total, residual) -> str:
    return (f"Konto 2400 viser {_kr(gl_ap)} kr i leverandørgjeld, men de åpne "
            f"leverandørfakturaene summerer bare til {_kr(ap_total)} kr. De "
            f"resterende {_kr(residual)} kr er lagt inn denne uka, uten "
            f"forfallsdato å feste dem til. Noen bør finne ut hva de består av.")


def bank_gap_unread() -> str:
    return ("Bankavstemmingen i Tripletex kunne ikke leses, så prognosen "
            "starter på den bokførte banksaldoen. Har det kommet inn eller gått "
            "ut penger som ikke er bokført ennå, er startpunktet feil med så "
            "mye — og det er ukjent hvor mye.")


def bank_feed_stale(latest: str) -> str:
    return (f"Bankfeeden i Tripletex har ingenting etter {latest}, "
            f"så startsaldoen er pengene i banken per den dagen. Det som "
            f"har kommet inn eller gått ut siden, er ikke med.")


def bank_gap_approximate() -> str:
    return ("For noen måneder i bankavstemmingen fantes ingen bokført "
            "månedsbevegelse å måle mot, så forskjellen mellom bank og bøker "
            "der er regnet ut fra de umatchede listene alene. De utelater "
            "lønnsposteringer brukeren ikke har innsyn i.")


def ap_unmatched_label() -> str:
    return ("Leverandørgjeld uten kjent faktura")


def ap_residual_over(ap_total, gl_ap) -> str:
    return (f"De åpne leverandørfakturaene summerer til {_kr(ap_total)} kr, "
            f"men konto 2400 viser bare {_kr(gl_ap)} kr i leverandørgjeld. "
            f"Prognosen betaler ut hele {_kr(ap_total)} kr, altså "
            f"{_kr(ap_total - gl_ap)} kr mer enn bøkene sier dere skylder. "
            f"Som regel er det fakturaer som er betalt uten at restbeløpet ble "
            f"nullet i reskontroen. Verdt å rydde i.")


def month_partial(what, when, note) -> str:
    return (f"{what} for {when} ble bare delvis lest "
            f"({note}). Tallene under er ufullstendige.")


def month_cut_off(what: str, when: str, count: int) -> str:
    return (f"Det er minst {count} {what.lower()} i {when}; "
            f"lista kan være avkortet.")


def foreign_currency(name: str | None, currency: str, amount) -> str:
    return (f"{name or 'En faktura'} står i {currency}, "
            f"ikke kroner ({_kr(float(amount))} {currency}). Beløpet "
            f"er lagt inn som om det var kroner, så prognosen er feil "
            f"på denne posten med hele valutakursen.")


def payments_unread() -> str:
    return ("Innbetalingene på konto 1500 kunne ikke leses helt, så "
            "betalingsvanene er ufullstendige; kunder uten nok historikk er "
            f"regnet med {PAY_LAG_DAYS} dager etter forfall.")


def register_unread(what: str) -> str:
    return f"{what} kunne ikke hentes."


def month_unread(what: str, when: str, error) -> str:
    return (f"{what} for {when} kunne ikke hentes ({error}). "
            f"Tallene under er ufullstendige.")


def early_in_year(keep: int, last_year: int, year: int) -> str:
    return (f"Det er for tidlig på året til å regne løpende tall på "
            f"{year} alene, så de siste {keep} månedene av "
            f"{last_year} er tatt med i snittet.")


def last_year_unread(last_year: int, months: int) -> str:
    return (f"Saldobalansen for {last_year} kunne ikke hentes, så de "
            f"løpende tallene hviler på færre enn {months} "
            f"måneder.")


def cost_label_tail(from_bank: bool) -> str:
    """From the bank the committed part is also what comes whatever is sold:
    rent, loans, insurance, pension, fees, the accountant."""
    return ", den faste delen" if from_bank else ", til den faste faktureringen"


def vat_contract_label(month: str) -> str:
    return (f"Merverdiavgift på fast fakturering {month}")


def vat_label(month: str) -> str:
    return (f"Merverdiavgift på fakturering {month}")


def sales_label(month: str, days: str) -> str:
    return (f"Fakturering {month}"
            f"{', ' + days.replace('fakturert ', '') if days else ''}"
            f", betalt")


def wages_label() -> str:
    return "Lønn og skattetrekk"


def aside_far_behind(behind: float) -> str:
    return (f"{_kr(behind)} kr over {LATE_DAYS} dager på overtid, "
            f"mer enn en vanlig måned")


def rate_held_low(months: list[str]) -> str:
    return (f"{', '.join(months)} er holdt utenfor — de ligger langt "
            f"under de andre månedene, og det betyr nesten alltid at bilag "
            f"ikke er bokført, ikke at kostnaden forsvant.")


def rate_held_high(months: list[str]) -> str:
    return (f"{', '.join(months)} er holdt utenfor — de ligger langt "
            f"over de andre månedene. Det er som regel etterslep som ble "
            f"bokført på én gang, eller noe som bare skjedde denne ene "
            f"gangen, men sjekk det før du stoler på snittet.")


def cost_label(month: str, current: bool, days: str, fixed: float, month_vat: float,
               from_bank: bool) -> str:
    """A month's running costs on the weeks: which days, and what is netted."""
    if from_bank:
        return (f"Driftskostnader {month}"
                f"{', resten' if current else ''}"
                f"{', betalt ' + days.replace('fakturert ', '') if days else ''}"
                f", fra banken"
                f"{' utenom kjente regninger' if fixed >= 0.5 else ''}")
    return (f"Driftskostnader {month}"
            f"{', resten' if current else ''}"
            f"{', ' + days if days else ''}"
            f"{' utenom faste regninger' if fixed >= 0.5 else ''}"
            f"{' (inkl. moms)' if month_vat >= 0.5 else ''}")
