#!/usr/bin/env python3
"""
Scanner arbitraj iPhone 999.md (Chisinau, mana a 2-a) + enrichment descriere.

Pas 1: scaneaza listingul, extrage model/memorie/pret (din titlu).
Pas 2: scor auto-referential (mediana + P25 per model+memorie).
Pas 3: ENRICHMENT - pe fiecare candidat de deal intra pe pagina lui si
       citeste DESCRIEREA (RO/RU/EN): Face ID / Touch ID mort, iCloud blocat,
       baterie %, magazin vs persoana fizica. Ce-i defect -> afara.
"""
import os, re, json, statistics, sys, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

PAGES          = int(os.environ.get("PAGES", "8"))
MIN_GROUP      = int(os.environ.get("MIN_GROUP", "4"))
DEAL_THRESHOLD = float(os.environ.get("DEAL_THRESHOLD", "0.15"))
FEE_EUR        = float(os.environ.get("FEE_EUR", "15"))
MIN_BATTERY    = int(os.environ.get("MIN_BATTERY", "80"))   # sub asta = flag baterie slaba
PRICE_MIN_EUR  = float(os.environ.get("PRICE_MIN_EUR", "40"))
PRICE_MAX_EUR  = float(os.environ.get("PRICE_MAX_EUR", "2500"))
MAX_ENRICH     = int(os.environ.get("MAX_ENRICH", "45"))    # cate pagini de detaliu deschidem
MIN_PROFIT     = float(os.environ.get("MIN_PROFIT", "50"))  # profit NET minim ca sa trimita
PEN_ECRAN      = float(os.environ.get("PEN_ECRAN", "40"))   # penalizare ecran schimbat (aftermarket)
PEN_BAT_LOW    = float(os.environ.get("PEN_BAT_LOW", "35")) # baterie < MIN_BATTERY
PEN_BAT_VLOW   = float(os.environ.get("PEN_BAT_VLOW", "55")) # baterie < 75%
RATE = {"MDL": 1/19.5, "LEI": 1/19.5, "€": 1.0, "EUR": 1.0, "$": 0.92, "USD": 0.92}

CANDIDATES = [
    "https://999.md/ro/list/phone-and-communication/mobile-phones?query=iphone",
    "https://999.md/ro/search?query=iphone",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# --- filtre pe titlu (cheap, prima linie) ---
BAD_TITLE = re.compile(
    r"(cump[ăa]r|куплю|schimb|обмен|spart|cr[aă]pat|defect|nefunc|pe piese|"
    r"на запчаст|icloud|blocat|hus[ăa]|чехол|sticl[ăa]|folie|стекло|cablu|"
    r"кабель|incarcator|încărc|зарядк|carcas|копия|copie|replica|clon|adaptor)", re.I)
COMPANY = re.compile(
    r"(magazin|магазин|store|srl|showroom|import|darwin|ishop|itotal|maxphone|"
    r"optimus|ultra\.?md|enter\.md|kct|gsm\b)", re.I)
MODEL_RE = re.compile(r"iphone\s*(1[0-6]|[5-9]|se)\s*(pro\s*max|pro|plus|mini|se|fe)?", re.I)
STORAGE_RE = re.compile(r"\b(1\s?tb|512|256|128|64)\s*(gb|tb|гб)", re.I)
PRICE_RE = re.compile(r"(\d[\d  .]{0,8}\d|\d)\s*(mdl|lei|€|eur|\$|usd)", re.I)

# --- detectie in DESCRIERE (RO/RU/EN) ---
FACEID = re.compile(r"face\s?id|фейс[\s-]?айди|фейсид|\bфейс\b|\bфэйс\b", re.I)
TOUCHID = re.compile(r"touch\s?id|тач[\s-]?айди|\bтач\b|отпечаток|amprent", re.I)
# defect langa feature (specific, ca sa nu dea fals pozitiv pe "nu are probleme")
# include "krome/in afara de/except" = "totul merge EXCEPT <feature>"
BROKEN = re.compile(
    r"(nu\s?(merge|funcț|funct|lucreaz|porne|se\s?deschide)|defect|stricat|mort|"
    r"nu\s?e\s?activ|не\s?работает|не\s?раб\b|неисправ|не\s?включ|проблем\w*\s?с|"
    r"кроме|cu\s?excep[țt]|[îi]n\s?afar[ăa]\s?de|except|apart\s?from|"
    r"not\s?work|doesn.?t\s?work|broken|dead|faulty|issue|неисправен)", re.I)
ABSENT = re.compile(r"(нет|без|no\b|f[ăa]r[ăa]|lipsă|lipse)\s*(face\s?id|touch\s?id|фейс|тач)", re.I)
ICLOUD = re.compile(
    r"(icloud|активац|аккаунт\s?apple|cont\s?apple).{0,25}(blocat|заблок|lock|привяз|активн)|"
    r"(blocat|заблок|lock|привяз).{0,25}(icloud|аккаунт|активац)", re.I)
BAT_NEAR = re.compile(
    r"(?:baterie|acumulator|battery|аккумул\w*|батар\w*|\bакб\b|акум\w*|состояние)\D{0,15}(\d{2,3})\s?%|"
    r"(\d{2,3})\s?%\D{0,15}(?:baterie|acumulator|battery|аккумул|батар|акб|акум)", re.I)
BAT_ANY = re.compile(r"\b(\d{2,3})\s?%")
SHOP_DESC = re.compile(
    r"(în\s?rate|in\s?rate|credit|кредит|в\s?рассрочку|рассрочк|гаранți|гарантия\s?магаз|"
    r"program\s?de\s?lucru|график\s?работы|adresa\s?magazin|наш\s?магазин|showroom)", re.I)


def parse_price(raw):
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
    storage = (sm.group(1).replace(" ", "") + "GB").upper().replace("TBGB", "TB") if sm else None
    return model, storage


def issue_near(text, feat_re):
    for m in feat_re.finditer(text):
        w = text[max(0, m.start() - 32): m.end() + 32]
        if BROKEN.search(w):
            return True
    return False


def find_battery(text):
    m = BAT_NEAR.search(text)
    if m:
        v = int(m.group(1) or m.group(2))
        if 50 <= v <= 100:
            return v
    for m in BAT_ANY.finditer(text):
        v = int(m.group(1))
        if 60 <= v <= 100:   # % standalone plauzibil pentru baterie
            return v
    return None


JS_LIST = r"""
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


# selectoare posibile pentru blocul descrierii (folosim primul cu text)
DESC_SEL = ("[itemprop='description']", ".adPage__content__description",
            ".adPage__content__description__text", "div.js-description",
            "[class*='description']", "[class*='Description']")


def get_desc(page):
    for sel in DESC_SEL:
        try:
            el = page.query_selector(sel)
            if el:
                t = (el.inner_text() or "").strip()
                if len(t) > 15:
                    return t, sel
        except Exception:
            pass
    try:
        return page.inner_text("body"), "body"
    except Exception:
        return "", "none"


def enrich(page, ad):
    """Deschide pagina anuntului, citeste DOAR descrierea, seteaza flag-urile."""
    ad["enriched"] = False
    ad["flags"] = []
    ad["battery"] = None
    ad["scope"] = None
    try:
        page.goto(ad["url"], wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(1300)
        desc, scope = get_desc(page)
    except Exception:
        ad["flags"].append("enrich_fail")
        return
    ad["enriched"] = True
    ad["scope"] = scope
    low = " ".join(((ad.get("title") or "") + " " + desc).split()).lower()
    ad["snippet"] = low[:200]
    if issue_near(low, FACEID) or (ABSENT.search(low) and re.search(r"face\s?id|фейс", low)):
        ad["flags"].append("faceid_defect")
    if issue_near(low, TOUCHID):
        ad["flags"].append("touchid_defect")
    if ICLOUD.search(low):
        ad["flags"].append("icloud")
    if re.search(r"spart|cr[ăa]pat|разбит|треснут|pe\s?piese|на\s?запчаст", low):
        ad["flags"].append("defect")
    if re.search(r"ecran\s?schimbat|display\s?schimbat|дисплей\s?замен|экран\s?замен|"
                 r"screen\s?replaced|копия\s?экран|неоригинал", low):
        ad["flags"].append("ecran_schimbat")   # avertisment: scade valoarea
    if COMPANY.search(low) or SHOP_DESC.search(low):
        ad["flags"].append("magazin")   # doar avertisment, nu elimina
    # scam / bot / lead-harvest: cer numarul TAU, te suna ei, privat/WhatsApp, avans
    scam = bool(re.search(
        r"(las[ăa]?[\s-]*(mi|ne)?[\s-]*(num[ăa]r|nr)|num[ăa]r(ul)?\s+(t[ăa]u|vostru|dvs|dumneavoastr)|"
        r"оставь\w*\s+(свой\s+)?(номер|тел)|скинь\w*\s+номер|ваш\s+номер|"
        r"v[ăa]\s?sun\b|te\s?sun\s?eu|\bsun\s?eu\b|перезвон|я\s?перезвоню|"
        r"пишите\s+(в\s+)?(лс|личк|ватсап|whats?app|вайбер|viber|телеграм|telegram)|"
        r"scrie[țt]i?\s+(doar\s+)?(în|in)\s+(privat|pm|mesaj))", low))
    if re.search(r"\b(avans|arvun|предоплат\w*|аванс)\b", low) and not \
       re.search(r"(f[ăa]r[ăa]|fara|без)\s+\w{0,6}\s?(avans|предоплат|аванс|arvun)", low):
        scam = True
    if scam:
        ad["flags"].append("scam?")
    bat = find_battery(low)
    ad["battery"] = bat
    if bat is not None and bat < MIN_BATTERY:
        ad["flags"].append(f"baterie_{bat}%")


def run():
    ads = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context(user_agent=UA, locale="ro-RO").new_page()

        used = None
        for cand in CANDIDATES:
            try:
                page.goto(cand, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_selector('a[href^="/ro/"]', timeout=20000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                items = page.evaluate(JS_LIST)
            except Exception as e:
                print(f"[skip] {cand}: {e}", file=sys.stderr)
                continue
            if items and len(items) >= 3:
                used = cand
                print(f"[ok] {cand} ({len(items)} pag1)", file=sys.stderr)
                break
        if not used:
            print(f"[FATAL] niciun URL valid. Titlu: {page.title()!r}", file=sys.stderr)
            b.close()
            return [], 0, 0

        for pg in range(1, PAGES + 1):
            sep = "&" if "?" in used else "?"
            url = used if pg == 1 else f"{used}{sep}page={pg}"
            try:
                if pg > 1:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    try:
                        page.wait_for_selector('a[href^="/ro/"]', timeout=20000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1500)
                items = page.evaluate(JS_LIST)
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
                ads[it["id"]] = {
                    "advert_id": it["id"], "url": it["url"],
                    "title": (raw[:pidx] if pidx else raw).strip()[:120],
                    "price_eur": price, "model": model, "storage": storage,
                    "bad_title": bool(BAD_TITLE.search(raw) or COMPANY.search(raw)),
                }
                new += 1
            print(f"[pag {pg}] +{new} (total {len(ads)})", file=sys.stderr)
            if new == 0:
                break

        all_ads = list(ads.values())
        # scoring pe titlu -> candidati
        valid = [a for a in all_ads if a["model"] and a["price_eur"] and a["storage"] and not a["bad_title"]]
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
        candidates = []
        for a in valid:
            if a["grp"] not in stats:
                continue
            med, p25 = stats[a["grp"]]
            a["group_median"] = round(med, 1)
            a["deal_score"] = round((med - a["price_eur"]) / med, 3)
            a["est_profit_eur"] = round(med - a["price_eur"] - FEE_EUR, 1)
            if a["price_eur"] <= p25 and a["deal_score"] >= DEAL_THRESHOLD and a["est_profit_eur"] > 0:
                candidates.append(a)
        candidates.sort(key=lambda x: (x["est_profit_eur"], x["deal_score"]), reverse=True)

        # ENRICHMENT pe candidati (descriere)
        print(f"[enrich] {min(len(candidates), MAX_ENRICH)} candidati -> citesc descrierile...", file=sys.stderr)
        for a in candidates[:MAX_ENRICH]:
            enrich(page, a)
            print(f"[cand] {a['advert_id']} {a['grp']} €{a['price_eur']:.0f} "
                  f"scope={a.get('scope')} bat={a.get('battery')} flags={a.get('flags')} "
                  f":: {a.get('snippet','')[:130]}", file=sys.stderr)

        b.close()

    # filtru final:
    #  MAJOR (faceid/touchid mort, iCloud, spart) -> AFARA (nu-s "minore").
    #  MINOR (ecran schimbat, baterie slaba) -> PENALIZARE din profit;
    #  ramane doar daca profitul NET >= MIN_PROFIT.
    KILL_MAJOR = {"faceid_defect", "touchid_defect", "icloud", "defect", "scam?"}
    deals = []
    for a in candidates:
        if not a.get("enriched") or (set(a.get("flags", [])) & KILL_MAJOR):
            continue
        pen = 0.0
        if "ecran_schimbat" in a.get("flags", []):
            pen += PEN_ECRAN
        bat = a.get("battery")
        if bat is not None and bat < MIN_BATTERY:
            pen += PEN_BAT_VLOW if bat < 75 else PEN_BAT_LOW
        a["penalty_eur"] = round(pen, 1)
        a["net_profit_eur"] = round(a["est_profit_eur"] - pen, 1)
        if a["net_profit_eur"] >= MIN_PROFIT:
            deals.append(a)
    deals.sort(key=lambda x: x["net_profit_eur"], reverse=True)
    return deals, len(all_ads), len(valid)


SEEN_FILE = os.environ.get("SEEN_FILE", "state/seen.json")


def load_seen():
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(ids):
    try:
        os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(ids)[-800:], f)   # pastram ultimele 800
    except Exception as e:
        print(f"[state] save fail: {e}", file=sys.stderr)


def tg_send(token, chat, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20)
        return True
    except Exception as e:
        print(f"[tg] fail: {e}", file=sys.stderr)
        return False


def fmt_tg(d):
    mdl = f'{round(d["price_eur"] * 19.5 / 100) * 100:,}'.replace(",", ".")
    bat = f'🔋 {d["battery"]}%' if d.get("battery") else '🔋 ?'
    minor = [f for f in d.get("flags", []) if f]
    pen = d.get("penalty_eur", 0)
    emoji = "🟡" if pen else "🟢"
    pen_note = f" (după −€{pen:.0f} problemă)" if pen else ""
    warn = ("\n⚠️ " + ", ".join(minor)) if minor else ""
    return (f'{emoji} {d["grp"].replace("|", " ")} — €{d["price_eur"]:.0f} (~{mdl} lei)\n'
            f'{bat} | profit net +€{d["net_profit_eur"]:.0f}{pen_note} · piață €{d["group_median"]:.0f}'
            f'{warn}\n{d["url"]}')


def main():
    deals, n_ads, n_valid = run()
    print("\n" + "=" * 74)
    print(f"REZUMAT: {n_ads} anunturi | {n_valid} evaluabile | {len(deals)} DEAL-URI CURATE (dupa descriere)")
    print("=" * 74)
    for d in deals[:30]:
        bat = f'{d["battery"]}%bat' if d.get("battery") else 'bat?'
        fl = (",".join(d.get("flags", [])) or "ok")
        print(f'€{d["price_eur"]:>5.0f} | NET +€{d["net_profit_eur"]:>4.0f} | brut +€{d["est_profit_eur"]:>4.0f} | '
              f'pen €{d.get("penalty_eur",0):>3.0f} | med €{d["group_median"]:>4.0f} | {bat:>7} | '
              f'{d["grp"]:<22} | {d["title"][:36]} | {fl} | {d["url"]}')
    print("\n<<<DEALS_JSON>>>")
    print(json.dumps(deals[:30], ensure_ascii=False))
    print("<<<END_DEALS_JSON>>>")

    # --- Telegram: doar deal-uri NOI (dedup via state/seen.json) ---
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    force = os.environ.get("FORCE_ALL") == "1"
    seen = load_seen()
    new = deals if force else [d for d in deals if d["advert_id"] not in seen]
    if token and chat:
        sent = 0
        for d in new[:15]:
            if tg_send(token, chat, fmt_tg(d)):
                sent += 1
        print(f"[tg] trimis {sent}/{len(new)} deal-uri noi (force={force})", file=sys.stderr)
    else:
        print("[tg] fara credentiale (seteaza secrets TELEGRAM_BOT_TOKEN/CHAT_ID)", file=sys.stderr)
    save_seen(seen | {d["advert_id"] for d in deals})


if __name__ == "__main__":
    main()
