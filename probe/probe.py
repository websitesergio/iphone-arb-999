#!/usr/bin/env python3
"""Sonda de descoperire: afla structura reala 999.md (URL listing + format link anunt)."""
import re
from playwright.sync_api import sync_playwright

URLS = [
    "https://999.md/ro",
    "https://999.md/ro/search?query=iphone",
    "https://999.md/ro/list/electronics",
    "https://999.md/ro/list/electronics-and-appliances",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

JS = r"""
() => {
  const all = [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'));
  const uniq = [...new Set(all)].filter(h => h && h.startsWith('/'));
  // link-uri care par anunturi (contin secventa lunga de cifre)
  const adlike = uniq.filter(h => /\d{5,}/.test(h)).slice(0, 40);
  // link-uri de categorie (contin /list/ sau /ro/... fara cifre)
  const cats = uniq.filter(h => /\/list\/|catalog|electronic|phone|telefo/i.test(h)).slice(0, 40);
  return {
    url: location.href, title: document.title,
    bodyLen: document.body ? document.body.innerText.length : 0,
    nAnchors: uniq.length, adlike, cats,
    sample: uniq.slice(0, 50),
  };
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_context(user_agent=UA, locale="ro-RO").new_page()
    for u in URLS:
        try:
            page.goto(u, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)
            info = page.evaluate(JS)
        except Exception as e:
            print(f"\n##### {u}\n[ERROR] {e}")
            continue
        print(f"\n########## IN: {u}")
        print(f"FINAL : {info['url']}")
        print(f"TITLE : {info['title']}")
        print(f"BODYLEN: {info['bodyLen']}  ANCHORS: {info['nAnchors']}")
        cf = re.search(r"just a moment|cloudflare|verify you are human", info['title'], re.I)
        print(f"CLOUDFLARE?: {bool(cf)}")
        print("-- AD-LIKE (cifre lungi) --")
        for h in info['adlike']:
            print("  ", h)
        print("-- CATEGORY-LIKE --")
        for h in info['cats']:
            print("  ", h)
        print("-- SAMPLE (primele 50 hrefs) --")
        for h in info['sample']:
            print("  ", h)
    b.close()
