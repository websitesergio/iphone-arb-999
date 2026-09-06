#!/usr/bin/env python3
"""
Scanner arbitraj iPhone 999.md (Chisinau, persoane fizice, mana a 2-a).
Ruleaza in GitHub Actions (nu-i blocat ca sandbox-ul Claude). Printeaza
deal-urile la stdout intr-un bloc delimitat, ca sa fie citite din loguri.

Scoring auto-referential: mediana + P25 per (model, memorie) din anunturile
reale scrapuite. Deal = pret <= P25 si >= DEAL_THRESHOLD sub mediana, PF,
folosit, exclude spart/iCloud/accesorii. Zero preturi inventate.
"""
import os, re, json, statistics, sys
from playwright.sync_api import sync_playwright

PAGES          = int(os.environ.get("PAGES", "8"))
MIN_GROUP      = int(os.environ.get("MIN_GROUP", "4"))
DEAL_THRESHOLD = float(os.environ.get("DEAL_THRESHOLD", "0.15"))
FEE_EUR        = float(os.environ.get("FEE_EUR", "15"))
FX = {"€": 1.0, "EUR": 1.0, "LEI": 1/19.5, "MDL": 1/19.5, "$": 0.92, "USD": 0.92}

# URL-uri candidate (structura 999 se schimba; folosim primul care da anunturi)
CANDIDATES = [
    "https://999.md/ro/search?query=iphone",
    "https://999.md/ro/list/electronics/mobile-phones",
    "https://999.md/ro/list/electronics-and-appliances/mobile-phones",
    "https://999.md/ro/list/electronics/phones",
]

BAD = re.compile(r"(spart|crapat|cr[aă]p|defect|nefunc|pe piese|icloud|blocat|"
                 r"activation lock|cont apple|reparat|cumpar|caut|schimb|hus[aă]|"
                 r"sticl[aă]|folie|cablu|incarcator|încărc|carcas|copie|replica|clon)", re.I)
COMPANY = re.compile(r"(magazin|store|srl|garanti|factura|credit|showroom|import)", re.I)
MODEL_RE = re.compile(r"iphone\s*(1[0-6]|[5-9]|se)\s*(pro\s*max|pro|plus|mini|se|fe)?", re.I)
STORAGE_RE = re.compile(r"\b(1\s?tb|64|128|256|512)\s*(gb|tb)?\b", re.I)
PRICE_RE = re.compile(r"([0-9][0-9 .,]{1,9})\s*(€|eur|lei|mdl|\$|usd)", re.I)

JS_EXTRACT = r"""
() => {
  const out = []; const seen = new Set();
  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href') || '';
    const m = href.match(/^\/ro\/(\d{6,})/);
    if (!m) return;
    const id = m[1]; if (seen.has(id)) return;
    const title = (a.textContent || '').replace(/\s+/g, ' ').trim();
    if (title.length < 6) return;
    const card = a.closest('li,article,div');
    const text = (card ? card.textContent : '').replace(/\s+/g, ' ');
    const pm = text.match(/([0-9][0-9 .,]{1,9})\s*(€|eur|lei|mdl|\$|usd)/i);
    seen.add(id);
    out.push({ id, url: 'https://999.md' + href.split('?')[0], title, price: pm ? pm[0] : '' });
  });
  return out;
}
"""


def to_eur(raw):
    if not raw:
        return None
    m = PRICE_RE.search(raw)
    if not m:
        return None
    num = re.sub(r"[^\d]", "", m.group(1))
    if not num:
        return None
    rate = FX.get(m.group(2).upper())
    return round(int(num) * rate, 1) if rate else None


def norm_model(t):
    mm = MODEL_RE.search(t)
    if not mm:
        return None, None
    model = ("iPhone " + mm.group(1).upper() + " " + (mm.group(2) or "").strip()).strip()
    sm = STORAGE_RE.search(t)
    storage = None
    if sm:
        storage = (sm.group(1).replace(" ", "") + (sm.group(2) or "gb")).upper()
    return model, storage


def scan():
    ads, used_url = {}, None
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            locale="ro-RO")
        page = ctx.new_page()

        # gaseste URL-ul de listing care functioneaza
        for cand in CANDIDATES:
            try:
                page.goto(cand, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                items = page.evaluate(JS_EXTRACT)
            except Exception as e:
                print(f"[skip] {cand}: {e}", file=sys.stderr)
                continue
            if items and len(items) >= 3:
                used_url = cand
                print(f"[ok] listing: {cand} ({len(items)} anunturi pe pag 1)", file=sys.stderr)
                break
        if not used_url:
            title = page.title()
            print(f"[FATAL] niciun URL de listing valid. Ultimul titlu pagina: {title!r}",
                  file=sys.stderr)
            b.close()
            return [], None

        for pg in range(1, PAGES + 1):
            sep = "&" if "?" in used_url else "?"
            url = used_url if pg == 1 else f"{used_url}{sep}page={pg}"
            try:
                if pg > 1:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2000)
                items = page.evaluate(JS_EXTRACT)
            except Exception as e:
                print(f"[skip pag {pg}] {e}", file=sys.stderr)
                break
            new = 0
            for it in items:
                if it["id"] in ads:
                    continue
                model, storage = norm_model(it["title"])
                ads[it["id"]] = {
                    "advert_id": it["id"], "url": it["url"], "title": it["title"][:160],
                    "price_eur": to_eur(it["price"]), "model": model, "storage": storage,
                    "condition": "nou" if re.search(r"(nou|sigilat|new|sealed)", it["title"], re.I) else "folosit",
                    "seller_hint": "firma?" if COMPANY.search(it["title"]) else "pf",
                }
                new += 1
            print(f"[pag {pg}] +{new} anunturi (total {len(ads)})", file=sys.stderr)
            if new == 0:
                break
        b.close()
    return list(ads.values()), used_url


def score(ads):
    valid = [a for a in ads if a["model"] and a["price_eur"]]
    groups = {}
    for a in valid:
        a["grp"] = f'{a["model"]}|{a["storage"] or "?"}'
        groups.setdefault(a["grp"], []).append(a["price_eur"])
    stats = {}
    for g, pr in groups.items():
        if len(pr) < MIN_GROUP:
            continue
        s = sorted(pr)
        stats[g] = (statistics.median(s), s[max(0, int(len(s) * 0.25) - 1)])
    deals = []
    for a in valid:
        if a["grp"] not in stats:
            continue
        med, p25 = stats[a["grp"]]
        a["group_median"] = round(med, 1)
        a["deal_score"] = round((med - a["price_eur"]) / med, 3)
        a["est_profit_eur"] = round(med - a["price_eur"] - FEE_EUR, 1)
        if (a["seller_hint"] == "pf" and a["condition"] == "folosit"
                and a["price_eur"] <= p25 and a["deal_score"] >= DEAL_THRESHOLD
                and a["est_profit_eur"] > 0 and not BAD.search(a["title"])):
            deals.append(a)
    deals.sort(key=lambda x: (x["est_profit_eur"], x["deal_score"]), reverse=True)
    return valid, deals


def main():
    ads, used = scan()
    valid, deals = score(ads)
    print("\n" + "=" * 70)
    print(f"REZUMAT: {len(ads)} anunturi | {len(valid)} cu model+pret | {len(deals)} DEAL-URI")
    print("=" * 70)
    for d in deals[:30]:
        print(f'€{d["price_eur"]:>6.0f} | med €{d["group_median"]:>5.0f} | '
              f'+€{d["est_profit_eur"]:>5.0f} ({d["deal_score"]*100:>4.1f}%) | '
              f'{d["grp"]:<22} | {d["title"][:52]} | {d["url"]}')
    # bloc JSON usor de parsat din loguri
    print("\n<<<DEALS_JSON>>>")
    print(json.dumps(deals[:30], ensure_ascii=False))
    print("<<<END_DEALS_JSON>>>")


if __name__ == "__main__":
    main()
