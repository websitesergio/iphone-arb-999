# iphone-arb-999

Robot de arbitraj iPhone pe [999.md](https://999.md) — Chișinău, persoane fizice, mâna a 2-a.

## Ce face
- `scripts/iphone-arb/scan.py` — scanează listările de iPhone (Playwright headless),
  normalizează model/memorie/preț și scorează arbitrajul.
- `.github/workflows/iphone-arb.yml` — rulează la fiecare 6h + manual (workflow_dispatch);
  printează deal-urile ranked în logurile rulării.

## Scoring (auto-referențial, zero prețuri inventate)
Grupează pe `(model, memorie)`, calculează mediana + P25 din anunțurile reale scrapuite.
Un **deal** = preț ≤ P25 **și** ≥15% sub mediană, de la **persoană fizică**, **folosit**,
fără `spart / iCloud / defect / accesoriu`. `profit_est = mediană − preț − fee`.

## Reglaje (env în workflow)
`PAGES`, `MIN_GROUP`, `DEAL_THRESHOLD` (0.15), `FEE_EUR` (15).

## Rulare manuală
Actions → *iPhone Arbitraj 999.md* → Run workflow. Rezultatele apar în logul jobului
(bloc `<<<DEALS_JSON>>>`).
