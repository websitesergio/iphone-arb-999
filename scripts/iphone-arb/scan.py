#!/usr/bin/env python3
"""
Scanner arbitraj iPhone 999.md (Chisinau, mana a 2-a).
Ruleaza in GitHub Actions. Printeaza deal-urile la stdout + bloc JSON.

Scoring auto-referential: mediana + P25 per (model, memorie) din anunturile
reale scrapuite. Deal = pret <= P25 si >= DEAL_THRESHOLD sub mediana,
folosit, memorie cunoscuta, exclude cumparatori/firme/defecte/accesorii.
Preturi reale (nu inventate); pretul e extras din textul anuntului.
"""
import os, re, json, statistics, sys
from playwright.sync_api import sync_playwright

PAGES          = int(os.environ.get("PAGES", "8"))
MIN_GROUP      = int(os.environ.get("MIN_GROUP", "4"))
DEAL_THRESHOLD = float(os.environ.get("DEAL_THRESHOLD", "0.15"))
FEE_EUR        = float(os.environ.get("FEE_EUR", "15"))
PRICE_MIN_EUR  = float(os.environ.get("PRICE_MIN_EUR", "40"))   # sub asta = accesoriu/gunoi
PRICE_MAX_EUR  = float(os.environ.get("PRICE_MAX_EUR", "2500"))  # peste asta = parse gresit
RATE = {"MDL": 1/19.5, "LEI": 1/19.5, "€": 1.0, "EUR": 1.0, "$": 0.92, "USD": 0.92}

CANDIDATES = [
    "https://999.md/ro/list/phone-and-communication/mobile-phones?query=iphone",
    "https://999.md/ro/search?query=iphone",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# exclude: cautari (cumpar/куплю/schimb), defecte, iCloud, accesorii
BAD = re.compile(
    r"(cump[ăa]r|куплю|schimb|обмен|spart|cr[aă]pat|cr[aă]p\b|defect|nefunc|"
    r"pe piese|на запчаст|icloud|blocat|activation lock|cont apple|reparat|"
    r"hus[ăa]|чехол|sticl[ăa]|folie|стекло|cablu|кабель|incarcator|încărc|"
    r"зарядк|carcas|копия|copie|replica|clon|adaptor)", re.I)
# firme/reselleri (euristic pe titlu; imperfect - vezi nota enrichment)
COMPANY = re.compile(
    r"(magazin|store|srl|garan[țt]|credit|în rate|in rate|showroom|import|"
    r"darwin|enter|ishop|itotal|maxphone|gsm|optimus|ultra\.?md|kct)", re.I)

MODEL_RE = re.compile(r"iphone\s*(1[0-6]|[5-9]|se)\s*(pro\s*max|pro|plus|mini|se|fe)?", re.I)
STORAGE_RE = re.compile(r"\b(1\s?tb|512|256|128|64)\s*(gb|tb|гб)", re.I)
PRICE_RE = re.compile(r"(\d[\d  .]{0,8}\d|\d)\s*(mdl|lei|€|eur|\$|usd)", re.I)

JS_EXTRACT = r"""
() => {
  const out = []; const seen = new Set();
  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href') || '';
    const m = href.match(/^\/ro\/(\d{5,})/);
    if (!m) return;
    const id = m[1]; if (seen.has(id)) return;
    const raw = (a.textContent || '').replace(/\s+/g, ' ').trim();
    if (raw.length < 6) return;
    seen.add(id);
    out.push({ id, url: 'https://999.md' + href.split('?')[0], raw });
  });
  return out;
}
"""


def parse_price(raw):
    """Primul pret plauzibil dinaintea unui simbol de moneda (curent, nu cel taiat)."""
    for m in PRICE_RE.finditer(raw):
        num = re.sub(r"[^\d]", "", m.group(1))
        if not num:
            continue
        val = round(int(num) * RATE[m.group(2).upper()], 1)
        if PRICE_MIN_EUR <= val <= PRICE_MAX_EUR:
            return val, m.start()
    return None, None


def norm_model(t):
    mm = MODEL_RE.search(t)
    if not mm:
        return None, None
    model = ("iPhone " + mm.group(1).upper() + " " + (mm.group(2) or "").strip()).strip()
    sm = STORAGE_RE.search(t)
    storage = None
    if sm:
        storage = (sm.group(1).replace(" ", "") + "GB").upper().replace("TBGB", "TB")
    return model, storage


def scan():
    ads, used_url = {}, None
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context(user_agent=UA, locale="ro-RO").new_page()

        for cand in CANDIDATES:
            try:
                page.goto(cand, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_selector('a[href^="/ro/"]', timeout=20000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                items = page.evaluate(JS_EXTRACT)
            except Exception as e:
                print(f"[skip] {cand}: {e}", file=sys.stderr)
                continue
            if items and len(items) >= 3:
                used_url = cand
                print(f"[ok] listing: {cand} ({len(items)} anunturi pag 1)", file=sys.stderr)
                break
        if not used_url:
            print(f"[FATAL] niciun URL valid. Titlu: {page.title()!r}", file=sys.stderr)
            b.close()
            return []

        for pg in range(1, PAGES + 1):
            sep = "&" if "?" in used_url else "?"
            url = used_url if pg == 1 else f"{used_url}{sep}page={pg}"
            try:
                if pg > 1:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    try:
                        page.wait_for_selector('a[href^="/ro/"]', timeout=20000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1500)
                items = page.evaluate(JS_EXTRACT)
            except Exception as e:
                print(f"[skip pag {pg}] {e}", file=sys.stderr)
                break
            new = 0
            for it in items:
                if it["id"] in ads:
                    continue
                raw = it["raw"]
                price, pidx = parse_price(raw)
                model, storage = norm_model(raw)
                title = (raw[:pidx] if pidx else raw).strip()[:120]
                ads[it["id"]] = {
                    "advert_id": it["id"], "url": it["url"], "title": title,
                    "price_eur": price, "model": model, "storage": storage,
                    "condition": "nou" if re.search(r"(sigilat|nou nou|new|sealed)", raw, re.I) else "folosit",
                    "seller_hint": "firma?" if COMPANY.search(raw) else "pf?",
                    "bad": bool(BAD.search(raw)),
                }
                new += 1
            print(f"[pag {pg}] +{new} (total {len(ads)})", file=sys.stderr)
            if new == 0:
                break
        b.close()
    return list(ads.values())


def score(ads):
    # doar anunturi valorabile: model + pret + MEMORIE cunoscuta, fara flag rau
    valid = [a for a in ads if a["model"] and a["price_eur"] and a["storage"] and not a["bad"]]
    groups = {}
    for a in valid:
        a["grp"] = f'{a["model"]}|{a["storage"]}'
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
        if (a["seller_hint"] == "pf?" and a["price_eur"] <= p25
                and a["deal_score"] >= DEAL_THRESHOLD and a["est_profit_eur"] > 0):
            deals.append(a)
    deals.sort(key=lambda x: (x["est_profit_eur"], x["deal_score"]), reverse=True)
    return valid, deals


def main():
    ads = scan()
    valid, deals = score(ads)
    print("\n" + "=" * 70)
    print(f"REZUMAT: {len(ads)} anunturi | {len(valid)} valorabile (model+pret+mem) | {len(deals)} DEAL-URI")
    print("=" * 70)
    for d in deals[:30]:
        print(f'€{d["price_eur"]:>5.0f} | med €{d["group_median"]:>4.0f} | '
              f'+€{d["est_profit_eur"]:>4.0f} ({d["deal_score"]*100:>4.1f}%) | '
              f'{d["seller_hint"]:<6} | {d["grp"]:<22} | {d["title"][:44]} | {d["url"]}')
    print("\n<<<DEALS_JSON>>>")
    print(json.dumps(deals[:30], ensure_ascii=False))
    print("<<<END_DEALS_JSON>>>")


if __name__ == "__main__":
    main()
