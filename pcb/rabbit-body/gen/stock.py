"""Check every LCSC part of design.py against the JLCPCB assembly catalogue (stock, basic/extended, price).

Run with any Python 3: python3 gen/stock.py [boards]. Writes fab/stock.json and fab/rabbit-body-revB-stock.csv.
JLC's own stock is what assembly uses; the LCSC shop page can differ (rev A: PCA9685 LCSC 0, JLC 393).
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


def main():
    boards = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    qty = defaultdict(int)
    mpn = {}
    for p in design.PARTS:
        if p["lcsc"] and p["bom"] in ("smt", "tht"):
            qty[p["lcsc"]] += 1
            mpn[p["lcsc"]] = (p["value"], p["mpn"], p["bom"])
    result = {}
    for code in sorted(qty):
        for attempt in range(3):
            try:
                result[code] = query(code)
                break
            except Exception as e:   # the API rate-limits bursts
                print("retry", code, e)
                time.sleep(3)
        time.sleep(0.3)
    FAB.mkdir(exist_ok=True)
    day = datetime.date.today().isoformat()
    (FAB / "stock.json").write_text(json.dumps({"date": day, "parts": result}, indent=1))
    short = []
    with open(FAB / "rabbit-body-revB-stock.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["LCSC", "Value", "MPN (design)", "JLC model", "Package", "Per board", f"Need for {boards}",
                    f"JLC stock {day}", "Library", "Unit price USD"])
        for code in sorted(qty, key=lambda c: (mpn[c][2], mpn[c][0])):
            r = result.get(code) or {}
            need = qty[code] * boards
            stock = r.get("stock")
            w.writerow([code, mpn[code][0], mpn[code][1], r.get("model"), r.get("package"), qty[code], need, stock,
                        r.get("type"), r.get("price")])
            flag = "" if stock is not None and stock >= need * 3 else ("  <-- LOW" if stock else "  <-- NONE")
            if flag:
                short.append(code)
            print(f"{code:10} {mpn[code][0]:14} x{qty[code]:<3} {str(r.get('model'))[:28]:28} {str(r.get('package'))[:16]:16} "
                  f"stock {stock} {r.get('type')}{flag}")
    print(f"{len(qty)} lines, {sum(qty.values())} placements per board, low/none: {short or 'none'}")


if __name__ == "__main__":
    main()
