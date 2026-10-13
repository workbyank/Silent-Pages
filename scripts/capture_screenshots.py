"""Run Silent Pages in headless Chromium, execute the library checks, and save screenshots.

This sandbox-friendly harness serves index.html locally and, when the network is
unavailable, replaces the CDN-hosted Firebase/Supabase modules with inert stubs
(scripts/fixtures) and the Project Gutenberg text with a short local excerpt.
The chat/messaging UI is never opened or captured, and the page's decorative
.secret-hint element is hidden in screenshots so the private entrance is not published.

Usage: python3 scripts/capture_screenshots.py [--fonts DIR]
  --fonts DIR  folder containing @fontsource files (optional; else system fonts are used)
"""
import argparse, functools, http.server, json, pathlib, threading
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
FX = ROOT / "scripts" / "fixtures"
SHOTS = ROOT / "screenshots"
ap = argparse.ArgumentParser(); ap.add_argument("--fonts"); a = ap.parse_args()
FONTS = pathlib.Path(a.fonts) if a.fonts else None
HIDE = ".secret-hint{display:none!important}"
results = []
def check(name, ok, detail=""):
    results.append((name, bool(ok), detail)); print(("PASS " if ok else "FAIL ") + name, detail)

class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(ROOT)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_port}/index.html"

def fulfil_cdn(route):
    u = route.request.url
    js = lambda p: route.fulfill(status=200, content_type="text/javascript", body=(FX / p).read_text())
    if "supabase-js" in u: return js("stub-supabase.js")
    if "firebasejs" in u: return js("stub-firebase.js")
    if "fonts.googleapis.com" in u:
        css = ""
        if FONTS:
            for w in (400, 500, 600):
                for st in ("normal", "italic"):
                    css += f"@font-face{{font-family:'Cormorant Garamond';font-style:{st};font-weight:{w};src:url(https://fonts.gstatic.com/cg-{w}-{st}.woff2)}}"
        return route.fulfill(status=200, content_type="text/css", body=css)
    if "fonts.gstatic.com" in u and FONTS:
        _, w, st = u.rsplit("/", 1)[1][:-6].split("-")
        f = FONTS / "cormorant-garamond" / "files" / f"cormorant-garamond-latin-{w}-{st}.woff2"
        return route.fulfill(status=200, content_type="font/woff2", body=f.read_bytes())
    if "gutenberg.org" in u:
        if "/1342" in u: return route.fulfill(status=200, content_type="text/plain; charset=utf-8", body=(FX / "reader-excerpt.txt").read_text())
        return route.fulfill(status=404, body="not found")
    route.abort()

with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    ctx.route(lambda u: not u.startswith("http://127.0.0.1"), fulfil_cdn)
    pg = ctx.new_page()
    errs = []; pg.on("console", lambda m: m.type == "error" and errs.append(m.text)); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_selector(".novel-item")
    pg.add_style_tag(content=HIDE)
    if FONTS:
        dv = FONTS / "noto-serif-devanagari" / "files"
        pg.add_style_tag(content="".join(f"@font-face{{font-family:'Noto Serif Devanagari';font-weight:{w};src:url(data:font/woff2;base64,{__import__('base64').b64encode((dv/f'noto-serif-devanagari-devanagari-{w}-normal.woff2').read_bytes()).decode()})}}" for w in (400, 600)))
        pg.wait_for_timeout(600)
    count = lambda: pg.locator(".novel-item").count()
    titles = lambda: pg.locator(".novel-title").all_inner_texts()

    check("library renders all 15 books", count() == 15, str(count()))
    check("result counter shows 15 books", pg.inner_text("#novel-result-count") == "15 books")
    check("no horizontal overflow (desktop)", pg.evaluate("document.documentElement.scrollWidth<=innerWidth"))
    check("chat UI stays hidden on load", pg.evaluate("getComputedStyle(document.getElementById('veil')).display==='none' || getComputedStyle(document.getElementById('veil')).visibility==='hidden' || getComputedStyle(document.getElementById('veil')).opacity==='0'"))
    pg.screenshot(path=str(SHOTS / "01-home.png"))
    pg.locator("#explore-novels").scroll_into_view_if_needed(); pg.evaluate("document.getElementById('explore-novels').scrollIntoView()"); pg.wait_for_timeout(300)
    pg.screenshot(path=str(SHOTS / "02-library.png"))

    pg.fill("#novel-search", "dickens"); check("search by author: 'dickens' -> 1", count() == 1 and titles() == ["Great Expectations"])
    pg.fill("#novel-search", "bronte"); check("search 'bronte' (no accent) -> 2", count() == 2, f"got {count()}")
    pg.fill("#novel-search", "Brontë"); check("search 'Brontë' -> 2", count() == 2)
    pg.fill("#novel-search", "godan"); check("search Latin part of Hindi title -> 1", count() == 1)
    pg.fill("#novel-search", "zzzz"); check("empty state message", "No novels found" in pg.inner_text("#novels-grid"))
    pg.click("#clear-novel-filters"); check("clear filters restores 15", count() == 15 and pg.input_value("#novel-search") == "")

    pg.click("#lang-filters [data-lang=hi]"); check("Hindi filter -> 4", count() == 4)
    pg.evaluate("document.getElementById('explore-novels').scrollIntoView()"); pg.wait_for_timeout(500); pg.screenshot(path=str(SHOTS / "08-hindi-literature.png"))
    pg.click("#lang-filters [data-lang=en]"); check("English filter -> 11", count() == 11)
    pg.click("#genre-filters [data-genre=Classics]"); n_cl = count(); check("English + Classics -> 3", n_cl == 3, str(n_cl))
    pg.select_option("#novel-sort", "author"); au = pg.locator(".novel-author").all_inner_texts()
    check("sort by author A-Z", au == sorted(au, key=lambda s: s.lower()) or au == sorted(au), str(au))
    pg.evaluate("document.getElementById('explore-novels').scrollIntoView()"); pg.wait_for_timeout(500)
    pg.screenshot(path=str(SHOTS / "03-search-filters.png"))
    pg.select_option("#novel-sort", "title"); t = titles(); check("sort by title A-Z", t == sorted(t), str(t))
    pg.click("#clear-novel-filters"); check("clear resets sort to curated", pg.input_value("#novel-sort") == "featured")

    fav = pg.locator("[data-fav=gb-1342]"); fav.click()
    check("favourite persists in localStorage", "gb-1342" in json.loads(pg.evaluate("localStorage.getItem('silentpages-favourites')")))
    pg.locator("[data-fav=gb-1342]").click(); check("favourite toggles off", "gb-1342" not in json.loads(pg.evaluate("localStorage.getItem('silentpages-favourites')")))

    href = pg.locator("a.novel-btn").first.get_attribute("href")
    check("Hindi books link out to Wikisource", href.startswith("https://hi.wikisource.org/"), href)

    pg.locator("[data-id=gb-1342]").click(); pg.wait_for_selector("#reader-body p, #reader-body div"); pg.wait_for_timeout(400)
    body = pg.inner_text("#reader-body")
    check("reader opens and trims Gutenberg markers", "universally acknowledged" in body and "START OF THE PROJECT" not in body)
    check("focus moves to reader close button", pg.evaluate("document.activeElement.id")=="reader-close")
    fs0 = pg.evaluate("parseFloat(getComputedStyle(document.getElementById('reader-body')).fontSize)")
    pg.click("#reader-larger"); fs1 = pg.evaluate("parseFloat(getComputedStyle(document.getElementById('reader-body')).fontSize)")
    pg.click("#reader-smaller"); pg.click("#reader-smaller"); fs2 = pg.evaluate("parseFloat(getComputedStyle(document.getElementById('reader-body')).fontSize)")
    check("reader A+ / A- change text size", fs1 > fs0 > fs2, f"{fs2}<{fs0}<{fs1}")
    pg.click("#reader-larger")
    pg.screenshot(path=str(SHOTS / "04-reader.png"))
    pg.click("#reader-theme"); check("dark reading theme toggles", pg.evaluate("document.getElementById('reader-modal').classList.contains('reading-dark')"))
    pg.screenshot(path=str(SHOTS / "05-reader-dark.png"))
    pg.keyboard.press("Escape"); check("Escape closes reader", not pg.evaluate("document.getElementById('reader-modal').classList.contains('open')"))
    check("focus returns to the Read button", pg.evaluate("document.activeElement.dataset.id")=="gb-1342")
    pg.locator("[data-id=gb-84]").click(); pg.wait_for_selector("#reader-body a.novel-btn"); check("reader failure falls back to external link", True)
    pg.click("#reader-close")

    # the app's own "[READER] Failed to fetch" log is expected: the 404 fallback path is exercised on purpose above
    real_errs = [e for e in errs if "Failed to load resource" not in e and "[READER] Failed to fetch" not in e]
    check("no JS console/page errors", not real_errs, str(real_errs[:3]))

    m = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    m.route(lambda u: not u.startswith("http://127.0.0.1"), fulfil_cdn)
    mp = m.new_page(); merrs = []; mp.on("pageerror", lambda e: merrs.append(str(e)))
    mp.goto(URL); mp.wait_for_selector(".novel-item")
    mp.add_style_tag(content=HIDE)
    if FONTS: mp.add_style_tag(content=pg.evaluate("[...document.styleSheets].map(s=>{try{return [...s.cssRules].filter(r=>r.cssText.includes('Noto Serif Devanagari')&&r.cssText.startsWith('@font-face')).map(r=>r.cssText).join('')}catch(e){return ''}}).join('')")); mp.wait_for_timeout(600)
    check("mobile: no horizontal overflow", mp.evaluate("document.documentElement.scrollWidth<=innerWidth"))
    cols = mp.evaluate("getComputedStyle(document.getElementById('novels-grid')).gridTemplateColumns.split(' ').length")
    check("mobile: two-column grid", cols == 2, str(cols))
    mp.screenshot(path=str(SHOTS / "06-mobile-home.png"))
    mp.evaluate("document.getElementById('explore-novels').scrollIntoView()"); mp.wait_for_timeout(300)
    mp.screenshot(path=str(SHOTS / "07-mobile-library.png"))
    check("mobile: no page errors", not merrs, str(merrs[:2]))
    br.close()
srv.shutdown()
bad = [r for r in results if not r[1]]
print(f"\n{len(results)-len(bad)}/{len(results)} checks passed")
