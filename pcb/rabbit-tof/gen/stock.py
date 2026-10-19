"""Check every LCSC part of design.py against the JLCPCB assembly catalogue (stock, basic/extended, price).

Run with any Python 3: python3 gen/stock.py [boards]. Writes fab/stock.json and fab/rabbit-tof-revA-stock.csv.
JLC's own stock is what assembly uses; the LCSC shop page can differ.
"""
import csv
import datetime
import json
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
FAB = HERE.parent / "fab"
ALTERNATIVES = {"C189892": ["C3011957", "C2829264", "C52037399"]}   # GH-6 vertical: HCTL, BOOMELE, XUNPU look-alikes


def query(code):
    req = urllib.request.Request(API, data=json.dumps({"keyword": code, "currentPage": 1, "pageSize": 5}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    for c in json.load(urllib.request.urlopen(req, timeout=30))["data"]["componentPageInfo"]["list"] or []:
        if c.get("componentCode") == code:
            prices = c.get("componentPrices") or [{}]
            return {"model": c.get("componentModelEn"), "package": c.get("componentSpecificationEn"),
                    "stock": c.get("stockCount"), "type": c.get("componentLibraryType"),
                    "price": prices[0].get("productPrice"), "describe": (c.get("describe") or "")[:120]}
    return None


def fetch(code):
    for _ in range(3):
        try:
            return query(code)
        except Exception as e:   # the API rate-limits bursts
            print("retry", code, e)
            time.sleep(3)
    return None


def main():
    boards = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    qty = defaultdict(int)
    mpn = {}
    for p in design.PARTS:
        if p["lcsc"] and p["bom"] == "smt":
            qty[p["lcsc"]] += 1
            mpn[p["lcsc"]] = (p["value"], p["mpn"])
    result = {}
    for code in sorted(qty) + [a for alts in ALTERNATIVES.values() for a in alts]:
        result[code] = fetch(code)
        time.sleep(0.3)
    FAB.mkdir(exist_ok=True)
    day = datetime.date.today().isoformat()
    (FAB / "stock.json").write_text(json.dumps({"date": day, "boards": boards, "parts": result}, indent=1))
    short = []
    with open(FAB / f"rabbit-tof-rev{design.REV}-stock.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["LCSC", "Value", "MPN (design)", "JLC model", "Package", "Per board", f"Need for {boards}",
                    f"JLC stock {day}", "Library", "Unit price USD"])
        for code in sorted(qty, key=lambda c: mpn[c][0]):
            r = result.get(code) or {}
            need = qty[code] * boards
            stock = r.get("stock")
            w.writerow([code, mpn[code][0], mpn[code][1], r.get("model"), r.get("package"), qty[code], need, stock,
                        r.get("type"), r.get("price")])
            flag = "" if stock is not None and stock >= need * 3 else ("  <-- LOW" if stock else "  <-- NONE")
            if flag:
                short.append(code)
            print(f"{code:10} {mpn[code][0]:12} x{qty[code]:<2} {str(r.get('model'))[:26]:26} stock {stock} "
                  f"{r.get('type')} ${r.get('price')}{flag}")
            for alt in ALTERNATIVES.get(code, []):
                a = result.get(alt) or {}
                w.writerow([alt, f"alt. for {code}", "", a.get("model"), a.get("package"), "", need, a.get("stock"),
                            a.get("type"), a.get("price")])
                print(f"   alt {alt:10} {str(a.get('model'))[:26]:26} stock {a.get('stock')} ${a.get('price')}")
    print(f"{len(qty)} lines, {sum(qty.values())} placements per board, low/none: {short or 'none'}")


if __name__ == "__main__":
    main()
