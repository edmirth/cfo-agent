"""The three demo companies, and the one story each of them tells.

All names are invented and were checked against Enhetsregisteret: no company,
customer or supplier here is a real one. Organisation numbers start with 9 and
fail the MOD11 check, so they cannot be mistaken for real ones either.

- Lindeskar Renhold AS, cleaning (yellow): cash dips under the floor in a few
  weeks, one customer is 45 days late with the reminder ready, and payroll
  runs above target on overtime.
- Kvarnheim Bygg AS, construction (red): the developer is a month late on an
  on-account invoice while the subcontractors' bills fall due, and the
  account runs dry unless that money comes in.
- Aslefjord Byggvare AS, building-materials wholesale (green): a quiet week.
  Nothing needs the CEO, and the figures that matter are a trader's.
"""
from datetime import timedelta

from demo.books import Customer, Spec, Supplier

# ---------------------------------------------------------------- cleaning
LINDESKAR_LATE = "Sjøgløtt Eiendom AS"


def _lindeskar_late_customer(b, rng):
    """Sjøgløtt's invoice from two and a half months ago is still open: 45
    days past due, the reminder ready. Their later invoices are open too."""
    for inv in b.invoices:
        if inv.customer == LINDESKAR_LATE and inv.due >= b.today - timedelta(days=52):
            inv.paid = None


def _lindeskar_machines(b, rng):
    """New scrubber-dryers are delivered and the bill is in: due early in
    December, the week the VAT term is paid too."""
    from demo.books import Bill
    on = b.today - timedelta(days=6)
    b.bills.append(Bill(len(b.bills) + 1, 0, f"{rng.randint(100000, 999999)}", on,
                        b.today + timedelta(days=65), "Renfix Engros AS",
                        b.suppliers["Renfix Engros AS"]["id"], 1250, 1_250_000.0, True, None))


LINDESKAR = Spec(
    slug="lindeskar", name="Lindeskar Renhold AS", orgnr="912345670", seed=4101,
    revenue=1_520_000,
    season=(1.0, 1.02, 1.04, 1.0, 1.03, 0.98, 0.74, 0.96, 1.06, 1.05, 1.04, 0.92),
    growth=1.07,
    customers=(
        Customer(LINDESKAR_LATE, 0.15, terms=30, late=3, org="923456781"),
        Customer("Bråtevik kommune, eiendom", 0.18, terms=30, late=1, org="934567892"),
        Customer("Kvernhusbakken Borettslag", 0.08, terms=14, late=4, org="945678903"),
        Customer("Fjellvang Skole", 0.07, terms=30, late=0, org="956789014"),
        Customer("Tunlia Næringspark AS", 0.11, terms=30, late=6, org="967890125"),
        Customer("Holmsrud Kontorfellesskap", 0.06, terms=14, late=2, org="978901236"),
        Customer("Vikertoppen Sameie", 0.05, terms=14, late=3, org="989012348"),
        Customer("Strandmyra Helsehus AS", 0.09, terms=30, late=1, org="990123458"),
        Customer("Lerkevoll Barnehage AS", 0.04, terms=14, late=0, org="901234569"),
        Customer("Grindhaug Eiendomsdrift AS", 0.10, terms=30, late=8, org="912345680"),
        Customer("Moen & Tveit Advokatfirma", 0.03, terms=14, late=1, org="923456792"),
        Customer("Sagbakken Treningssenter", 0.04, terms=14, late=5, org="934567804"),
    ),
    suppliers=(
        Supplier("Renfix Engros AS", 6550, ratio=0.035, terms=30, day=8),
        Supplier("Arbeidsklær Nord AS", 6570, monthly=9_000, terms=30, day=12),
        Supplier("Lindeskar Gårdeiendom AS", 6300, monthly=48_000, terms=14, day=1),
        Supplier("Bilpartner Leasing AS", 6400, monthly=36_000, terms=14, day=3),
        Supplier("Brennli Drivstoff AS", 7000, ratio=0.012, terms=14, day=25),
        Supplier("Trygg Forsikring Vest AS", 7500, monthly=14_000, terms=30, day=2, vat=False),
        Supplier("Tallmester Regnskap AS", 6705, monthly=16_500, terms=14, day=10),
        Supplier("Skyline Systemer AS", 6420, monthly=7_200, terms=14, day=1),
        Supplier("Fjordnett Mobil AS", 6900, monthly=6_400, terms=14, day=15),
    ),
    payroll=0.79, headcount=24, fte=21.6, payday=20, invoice_day=0,
    opening_bank=2_350_000, opening_assets=900_000,
    inbox=3, budget_revenue=1.03, budget_payroll=0.75, dividend=300_000,
    events=(_lindeskar_late_customer, _lindeskar_machines),
    profile={
        "bransje": "Renhold (bygg- og eiendomsrenhold)",
        "beskrivelse": "Renhold av kontorbygg, skoler, sameier og helsehus med egne ansatte, fakturert etterskuddsvis hver måned.",
        "begrunnelse": "Fakturaene gjelder løpende renhold, kundene er eiendomsselskaper, kommunen og sameier, og nesten alle kostnadene er lønn (rundt 79 %) med lite varer. Det er en ren tjenesteleverandør med mange ansatte.",
        "sikkerhet": "høy",
        "hovedtall": "lonnsandel",
        "nokkeltall": [
            {"id": "lonnsandel", "hvorfor": "Dere selger arbeidstimer, så andelen av fakturaen som går til lønn avgjør nesten alene om dere tjener penger.", "mal": 75, "varsel": 80},
            {"id": "driftsmargin", "hvorfor": "I renhold er marginen tynn, så det som blir igjen etter alle kostnader må følges måned for måned.", "mal": 6, "varsel": 3},
            {"id": "omsetning_per_ansatt", "hvorfor": "Viser om hver renholder har nok oppdrag og riktig timepris.", "mal": 750000, "varsel": 600000},
            {"id": "topp_tre", "hvorfor": "Mister dere én av de største kundene, forsvinner en stor del av inntekten over natta.", "mal": 40, "varsel": 55},
            {"id": "betalingstid", "hvorfor": "Lønnen går ut hver måned uansett, så sene kunder blir fort trangt.", "mal": 30, "varsel": 45},
            {"id": "vekst", "hvorfor": "Om dere vinner flere kontrakter enn dere mister.", "mal": 5, "varsel": 0},
            {"id": "likviditetsgrad", "hvorfor": "Om dere har nok omløpsmidler til å dekke det som forfaller.", "mal": 1.5, "varsel": 1.0}
        ]
    },
    company_md="""---
lonn_utbetalingsdag: 20
ferie_utbetalingsmnd: 6
likviditetsgulv_kr: 2 000 000
purring_etter_dager: 14
lonnsandel_mal_pct: 75
---

# Slik fungerer Lindeskar Renhold

Vi gjør renhold for kontorbygg, skoler, sameier og helsehus på Vestlandet.
Kundene faktureres etterskuddsvis den siste virkedagen i måneden, med 14 eller
30 dagers betalingsfrist.

## Lønn

Lønnen kjøres den 20. Om lag 24 ansatte, de fleste i deltidsstillinger. Overtid
på kveldsrenhold for Sjøgløtt-byggene har drevet lønnsandelen opp i høst.

## Kundene

Bråtevik kommune og Sjøgløtt Eiendom er de to største. Kommunen betaler alltid
på dagen. Sjøgløtt har betalt greit før, men er nå på etterskudd.

## Sesong

Juli er alltid svak: skolene og flere kontorbygg står tomme i fellesferien.

## Investeringer

Ny maskinpark (fire skurevaskemaskiner) er levert i oktober og betales i
desember.
""",
)

# ------------------------------------------------------------ construction
KVARNHEIM_DEVELOPER = "Ospelia Utvikling AS"


def _kvarnheim_developer_late(b, rng):
    """The developer's last on-account invoice is a month past due, and the
    one before it was paid late. The work goes on, so the next one is out."""
    devs = sorted((i for i in b.invoices if i.customer == KVARNHEIM_DEVELOPER),
                  key=lambda i: i.date)
    for inv in devs:
        days_late = (b.today - inv.due).days
        if 20 <= days_late <= 40:
            inv.paid = None
            inv.comment = "A-konto 7, Ospelia trinn 2"
        elif days_late < 20:
            inv.paid = None


def _kvarnheim_subcontractors(b, rng):
    """Two large subcontractor bills land now and fall due within three weeks."""
    from demo.books import Bill
    for name, account, net, days in (("Strømvik Elektro AS", 4500, 880_000, 12),
                                     ("Rørtek Vest AS", 4500, 690_000, 19),
                                     ("Nordvik Byggevare AS", 4000, 520_000, 9)):
        on = b.today - timedelta(days=30 - days)
        b.bills.append(Bill(len(b.bills) + 1, 0, f"{rng.randint(100000, 999999)}", on,
                            on + timedelta(days=30), name, b.suppliers[name]["id"],
                            account, float(net), True, None))


KVARNHEIM = Spec(
    slug="kvarnheim", name="Kvarnheim Bygg AS", orgnr="945612378", seed=4202,
    revenue=2_950_000,
    season=(0.78, 0.84, 0.98, 1.08, 1.12, 1.1, 0.7, 1.08, 1.14, 1.12, 1.04, 0.82),
    growth=1.11,
    customers=(
        Customer(KVARNHEIM_DEVELOPER, 0.42, terms=30, late=9, org="956123489"),
        Customer("Bergtun Boligbyggelag", 0.17, terms=30, late=2, org="967234590"),
        Customer("Kvitveis Sameie", 0.08, terms=30, late=4, org="978345601"),
        Customer("Ravnefjell Eiendom AS", 0.12, terms=30, late=3, org="989456712"),
        Customer("Lykkjebakken Næringsbygg AS", 0.09, terms=30, late=5, org="990567823"),
        Customer("Hustad Barnehager AS", 0.05, terms=30, late=1, org="901678934"),
        Customer("Privatkunder, diverse", 0.07, terms=14, late=6, org=""),
    ),
    suppliers=(
        Supplier("Nordvik Byggevare AS", 4000, ratio=0.37, terms=30, day=6),
        Supplier("Strømvik Elektro AS", 4500, ratio=0.07, terms=30, day=14),
        Supplier("Rørtek Vest AS", 4500, ratio=0.06, terms=30, day=18),
        Supplier("Maskinutleie Fjord AS", 6400, monthly=88_000, terms=14, day=4),
        Supplier("Kvarnheim Eiendom AS", 6300, monthly=62_000, terms=14, day=1),
        Supplier("Brennli Drivstoff AS", 7000, ratio=0.008, terms=14, day=24),
        Supplier("Trygg Forsikring Vest AS", 7500, monthly=31_000, terms=30, day=2, vat=False),
        Supplier("Tallmester Regnskap AS", 6705, monthly=24_000, terms=14, day=10),
        Supplier("Arbeidsklær Nord AS", 6570, monthly=11_000, terms=30, day=12),
    ),
    payroll=0.31, headcount=18, fte=17.4, payday=10, invoice_day=10,
    opening_bank=2_600_000, opening_assets=3_200_000,
    loan=2_400_000, loan_monthly=40_000,
    inbox=5, budget_revenue=1.0, budget_payroll=0.33, dividend=1_450_000,
    events=(_kvarnheim_developer_late, _kvarnheim_subcontractors),
    profile={
        "bransje": "Bygg og anlegg (totalentreprise bolig og næring)",
        "beskrivelse": "Totalentreprenør med egne fagarbeidere og underentreprenører på elektro og rør, fakturert a-konto etter fremdrift.",
        "begrunnelse": "Store a-kontofakturaer til utbyggere og borettslag, tunge innkjøp av byggevarer og underentreprise, og én utbygger som står for rundt 40 % av omsetningen. Pengene bindes i prosjektene mellom innkjøp og betaling.",
        "sikkerhet": "høy",
        "hovedtall": "driftsmargin",
        "nokkeltall": [
            {"id": "driftsmargin", "hvorfor": "I bygg er marginen liten og risikoen stor; ett prosjekt som sprekker, spiser årets overskudd.", "mal": 6, "varsel": 3},
            {"id": "storste_kunde", "hvorfor": "Når én utbygger er nesten halve omsetningen, er det dens betaling hele kontantstrømmen venter på.", "mal": 30, "varsel": 45},
            {"id": "kontantdager", "hvorfor": "Underentreprenører og lønn må betales før utbyggeren betaler, så buffer i dager er det som avgjør.", "mal": 30, "varsel": 15},
            {"id": "betalingstid", "hvorfor": "A-konto skal inn på 30 dager; drar det ut, finansierer dere prosjektet selv.", "mal": 30, "varsel": 45},
            {"id": "lonnsandel", "hvorfor": "Egne fagarbeidere er en fast kostnad, også i måneder med lite fakturering.", "mal": 33, "varsel": 40},
            {"id": "vekst", "hvorfor": "Om ordrebøkene vokser.", "mal": 5, "varsel": 0},
            {"id": "likviditetsgrad", "hvorfor": "Om omløpsmidlene dekker det som forfaller.", "mal": 1.5, "varsel": 1.0}
        ]
    },
    company_md="""---
lonn_utbetalingsdag: 10
lonn_etterskuddsvis_mnd: 1
ferie_utbetalingsmnd: 6
likviditetsgulv_kr: 1 500 000
purring_etter_dager: 10
lonnsandel_mal_pct: 35
---

# Slik fungerer Kvarnheim Bygg

Totalentreprenør på bolig og mindre næringsbygg. 18 egne fagarbeidere; elektro
og rør settes ut til underentreprenører.

## Fakturering

Store prosjekter faktureres a-konto den 10. hver måned etter fremdrift, med 30
dagers frist. Ospelia trinn 2 for Ospelia Utvikling er det klart største
prosjektet i år, rundt 40 % av omsetningen.

## Leverandører

Underentreprenørene fakturerer midt i måneden med 30 dager. Byggevarer kjøpes
på konto hos Nordvik Byggevare.

## Sesong

Januar, februar og juli er svake. Fellesferien stopper byggeplassene.
""",
)

# ------------------------------------------------------------------ wholesale
ASLEFJORD = Spec(
    slug="aslefjord", name="Aslefjord Byggvare AS", orgnr="978901245", seed=4303,
    revenue=2_180_000,
    season=(0.82, 0.86, 1.0, 1.1, 1.14, 1.08, 0.78, 1.02, 1.08, 1.06, 0.98, 0.84),
    growth=1.05,
    customers=(
        Customer("Hageli Tømrer AS", 0.13, terms=30, late=0, org="989012356"),
        Customer("Brennvik Bygg & Tak AS", 0.11, terms=30, late=1, org="990123467"),
        Customer("Sørlund Snekkeri AS", 0.09, terms=30, late=0, org="901234578"),
        Customer("Vardehaug Entreprenør AS", 0.12, terms=30, late=2, org="912345689"),
        Customer("Lomsdal Maler & Bygg", 0.06, terms=14, late=1, org="923456790"),
        Customer("Kroktjern Hytteservice AS", 0.07, terms=14, late=0, org="934567801"),
        Customer("Bøen Rørlegger AS", 0.05, terms=30, late=1, org="945678912"),
        Customer("Grytdal Anlegg AS", 0.10, terms=30, late=2, org="956789023"),
        Customer("Kontantsalg butikk", 0.21, terms=0, late=0, org=""),
        Customer("Tjernhaug Hytteeiendom AS", 0.06, terms=30, late=1, org="967890134"),
    ),
    suppliers=(
        Supplier("Skogheim Trelast AS", 4300, ratio=0.33, terms=45, day=7),
        Supplier("Nordisk Isolasjon AS", 4300, ratio=0.14, terms=30, day=11),
        Supplier("Festeteknikk Norge AS", 4300, ratio=0.12, terms=30, day=16),
        Supplier("Vestlandsplater AS", 4300, ratio=0.10, terms=30, day=21),
        Supplier("Aslefjord Næringseiendom AS", 6300, monthly=95_000, terms=14, day=1),
        Supplier("Truckservice Midt AS", 6400, monthly=22_000, terms=14, day=4),
        Supplier("Trygg Forsikring Vest AS", 7500, monthly=9_500, terms=30, day=2, vat=False),
        Supplier("Tallmester Regnskap AS", 6705, monthly=14_000, terms=14, day=10),
        Supplier("Skyline Systemer AS", 6420, monthly=11_800, terms=14, day=1),
        Supplier("Skiltlaget Tverrdal AS", 7320, monthly=18_000, terms=30, day=20),
    ),
    # Invoiced on the 20th, before payday: from the 25th on, a month-end
    # invoicer's open month reads as payroll in and sales missing, and
    # the quiet week's books are called provisional for a week a month.
    payroll=0.115, headcount=9, fte=8.6, payday=25, invoice_day=20,
    opening_bank=4_200_000, opening_assets=1_400_000, opening_stock=3_900_000,
    inbox=0, budget_revenue=0.99, budget_payroll=0.12, dividend=500_000,
    profile={
        "bransje": "Varehandel (grossist byggevarer)",
        "beskrivelse": "Grossist og proffbutikk for trelast, plater, isolasjon og festemidler til håndverkere.",
        "begrunnelse": "Om lag 70 % av omsetningen går til varekjøp, lageret er stort, og kundene er mange håndverkere på konto pluss kontantsalg. Det er marginen på varene som avgjør, ikke lønnen.",
        "sikkerhet": "høy",
        "hovedtall": "bruttomargin",
        "nokkeltall": [
            {"id": "bruttomargin", "hvorfor": "Hva som blir igjen av hver krone etter varekjøpet; det er hele forretningen for en grossist.", "mal": 25, "varsel": 21},
            {"id": "varekostandel", "hvorfor": "Stiger innkjøpsprisene uten at utsalgsprisene følger, er det her det synes først.", "mal": 75, "varsel": 79},
            {"id": "driftsmargin", "hvorfor": "Det som blir igjen etter lokaler, lager og lønn.", "mal": 4, "varsel": 2},
            {"id": "omsetning_per_ansatt", "hvorfor": "En grossist skal selge mye per ansatt.", "mal": 2500000, "varsel": 2000000},
            {"id": "betalingstid", "hvorfor": "Håndverkerne handler på konto; varene er betalt til leverandøren før de betaler dere.", "mal": 30, "varsel": 40},
            {"id": "vekst", "hvorfor": "Om dere tar andeler i et marked som følger byggeaktiviteten.", "mal": 5, "varsel": 0},
            {"id": "egenkapitalandel", "hvorfor": "Lageret skal være finansiert av egne penger, ikke av leverandørene.", "mal": 35, "varsel": 20}
        ]
    },
    company_md="""---
lonn_utbetalingsdag: 25
ferie_utbetalingsmnd: 6
likviditetsgulv_kr: 2 000 000
purring_etter_dager: 14
---

# Slik fungerer Aslefjord Byggvare

Grossist og proffbutikk for byggevarer: trelast, plater, isolasjon og
festemidler til håndverkere i regionen. Ni ansatte, butikk og lager på samme
tomt.

## Kundene

Faste håndverkere på konto med 30 dager, fakturert samlet den 20. hver
måned, og kontantsalg i butikken. Ingen kunde står for mer enn rundt en
åttendedel.

## Leverandører

Trelast fra Skogheim på 45 dager, resten på 30. Lageret holdes rundt fire
millioner.

## Sesong

Vår og høst er travlest. Juli og vinteren er rolige.
""",
)

SPECS = {s.slug: s for s in (LINDESKAR, KVARNHEIM, ASLEFJORD)}
