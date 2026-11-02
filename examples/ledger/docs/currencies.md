# Currencies

- Every amount in the ledger is an integer count of the currency's MINOR units.
- The number of decimal places of the minor unit (the exponent) differs by currency:
  JPY 0, USD 2, EUR 2, BHD 3, KWD 3. Never assume 2 decimals.
- `ledger.currencies.currency_exponent(code)` returns it. One major unit is 10**exponent minor units.
- A refund reverses the original charge at the rate STORED on that charge, never today's rate.
- A rate is USD major units per one major unit of the charge currency (JPY 0.0067 means 1 yen = 0.0067 USD).
  Convert major amounts, then express the result in the target currency's minor units.
- Rounding is half up at the target currency's minor unit.
