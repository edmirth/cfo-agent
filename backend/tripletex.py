"""Tripletex REST client, shaped for CFO questions rather than for the API.

Auth is Tripletex's three-token model: a consumer token (one per integration)
and an employee token (one per customer) are exchanged for a short-lived
session token, which is then the password in HTTP Basic with username "0".

Every call here is a GET. The client has no method that writes, so read-only is
a property of the code rather than a rule in a prompt.
"""
import asyncio
import base64
import logging
from datetime import date, timedelta

# The Anthropic SDK 1.x ships httpx2; reuse it rather than pulling in a
# second HTTP stack that would have to be kept in version sync.
import httpx2 as httpx

log = logging.getLogger("cfo.tripletex")

BASE = "https://tripletex.no/v2"

# Norwegian standard chart of accounts. (from, to, label, sign) where sign says
# whether the account group is naturally a credit (revenue) or debit (cost) —
# used to normalise everything to positive numbers.
PL_GROUPS = [
    (3000, 3999, "Driftsinntekter", "credit"),
    (4000, 4999, "Varekostnad", "debit"),
    (5000, 5999, "Lønnskostnad", "debit"),
    (6000, 6099, "Avskrivninger", "debit"),
    (6100, 7999, "Andre driftskostnader", "debit"),
    (8000, 8099, "Finansinntekter", "credit"),
    (8100, 8199, "Finanskostnader", "debit"),
    (8300, 8399, "Skattekostnad", "debit"),
]

BS_GROUPS = [
    (1000, 1999, "Eiendeler", "debit"),
    (2000, 2099, "Egenkapital", "credit"),
    (2100, 2999, "Gjeld", "credit"),
]


class TripletexError(RuntimeError):
    pass


class TripletexClient:
    def __init__(self, consumer_token: str, employee_token: str, base: str = BASE):
        if not consumer_token or not employee_token:
            raise TripletexError(
                "Mangler TRIPLETEX_CONSUMER_TOKEN eller TRIPLETEX_EMPLOYEE_TOKEN."
            )
        self._consumer = consumer_token
        self._employee = employee_token
        self._base = base.rstrip("/")
        self._session_token: str | None = None
        self._session_expires: date | None = None
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(timeout=60.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------- auth ----------

    async def _session(self) -> str:
        async with self._lock:
            today = date.today()
            if self._session_token and self._session_expires and self._session_expires > today:
                return self._session_token

            expiry = today + timedelta(days=1)
            r = await self._http.put(
                f"{self._base}/token/session/:create",
                params={
                    "consumerToken": self._consumer,
                    "employeeToken": self._employee,
                    "expirationDate": expiry.isoformat(),
                },
            )
            if r.status_code >= 400:
                raise TripletexError(
                    f"Kunne ikke opprette sesjonstoken ({r.status_code}). "
                    "Sjekk at consumer- og employee-token hører sammen og er gyldige."
                )
            token = (r.json().get("value") or {}).get("token")
            if not token:
                raise TripletexError("Sesjonstoken manglet i svaret fra Tripletex.")
            self._session_token, self._session_expires = token, expiry
            log.info("Tripletex session token created, valid to %s", expiry)
            return token

    async def _auth_header(self) -> dict[str, str]:
        token = await self._session()
        raw = base64.b64encode(f"0:{token}".encode()).decode()
        return {"Authorization": f"Basic {raw}"}

    # ---------- transport ----------

    async def get(self, path: str, **params) -> dict:
        """GET any Tripletex endpoint. The only verb this client implements."""
        params = {k: v for k, v in params.items() if v is not None}
        params.setdefault("count", 1000)
        r = await self._http.get(
            f"{self._base}/{path.lstrip('/')}",
            params=params,
            headers=await self._auth_header(),
        )
        if r.status_code == 401:
            # Session may have been revoked early; drop it and retry once.
            self._session_token = None
            r = await self._http.get(
                f"{self._base}/{path.lstrip('/')}",
                params=params,
                headers=await self._auth_header(),
            )
        if r.status_code >= 400:
            raise TripletexError(f"Tripletex {path} svarte {r.status_code}: {r.text[:400]}")
        return r.json()

    async def whoami(self) -> dict:
        return (await self.get("/token/session/>whoAmI")).get("value", {})

    # ---------- shaping helpers ----------

    @staticmethod
    def _rows(payload: dict) -> list[dict]:
        v = payload.get("value", payload)
        if isinstance(v, dict) and "rows" in v:
            return v["rows"] or []
        return payload.get("values") or (v if isinstance(v, list) else [])

    @staticmethod
    def _account_number(row: dict) -> int | None:
        acct = row.get("account") or {}
        num = acct.get("number") if isinstance(acct, dict) else None
        try:
            return int(str(num).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _movement(row: dict) -> float:
        for key in ("balanceChange", "sumAmount", "amount", "change"):
            if row.get(key) is not None:
                return float(row[key])
        # Fall back to out minus in when only balances are present.
        out, inn = row.get("balanceOut"), row.get("balanceIn")
        if out is not None and inn is not None:
            return float(out) - float(inn)
        return 0.0

    def _grouped(self, rows: list[dict], groups: list[tuple]) -> dict:
        """Bucket account rows into Norwegian statement groups, sign-normalised."""
        out = {label: {"total": 0.0, "accounts": []} for _, _, label, _ in groups}
        unmapped = []
        for row in rows:
            num = self._account_number(row)
            if num is None:
                continue
            raw = self._movement(row)
            for lo, hi, label, sign in groups:
                if lo <= num <= hi:
                    amount = -raw if sign == "credit" else raw
                    acct = row.get("account") or {}
                    out[label]["total"] += amount
                    out[label]["accounts"].append(
                        {"number": num, "name": acct.get("name"), "amount": round(amount, 2)}
                    )
                    break
            else:
                unmapped.append(num)
        for g in out.values():
            g["total"] = round(g["total"], 2)
            g["accounts"].sort(key=lambda a: -abs(a["amount"]))
        if unmapped:
            out["_unmapped_accounts"] = sorted(set(unmapped))
        return out

    # ---------- CFO-level queries ----------

    async def profit_and_loss(self, date_from: str, date_to: str) -> dict:
        payload = await self.get(
            "/balanceSheet", dateFrom=date_from, dateTo=date_to,
            accountNumberFrom=3000, accountNumberTo=8999,
        )
        g = self._grouped(self._rows(payload), PL_GROUPS)
        revenue = g["Driftsinntekter"]["total"]
        opex = sum(g[k]["total"] for k in
                   ("Varekostnad", "Lønnskostnad", "Avskrivninger", "Andre driftskostnader"))
        operating = revenue - opex
        net_finance = g["Finansinntekter"]["total"] - g["Finanskostnader"]["total"]
        pre_tax = operating + net_finance
        return {
            "period": {"from": date_from, "to_exclusive": date_to},
            "groups": g,
            "totals": {
                "driftsinntekter": round(revenue, 2),
                "sum_driftskostnader": round(opex, 2),
                "driftsresultat": round(operating, 2),
                "netto_finans": round(net_finance, 2),
                "resultat_for_skatt": round(pre_tax, 2),
                "skattekostnad_bokfort": g["Skattekostnad"]["total"],
                "driftsmargin_pct": round(operating / revenue * 100, 2) if revenue else None,
            },
            "note": "Beløp er fortegnsnormalisert: inntekter og kostnader er begge positive.",
        }

    async def balance_sheet(self, date_from: str, date_to: str) -> dict:
        payload = await self.get(
            "/balanceSheet", dateFrom=date_from, dateTo=date_to,
            accountNumberFrom=1000, accountNumberTo=2999,
        )
        rows = self._rows(payload)
        # A balance sheet is a position, so read closing balances, not movement.
        for r in rows:
            if r.get("balanceOut") is not None:
                r["balanceChange"] = r["balanceOut"]
        return {
            "as_of": date_to,
            "groups": self._grouped(rows, BS_GROUPS),
            "note": "Utgående saldo per as_of. Egenkapital og gjeld er vist positivt.",
        }

    async def monthly_trend(self, year: int, account_from: int = 3000,
                            account_to: int = 8999) -> dict:
        """Month-by-month movement, which is what a trend question needs."""
        today = date.today()
        months = []
        for m in range(1, 13):
            start = date(year, m, 1)
            if start > today:
                break
            end = date(year + 1, 1, 1) if m == 12 else date(year, m + 1, 1)
            months.append((start, min(end, today + timedelta(days=1))))

        async def one(start: date, end: date):
            payload = await self.get(
                "/balanceSheet", dateFrom=start.isoformat(), dateTo=end.isoformat(),
                accountNumberFrom=account_from, accountNumberTo=account_to,
            )
            return start, self._grouped(self._rows(payload), PL_GROUPS)

        results = await asyncio.gather(*(one(s, e) for s, e in months))
        out = []
        for start, g in results:
            revenue = g["Driftsinntekter"]["total"]
            opex = sum(g[k]["total"] for k in
                       ("Varekostnad", "Lønnskostnad", "Avskrivninger", "Andre driftskostnader"))
            out.append({
                "month": start.strftime("%Y-%m"),
                "driftsinntekter": round(revenue, 2),
                "lonnskostnad": g["Lønnskostnad"]["total"],
                "sum_driftskostnader": round(opex, 2),
                "driftsresultat": round(revenue - opex, 2),
            })
        partial = out[-1]["month"] if out and date.today().day < 28 else None
        return {"year": year, "months": out,
                "note": f"Siste måned ({partial}) er ufullstendig." if partial else None}

    async def budget(self, year: int) -> dict:
        payload = await self.get("/resultbudget/company", year=year)
        rows = payload.get("values") or []
        by_account: dict[int, dict] = {}
        for r in rows:
            acct = r.get("account") or {}
            try:
                num = int(str(acct.get("number")).strip())
            except (TypeError, ValueError):
                continue
            slot = by_account.setdefault(num, {"number": num, "name": acct.get("name"), "amount": 0.0})
            slot["amount"] += float(r.get("amount") or 0)
        for slot in by_account.values():
            slot["amount"] = round(slot["amount"], 2)
        return {"year": year, "accounts": sorted(by_account.values(), key=lambda a: a["number"])}

    async def receivables(self, as_of: str | None = None) -> dict:
        """Open customer posts: the AR ledger, aged and concentrated."""
        as_of_d = date.fromisoformat(as_of) if as_of else date.today()
        payload = await self.get("/ledger/openPost", date=(as_of_d + timedelta(days=1)).isoformat())
        rows = payload.get("values") or []

        buckets = {"ikke_forfalt": 0.0, "1_30": 0.0, "31_60": 0.0, "61_90": 0.0, "over_90": 0.0}
        by_customer: dict[str, dict] = {}
        total = 0.0

        for r in rows:
            cust = r.get("customer") or {}
            if not cust:
                continue  # supplier-side open posts belong to AP, not here
            amount = float(r.get("amount") or r.get("amountCurrency") or 0)
            if not amount:
                continue
            total += amount
            name = cust.get("name") or f"Kunde {cust.get('id')}"
            slot = by_customer.setdefault(name, {"customer": name, "amount": 0.0, "oldest_due": None})
            slot["amount"] += amount

            due = r.get("dueDate") or r.get("date")
            if due:
                try:
                    days = (as_of_d - date.fromisoformat(due)).days
                except ValueError:
                    days = 0
                if slot["oldest_due"] is None or due < slot["oldest_due"]:
                    slot["oldest_due"] = due
                key = ("ikke_forfalt" if days <= 0 else "1_30" if days <= 30
                       else "31_60" if days <= 60 else "61_90" if days <= 90 else "over_90")
                buckets[key] += amount

        ranked = sorted(by_customer.values(), key=lambda c: -c["amount"])
        for c in ranked:
            c["amount"] = round(c["amount"], 2)
            c["andel_pct"] = round(c["amount"] / total * 100, 2) if total else 0.0
        return {
            "as_of": as_of_d.isoformat(),
            "total": round(total, 2),
            "aldersfordeling": {k: round(v, 2) for k, v in buckets.items()},
            "kunder": ranked,
            "note": "Kundefordringer inkluderer mva. Grosse opp omsetning før DSO beregnes.",
        }

    async def revenue_by_customer(self, date_from: str, date_to: str) -> dict:
        payload = await self.get(
            "/ledger/posting", dateFrom=date_from, dateTo=date_to,
            accountNumberFrom=3000, accountNumberTo=3999, count=10000,
        )
        rows = payload.get("values") or []
        by_customer: dict[str, float] = {}
        for r in rows:
            cust = r.get("customer") or {}
            name = cust.get("name") or "Uten kunde"
            by_customer[name] = by_customer.get(name, 0.0) - float(r.get("amount") or 0)
        total = sum(by_customer.values())
        ranked = [{"customer": k, "omsetning": round(v, 2),
                   "andel_pct": round(v / total * 100, 2) if total else 0.0}
                  for k, v in sorted(by_customer.items(), key=lambda kv: -kv[1])]
        cum = 0.0
        for row in ranked:
            cum += row["andel_pct"]
            row["akkumulert_pct"] = round(cum, 2)
        return {"period": {"from": date_from, "to_exclusive": date_to},
                "total": round(total, 2), "kunder": ranked,
                "note": "Datterselskaper telles hver for seg — rull opp til konsern selv."}
