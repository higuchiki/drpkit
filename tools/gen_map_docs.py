"""Generate the documentation tables from drpkit/fairlight_map.yaml (the single source of truth).

    python tools/gen_map_docs.py          # write docs_snippets/*.md
    python tools/gen_map_docs.py --check  # exit 1 if the committed files are out of date

The pages under docs/ include these files with pymdownx.snippets (`--8<-- "map_items.en.md"`).
"""
import argparse
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, "drpkit", "fairlight_map.yaml")
OUT = os.path.join(ROOT, "docs_snippets")

MARK = {"direct": "", "two_point": "²", "calib": "※", "law": "※", "assumed": "?", "raw": "✗", "uncal": "✗"}
EQ_TYPE_EN = {"ローシェルフ": "low shelf", "ベル": "bell", "ハイシェルフ": "high shelf", "ノッチ": "notch",
              "LPF": "low-pass", "HPF": "high-pass"}
EQ_TYPE_JA = {"LPF": "ローパス", "HPF": "ハイパス"}

T = {
    "en": {
        "item": "Item", "id": "Id", "kind": "Kind", "conv": "Stored value → UI", "conf": "Mark",
        "scale1": "as-is", "scale": "× %s", "flag": "1 = on", "flag_inv": "1 = off (reported inverted as `%s`)",
        "law": "Dynamics law `%s` (see [Conversions](conversions.md#built-in-dynamics))",
        "raw": "raw only (meaning unknown)", "affine": "%s + %s × raw, %s … %s",
        "floor": ", minimum %s ms",
        "M": "M (knob position)", "legacy": "legacy r (knob %)", "param": "Parameter", "label": "Label",
        "plugin": "Plugin", "code": "Stored code", "color": "Color", "bit": "Stored bit", "value": "Value",
        "meaning": "Meaning", "pid": "Param", "name": "Name",
        "linear": "%s + (%s − %s) × p", "log": "%s × (%s / %s)^p", "flagp": "≥ 0.5 = on", "enump": "lookup",
        "unit": "unit",
    },
    "ja": {
        "item": "項目", "id": "番号", "kind": "種類", "conv": "保存値 → 画面値", "conf": "確度",
        "scale1": "そのまま", "scale": "× %s", "flag": "1 = 有効", "flag_inv": "1 = 無効（`%s` として反転して出力）",
        "law": "Dynamics 換算表 `%s`（[換算](conversions.md#built-in-dynamics)）",
        "raw": "生値のみ（意味未確定）", "affine": "%s + %s × 保存値、%s〜%s",
        "floor": "、最小 %s ms",
        "M": "M（つまみ位置）", "legacy": "旧方式 r（つまみ%）", "param": "パラメーター", "label": "出力名",
        "plugin": "プラグイン", "code": "保存コード", "color": "色", "bit": "保存ビット", "value": "値",
        "meaning": "意味", "pid": "番号", "name": "名前",
        "linear": "%s + (%s − %s) × p", "log": "%s × (%s / %s)^p", "flagp": "0.5 以上 = 有効", "enump": "対応表",
        "unit": "単位",
    },
}


def g(v):
    return ("%g" % v) if isinstance(v, float) else str(v)


def scale_text(s, unit, t):
    if s == 1:
        txt = t["scale1"]
    elif s == 0.1:
        txt = "÷ 10"
    else:
        txt = t["scale"] % g(s)
    return txt + (" " + unit if unit else "")


def enum_text(m, lang):
    parts = []
    for k, v in m.items():
        v = str(v)
        if lang == "en":
            v = EQ_TYPE_EN.get(v, v)
        else:
            v = EQ_TYPE_JA.get(v, v)
        parts.append("%s = %s" % (g(k), v))
    return ", ".join(parts)


def item_rows(cfg, lang):
    t = T[lang]
    items = sorted(cfg["channel_items"].items(), key=lambda kv: kv[1]["id"])
    out = ["| %s | %s | %s | %s | %s |" % (t["id"], t["item"], t["kind"], t["conv"], t["conf"]), "|---|---|---|---|---|"]
    for name, s in items:
        kind = s["kind"]
        unit = s.get("unit", "")
        if kind == "scale":
            conv = scale_text(s["scale"], unit, t)
        elif kind == "flag":
            conv = t["flag"]
        elif kind == "flag_inv":
            conv = t["flag_inv"] % s.get("label", name)
        elif kind == "enum":
            conv = enum_text(s["map"], lang)
        elif kind == "affine":
            conv = t["affine"] % (g(s["a"]), g(s["b"]), g(s["min"]), g(s["max"]))
        elif kind == "law":
            conv = t["law"] % s["law"] + (" " + unit.strip() if unit.strip() else "")
            if "floor" in s:
                conv += t["floor"] % g(s["floor"])
        else:
            conv = t["raw"]
        conf = "law" if kind == "law" else s.get("conf", "raw")
        out.append("| `0x%03X` | `%s` | %s | %s | %s %s |" % (s["id"], name, kind, conv, MARK.get(conf, "✗"), "`%s`" % conf))
    return "\n".join(out) + "\n"


def law_tables(cfg, lang, which):
    t = T[lang]
    laws = cfg["dyn_laws"]
    names = list(laws)
    keys = sorted({k for n in names for k in laws[n][which]})
    head = t["M"] if which == "law" else t["legacy"]
    out = ["| %s | %s |" % (head, " | ".join("`%s`" % n for n in names)), "|---" * (len(names) + 1) + "|"]
    for k in keys:
        out.append("| %s | %s |" % (k, " | ".join(g(laws[n][which][k]) if k in laws[n][which] else "" for n in names)))
    foot = []
    for n in names:
        L = laws[n]
        foot.append("`%s`: fine = %s%s" % (n, g(L.get("fine", 0)), (", max = %s" % g(L["max"])) if "max" in L else ""))
    return "\n".join(out) + "\n\n" + " · ".join(foot) + "\n"


def plugin_rows(cfg, lang):
    t = T[lang]
    out = ["| %s | %s | %s | %s | %s | %s |" % (t["plugin"], t["param"], t["label"], t["kind"], t["conv"], t["conf"]),
           "|---|---|---|---|---|---|"]
    for pl, params in cfg["plugins"].items():
        for pname, s in params.items():
            kind = s["kind"]
            unit = s.get("unit", "")
            if kind == "linear":
                conv = t["linear"] % (g(s["min"]), g(s["max"]), g(s["min"])) + (" " + unit if unit else "")
            elif kind == "log":
                conv = t["log"] % (g(s["min"]), g(s["max"]), g(s["min"])) + (" " + unit if unit else "")
            elif kind == "flag":
                conv = t["flagp"]
            elif kind == "enum":
                conv = ", ".join("%s → %s" % (g(k), v) for k, v in s["map"].items())
            else:
                conv = kind
            conf = s.get("conf", "raw")
            out.append("| %s | `%s` | `%s` | %s | %s | %s `%s` |" % (pl, pname, s["label"], kind, conv, MARK.get(conf, "✗"), conf))
    return "\n".join(out) + "\n"


def color_rows(cfg, lang):
    t = T[lang]
    cc = cfg["clip_colors"]
    mc = cfg["marker_colors"]
    a = ["| %s | %s |" % (t["code"], t["color"]), "|---|---|"] + ["| %d (`0x%02X`) | %s |" % (k, k, v) for k, v in sorted(cc.items())]
    b = ["| %s | %s |" % (t["bit"], t["color"]), "|---|---|"] + ["| %d (`0x%X`) | %s |" % (k, k, v) for k, v in sorted(mc.items())]
    return "\n".join(a) + "\n", "\n".join(b) + "\n"


def misc_rows(cfg, lang):
    t = T[lang]
    ta = ["| `AlignmentType` | %s |" % t["meaning"], "|---|---|"] + ["| %s | %s |" % (k, v) for k, v in cfg["transition_alignment"].items()]
    ce = ["| Effect type | %s | %s |" % (t["pid"], t["name"]), "|---|---|---|"]
    for et, s in cfg["clip_effects"].items():
        for pid, nm in s["params"].items():
            ce.append("| %s (%s) | %s | `%s` |" % (et, s["name"], pid, nm))
    return "\n".join(ta) + "\n", "\n".join(ce) + "\n"


def build():
    with open(MAP, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    files = {}
    for lang in ("en", "ja"):
        files["map_items.%s.md" % lang] = item_rows(cfg, lang)
        files["map_laws.%s.md" % lang] = law_tables(cfg, lang, "law")
        files["map_legacy.%s.md" % lang] = law_tables(cfg, lang, "legacy")
        files["map_plugins.%s.md" % lang] = plugin_rows(cfg, lang)
        files["map_clip_colors.%s.md" % lang], files["map_marker_colors.%s.md" % lang] = color_rows(cfg, lang)
        files["map_alignment.%s.md" % lang], files["map_clip_effects.%s.md" % lang] = misc_rows(cfg, lang)
    note = "<!-- generated by tools/gen_map_docs.py from drpkit/fairlight_map.yaml; do not edit -->\n"
    return {k: note + v for k, v in files.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if docs_snippets/ is out of date")
    a = ap.parse_args(argv)
    files = build()
    stale = []
    for name, text in files.items():
        p = os.path.join(OUT, name)
        old = open(p, encoding="utf-8").read() if os.path.exists(p) else None
        if old != text:
            stale.append(name)
            if not a.check:
                os.makedirs(OUT, exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text)
    if a.check and stale:
        sys.stderr.write("out of date: %s\nrun: python tools/gen_map_docs.py\n" % ", ".join(stale))
        return 1
    print("%d files %s" % (len(files), "up to date" if not stale else ("checked" if a.check else "written: " + ", ".join(stale))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
