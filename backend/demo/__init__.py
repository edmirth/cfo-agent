"""Demo mode: made-up companies with whole books, for showing the product.

With CFO_DEMO=<slug> the server runs on one of the companies in
`companies.py`. Their books are generated (`books.py`) and answered in
Tripletex's own formats (`tripletex.py`), so every page, check and
conversation runs on them unchanged. Nothing in demo mode can reach the real
ledger: config never creates a Tripletex client or token, mail is off, and
Brønnøysund is not asked about companies that do not exist.
"""
