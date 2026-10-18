"""Built-in Dynamics conversion (dyn_laws) vs. values read on the Resolve UI.

Data: a write sweep (23 projects x 10 knobs, tests/data/dyn_law_sweep_*) plus individually
written points (EXTRA). Each entry = (knob, stored value written into the .drp, value shown in the UI).
"""
import json
import os
import sys
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import yaml  # noqa: E402
from drpkit import reader as fr  # noqa: E402

CFG = yaml.safe_load(open(os.path.join(ROOT, "drpkit", "fairlight_map.yaml"), encoding="utf-8"))
ITEM = {"ratio": "comp_ratio", "cAtt": "comp_attack", "xAtt": "exp_attack", "lAtt": "limiter_attack",
        "cHold": "comp_hold", "xHold": "exp_hold", "lHold": "limiter_hold",
        "cRel": "comp_release", "xRel": "exp_release", "lRel": "limiter_release", "xRat": "exp_ratio"}

EXTRA = [("cAtt", 40496, "4.0"), ("lAtt", 40496, "1.7"), ("lAtt", 32196, "0.81"), ("cAtt", 67496, "20"),
         ("cRel", 32196, "134"), ("cRel", 48096, "300"), ("xRel", 67496, "832"), ("ratio", 51996, "3.0"),
         ("ratio", 51950, "3.0"), ("ratio", 52000, "3.0"), ("ratio", 30000, "1.8"), ("ratio", 70000, "5.0"),
         ("cAtt", 40400, "8.0"), ("cAtt", 40420, "28"), ("xAtt", 40450, "58"), ("cAtt", 40480, "88"),
         ("xAtt", 40490, "98"), ("cHold", 40400, "206"), ("cRel", 40420, "226"), ("xHold", 40450, "256"),
         ("xRel", 40480, "286"), ("lHold", 40490, "296"), ("lRel", 40496, "203"), ("xRel", 40499, "206"),
         ("lHold", 40499, "206"), ("lAtt", 40450, "56"), ("lAtt", 40400, "5.7"), ("xHold", 40500, "207"),
         ("xRel", 41000, "212"), ("cAtt", 20000, "5.1"), ("cHold", 30000, "125"), ("cRel", 40000, "201"),
         ("xAtt", 50000, "11"), ("xHold", 60000, "560"), ("xRel", 70000, "949"), ("lAtt", 80000, "19"),
         ("lHold", 90000, "2374"), ("lRel", 45000, "260"), ("cHold", 10, "32"), ("xHold", 50, "408"),
         ("lHold", 60, "700"), ("lRel", 80, "1827"), ("xRel", 99, "3859"), ("cHold", 5000, "4.0"),
         ("cAtt", 10000, "4.7"), ("xAtt", 10000, "4.6"), ("lAtt", 30000, "4.7"), ("lHold", 80000, "1523"),
         ("lRel", 50000, "335"), ("lRel", 100000, "3457"), ("cRel", 1000, "画面空欄(raw=1000)"),
         ("xHold", 101, "画面空欄(raw=101)"), ("ratio", 50, "3.1"), ("ratio", 10, "1.4"), ("cAtt", 50, "9.4"),
         ("xAtt", 33, "3.2"), ("lAtt", 40, "2.3"), ("cHold", 50, "408"), ("ratio", 0, "1.2"), ("cAtt", 0, "0.70"),
         ("cRel", 0, "50"), ("xAtt", 25, "1.9"), ("xHold", 15, "78"), ("cRel", 20, "93"), ("xRel", 28, "134"),
         ("lAtt", 10, "0.71"), ("lRel", 10, "66"),
         # blind prediction check (points not used to build the tables; M=165 added afterwards)
         ("ratio", 92896, "11"), ("cAtt", 85096, "48"), ("xAtt", 56600, "15"), ("cRel", 68396, "871"),
         ("lAtt", 29703, "7.7"), ("lHold", 16499, "74"), ("lRel", 85909, "1991"), ("ratio", 38, "2.4"),
         ("cAtt", 56499, "14"), ("xAtt", 15138, "43"), ("xRel", 64797, "726"), ("lRel", 97600, "3172"),
         # expander ratio (UI 1:x), typed in the UI and exported (2026-10-18)
         ("xRat", 0, "1.1"), ("xRat", 15196, "1.3"), ("xRat", 26296, "1.5"), ("xRat", 55, "2.1"),
         ("xRat", 75, "2.5"), ("xRat", 100, "3.0"),
         # expander ratio blind check (written values, read on the UI): X1 / X2
         ("xRat", 40000, "1.7"), ("xRat", 60000, "2.1"), ("xRat", 80000, "2.5"), ("xRat", 100000, "2.9"),
         ("xRat", 10, "1.3"), ("xRat", 25, "1.6"), ("xRat", 40, "1.8"), ("xRat", 90, "2.8")]


def pred(knob, raw):
    t, _ = fr.decode_item(CFG["channel_items"][ITEM[knob]], raw, {}, CFG["dyn_laws"])
    return t.replace(" ms", "").replace(":1", "").replace("1:", "")


def rows():
    plan = json.load(open(os.path.join(HERE, "data", "dyn_law_sweep_plan.json"), encoding="utf-8"))
    out = []
    for line in open(os.path.join(HERE, "data", "dyn_law_sweep_readings.txt"), encoding="utf-8"):
        t = line.split()
        i = int(t[0][1:])
        for k, (nm, v) in enumerate(zip(plan["names"], t[1:])):
            raw = plan["plan"][i][k] * 100
            out.append(("sweep " + t[0], nm, raw, "画面空欄(raw=%d)" % raw if v == "-" else v))
    out += [("single", nm, raw, v) for nm, raw, v in EXTRA]
    return out


class DynLawTest(unittest.TestCase):
    def test_all_points(self):
        rs = rows()
        self.assertEqual(len(rs), 230 + len(EXTRA))
        ng = [(s, nm, raw, v, pred(nm, raw)) for s, nm, raw, v in rs if pred(nm, raw) != v]
        print("\n[dyn_law] match %d / %d" % (len(rs) - len(ng), len(rs)))
        self.assertEqual(ng, [])


if __name__ == "__main__":
    unittest.main()
