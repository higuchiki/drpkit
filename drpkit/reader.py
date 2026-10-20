"""DaVinci Resolve の .drp / Project.db から Fairlight のトラック・Bus設定を読み取る（読み取り専用）。

使い方:
  drpkit read <path.drp|Project.db> [--timeline 名前] [--json] [--expect expect.yaml]
  drpkit read <path.drp|Project.db> --edits [--json]   # カット位置・クリップ色・トランジション

原本は変更しない（.drp は zip として読むだけ、Project.db は SQLite の immutable 読み取り）。
項目番号・換算は drpkit/fairlight_map.yaml（単一ソース）。形式の解説は FORMAT.md。
"""
import sys

import argparse
import binascii
import json
import math
import os
import re
import sqlite3
import struct
import zipfile
import zlib

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(HERE, "fairlight_map.yaml")
NAMES_ITEM = 0xBC


# ---------------- QDataStream（FieldsBlob）----------------
class _R:
    def __init__(self, b):
        self.b, self.o = b, 0

    def u32(self):
        v = struct.unpack_from(">I", self.b, self.o)[0]
        self.o += 4
        return v

    def take(self, n):
        v = self.b[self.o:self.o + n]
        self.o += n
        return v


def _qstr(r):
    n = r.u32()
    return None if n == 0xFFFFFFFF else r.take(n).decode("utf-16-be")


def _qvar(r):
    t = r.u32()
    r.take(1)
    if t == 1:
        return bool(r.take(1)[0])
    if t == 2:
        return struct.unpack(">i", r.take(4))[0]
    if t == 3:
        return r.u32()
    if t == 4:
        return struct.unpack(">q", r.take(8))[0]
    if t == 5:
        return struct.unpack(">Q", r.take(8))[0]
    if t == 6:
        return struct.unpack(">d", r.take(8))[0]
    if t == 10:
        return _qstr(r)
    if t == 12:
        n = r.u32()
        return None if n == 0xFFFFFFFF else r.take(n)
    if t == 8:
        n = r.u32()
        return {_qstr(r): _qvar(r) for _ in range(n)}
    if t == 9:
        n = r.u32()
        return [_qvar(r) for _ in range(n)]
    if t == 11:
        n = r.u32()
        return [_qstr(r) for _ in range(n)]
    raise ValueError("未対応のQVariant型 %d" % t)


def parse_fieldsblob(b):
    r = _R(b)
    r.u32()  # version
    n = r.u32()
    return {_qstr(r): _qvar(r) for _ in range(n)}


def _decompress(ba):
    # qCompress：先頭4バイト（展開後サイズ）＋zlib
    return zlib.decompress(ba[4:])


# ---------------- 入力（drp / Project.db）----------------
def timeline_name_at(text, pos):
    """MpFolder.xml の位置 pos にある FieldsBlob が属するタイムライン名（直前の Sm2Timeline の Name）"""
    ctx = text[:pos]
    k = ctx.rfind("<Sm2Timeline")
    nm = re.search(r"<Name>([^<]*)</Name>", ctx[k:]) if k >= 0 else None
    return nm.group(1) if nm else "(名前不明)"


def models_from_drp(path):
    out = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith("MpFolder.xml"):
                continue
            t = z.read(name).decode("utf-8", "replace")
            for m in re.finditer(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", t):
                hx = m.group(1)
                if "0046004c00530074" not in hx.lower():  # "FLSt" UTF-16BE
                    continue
                d = parse_fieldsblob(binascii.unhexlify(hx))
                if "FLStudioModelBA" not in d:
                    continue
                out.append({"timeline": timeline_name_at(t, m.start()),
                            "seqref": d.get("SeqRef"),
                            "modtime": d.get("ModTimeInSecs"),
                            "model": _decompress(d["FLStudioModelBA"])})
    return out


def models_from_db(path):
    uri = "file:%s?mode=ro&immutable=1" % path
    con = sqlite3.connect(uri, uri=True)
    out = []
    q = ("select t.Name, s.FieldsBlob from Sm2Sequence s "
         "join Sm2Timeline t on t.Sequence = s.Sm2Sequence_id")
    for name, fb in con.execute(q):
        if not fb:
            continue
        d = parse_fieldsblob(bytes(fb))
        if "FLStudioModelBA" not in d:
            continue
        out.append({"timeline": name, "seqref": d.get("SeqRef"),
                    "modtime": d.get("ModTimeInSecs"),
                    "model": _decompress(d["FLStudioModelBA"])})
    con.close()
    return out


def load_models(path):
    if path.lower().endswith(".drp"):
        return models_from_drp(path)
    return models_from_db(path)


# ---------------- FLStudioModel：設定表 ----------------
def _parse_records(b, p, stop=None):
    recs = []
    while p + 12 <= len(b):
        t, item, n = struct.unpack_from("<III", b, p)
        if t != 1 or item > 0xFFFF or n == 0 or n > 4096 or p + 12 + 4 * n > len(b):
            break
        if item == NAMES_ITEM:
            vals, q = [], p + 12
            try:
                for _ in range(n):
                    ln = struct.unpack_from("<I", b, q)[0]
                    if ln > 1000:
                        raise ValueError
                    vals.append(b[q + 4:q + 4 + ln].decode("utf-8"))
                    q += 4 + ln
            except Exception:
                break
            recs.append((p, item, n, vals))
            p = q
            continue
        recs.append((p, item, n, list(struct.unpack_from("<%di" % n, b, p + 12))))
        p += 12 + 4 * n
        if stop is not None and p >= stop:
            break
    return recs, p


def channel_tables(b):
    """項目0xBC（名前の配列）を含む設定表をすべて返す。列＝チャンネル"""
    tables = []
    pat = struct.pack("<II", 1, NAMES_ITEM)
    for m in re.finditer(re.escape(pat), b):
        o = m.start()
        n = struct.unpack_from("<I", b, o + 8)[0]
        if n == 0 or n > 4096:
            continue
        start = None
        for c in range(max(0, o - 0x8000), o):
            if b[c:c + 4] != b"\x01\x00\x00\x00":
                continue
            it, nn = struct.unpack_from("<II", b, c + 4)
            if nn != n or it > NAMES_ITEM:
                continue
            r, _ = _parse_records(b, c, stop=o + 1)
            if any(x[0] == o for x in r):
                start = c
                break
        if start is None:
            continue
        recs, _ = _parse_records(b, start)
        names = next(x[3] for x in recs if x[1] == NAMES_ITEM)
        items = {}
        for _, item, _, vals in recs:
            items.setdefault(item, vals)  # 同じ項目番号が2回ある場合は最初を採用
        if names and names[0].startswith("Bus"):
            for item, vals in _bus_part_a(b, start, n).items():
                items.setdefault(item, vals)
        tables.append({"names": names, "items": items, "record_start": start})
    return tables


def _bus_part_a(b, before, n):
    """Bus 表の前半（フェーダー 0x001・ミュート 0x002 など）。名前表とは離れた位置にあり、
    見出し [u32 0][u32 7]（7＝Bus の種別番号。プラグインの所属と同じ）の直後に列数 n のレコード列が続く。
    Bus 表より前で最後に現れる、10レコード以上・全列数 n のものを採用（2026-10-18 書き出しの音量実測で確定）"""
    recs = _bus_part_a_records(b, before, n)
    out = {}
    for _, item, _, vals in recs:
        out.setdefault(item, vals)
    return out


def _bus_part_a_records(b, before, n):
    """Keep offsets as well as values so reader and writer use the same Bus region."""
    pat = struct.pack("<IIIII", 0, 7, 1, 0x001, n)
    best = None
    for m in re.finditer(re.escape(pat), b[:before]):
        recs, _ = _parse_records(b, m.start() + 8)
        if len(recs) >= 10 and all(x[2] == n for x in recs):
            best = recs
    return best or []


def track_aliases(tab):
    """Stable @A1, @A2 selectors from strip IDs, including unnamed stereo columns.

    Only audio mixer tables have both fader and EQ records. A nonnegative strip ID
    starts a track; -1 is a continuation column. Never infer groups from blank names.
    """
    if not all(k in tab['items'] for k in (0x001, 0x0df, 0x458)):
        return {}
    if tab['names'] and tab['names'][0].startswith(('Bus', 'VCA', 'Mapping', 'Folder')):
        return {}
    ids = tab['items'][0x458]
    starts = [value for value in ids if value >= 0]
    if (len(ids) != len(tab['names']) or not ids or ids[0] < 0
            or any(value < -1 for value in ids) or len(set(starts)) != len(starts)):
        return {}  # Ambiguous layouts must not select a different track silently.
    aliases, current = {}, None
    for col, strip_id in enumerate(ids):
        if strip_id >= 0:
            current = '@A%d' % (strip_id + 1)
        if current is not None:
            aliases.setdefault(current, []).append(col)
    return aliases


# ---------------- FLStudioModel：プラグイン ----------------
# つまみ名：「Plugin::PARAM」形式と、Dialogue Leveler の「UI_BAS_PRESET」形式（:: なし）の両方
PARAM_RE = rb"([A-Za-z][A-Za-z0-9_]*(?:::[A-Z_]+)?)\x00"
def plugins(b):
    """bmd:<名前>:<ID> を所属（種別・列・スロット）付きで返す。パラメータは次の bmd: までの範囲"""
    hits = [m for m in re.finditer(rb"bmd:([A-Za-z \-]+):(\d+)", b)]
    out = []
    for i, m in enumerate(hits):
        s = m.start()
        pre = b[s - 12:s - 8]
        kind, col, _, slot = pre[0], pre[1], pre[2], pre[3]
        tail = struct.unpack_from("<I", b, s - 4)[0]
        if tail != 2 and not (kind == 0 and slot >= 6):
            continue  # AutoMix の雛形など、ミキサー所属でない記録
        end = hits[i + 1].start() if i + 1 < len(hits) else min(len(b), s + 0x400)
        params = {}
        for pm in re.finditer(PARAM_RE, b[s:end]):
            q = s + pm.start()
            nm = pm.group(1)
            if any(c != 0 for c in b[q + len(nm):q + 64]):
                continue
            params[nm.decode()] = struct.unpack_from("<f", b, q + 64)[0]
        out.append({"name": m.group(1).decode(), "kind": "bus" if kind == 7 else "track",
                    "column": col, "slot": slot, "params": params, "state": plugin_state(b, s)})
    return out


# 記録の並び（"bmd:" の位置 s から）：名前欄 256 バイト（"bmd:名前:ID" を NUL 埋め）→ int32×4（プラグイン画面の
# 位置・大きさ。一度も開いていなければ全て −1）→ u32 状態フラグ。2026-10-18 F00〜F03（トラック内蔵 Voice Isolation の
# 有効/無効を画面で切替）で、状態フラグの 0x10 だけが変わる（0x00＝有効／0x10＝無効）ことを確認
PLUGIN_NAME_FIELD = 256
PLUGIN_STATE_OFFSET = PLUGIN_NAME_FIELD + 16


def plugin_state(b, s):
    """プラグイン記録の状態フラグ（u32）。名前欄が NUL 埋めの 256 バイトでなければ None（形式が違う記録）"""
    end = b.find(b"\x00", s, s + PLUGIN_NAME_FIELD)
    if end < 0 or s + PLUGIN_STATE_OFFSET + 4 > len(b) or any(b[end:s + PLUGIN_NAME_FIELD]):
        return None
    return struct.unpack_from("<I", b, s + PLUGIN_STATE_OFFSET)[0]


# ---------------- 換算 ----------------
def _fmt(v, unit):
    if isinstance(v, float):
        v = round(v, 2)
    return ("%s %s" % (v, unit)).strip() if unit else str(v)


def _interp(table, x):
    """表 {x: y} を補間（両端の y が正なら対数、そうでなければ線形）。範囲外は端の外挿をせず端の値"""
    ks = sorted(table)
    if x <= ks[0]:
        return float(table[ks[0]])
    if x >= ks[-1]:
        return float(table[ks[-1]])
    for a, b in zip(ks, ks[1:]):
        if a <= x <= b:
            ya, yb = float(table[a]), float(table[b])
            t = (x - a) / float(b - a)
            if ya > 0 and yb > 0:
                return math.exp(math.log(ya) + (math.log(yb) - math.log(ya)) * t)
            return ya + (yb - ya) * t


def dyn_law_value(law, raw):
    """内蔵Dynamicsの保存値→画面値（数値）。表示なしの範囲は None。方式は fairlight_map.yaml dyn_laws の注記"""
    if raw <= 100:
        return _interp(law["legacy"], raw), "legacy"
    if raw < 5000:
        return None, "空欄"
    m = (raw + 5) // 100
    d = raw - 100 * m
    v = _interp(law["law"], m) + d * law.get("fine", 0)
    return v, "M=%d,d=%d" % (m, d)


def fmt_dyn(v, unit):
    if v < 1:
        s = "%.2f" % v
    elif v < 9.95:
        s = "%.1f" % v
    else:
        s = "%d" % int(round(v))
    if unit == ":1":
        return s + unit
    if unit == "1:":
        return unit + s
    return ("%s %s" % (s, unit)).strip()


def decode_item(spec, raw, calib, laws=None):
    k = spec["kind"]
    if raw is None:
        return None, "なし"
    if k == "flag":
        return ("ON" if raw else "OFF"), spec.get("conf", "direct")
    if k == "flag_inv":
        return ("ON" if not raw else "OFF"), spec.get("conf", "direct")
    if k == "scale":
        v = raw * spec["scale"]
        v = int(v) if float(v).is_integer() else v
        return _fmt(v, spec.get("unit", "")), spec.get("conf", "direct")
    if k == "enum":
        m = spec["map"]
        return (m[raw], spec["conf"]) if raw in m else ("未較正(raw=%s)" % raw, "uncal")
    if k == "affine":
        v = spec["a"] + spec["b"] * raw
        if spec.get("min") is not None:
            v = max(v, spec["min"])
        if spec.get("max") is not None:
            v = min(v, spec["max"])
        return _fmt(round(v, spec.get("digits", 2)), spec.get("unit", "")), spec.get("conf", "calib")
    if k == "law":
        law = laws[spec["law"]]
        v, how = dyn_law_value(law, raw)
        if v is None:
            return "画面空欄(raw=%s)" % raw, "uncal"
        if spec.get("floor") is not None:
            v = max(v, spec["floor"])
        if law.get("max") is not None:
            v = min(v, law["max"])
        return fmt_dyn(v, spec.get("unit", "")), "law"
    if k == "calib":
        t = calib[spec["table"]]
        return (t[raw], "calib") if raw in t else ("未較正(raw=%s)" % raw, "uncal")
    return "raw=%s" % raw, "raw"


def decode_param(spec, p):
    k = spec["kind"]
    if k == "flag":
        return ("ON" if p >= 0.5 else "OFF"), spec["conf"]
    if k == "linear":
        return _fmt(spec["min"] + (spec["max"] - spec["min"]) * p, spec.get("unit", "")), spec["conf"]
    if k == "log":
        v = spec["min"] * math.exp(math.log(spec["max"] / spec["min"]) * p)
        v = int(round(v, 2 - int(math.floor(math.log10(abs(v))))))  # 有効数字3桁（画面表示に合わせる）
        return _fmt(v, spec.get("unit", "")), spec["conf"]
    if k == "enum":
        for key, lab in spec["map"].items():
            if abs(float(key) - p) < 1e-6:
                return lab, spec["conf"]
        return "未較正(raw=%.4f)" % p, "uncal"
    return "raw=%.4f" % p, "raw"


def read(path, timeline=None, show_all=False):
    with open(MAP_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    res = []
    for mdl in load_models(path):
        if timeline and mdl["timeline"] != timeline:
            continue
        b = mdl["model"]
        tabs = channel_tables(b)
        strips = []
        for tab in tabs:
            names = tab["names"]
            aliases = track_aliases(tab)
            if aliases:
                names = list(names)
                for alias, cols in aliases.items():
                    for col in cols:
                        if col < len(names) and not names[col]:
                            names[col] = alias
            if not names or names[0].startswith(("VCA", "Mapping", "Folder")) or names[0] == "":
                continue
            seen = {}
            for col, nm in enumerate(names):
                if nm in seen:
                    continue  # ステレオの2列目は1列目で代表
                seen[nm] = col
                vals = {}
                for key, spec in cfg["channel_items"].items():
                    arr = tab["items"].get(spec["id"])
                    raw = arr[col] if arr and col < len(arr) else None
                    text, conf = decode_item(spec, raw, cfg.get("calib_tables", {}), cfg.get("dyn_laws"))
                    vals[spec.get("label", key)] = {"value": text, "raw": raw, "conf": conf}
                strips.append({"name": nm, "type": "bus" if nm.startswith("Bus") else "track",
                               "column": col, "values": vals, "plugins": []})
        # プラグインを所属先へ
        track_cols = {}
        for tab in tabs:
            if tab["names"] and not tab["names"][0].startswith(("VCA", "Mapping", "Folder", "Bus")) and tab["names"][0]:
                track_cols = {i: n for i, n in enumerate(tab["names"])}
                break
        for pl in plugins(b):
            owner = ("Bus %d" % (pl["column"] + 1)) if pl["kind"] == "bus" else track_cols.get(pl["column"], "列%d" % pl["column"])
            pspec = cfg["plugins"].get(pl["name"], {})
            dec = {}
            for pname, pv in pl["params"].items():
                sp = pspec.get(pname)
                if sp:
                    text, conf = decode_param(sp, pv)
                    dec[sp["label"]] = {"value": text, "raw": round(pv, 6), "conf": conf}
                elif show_all:
                    dec[pname] = {"value": "raw=%.4f" % pv, "raw": round(pv, 6), "conf": "raw"}
            st = cfg.get("plugin_state", {})
            if pl["state"] is not None and pl["slot"] >= 6 and pl["name"] in st.get("enabled_for_builtin", []):
                off = pl["state"] & st["disabled_bit"]
                dec["enabled"] = {"value": "OFF" if off else "ON", "raw": pl["state"], "conf": "direct"}
            elif show_all and pl["state"] is not None:
                dec["state_flags"] = {"value": "raw=0x%x" % pl["state"], "raw": pl["state"], "conf": "raw"}
            slot = ("内蔵FX(%d)" % pl["slot"]) if pl["slot"] >= 6 else ("Slot%d" % (pl["slot"] + 1))
            entry = {"plugin": pl["name"], "slot": slot, "params": dec}
            for s in strips:
                if s["name"] == owner:
                    s["plugins"].append(entry)
                    break
            else:
                strips.append({"name": owner, "type": pl["kind"], "column": pl["column"],
                               "values": {}, "plugins": [entry]})
        res.append({"timeline": mdl["timeline"], "seqref": mdl["seqref"], "strips": strips})
    return res


# ---------------- カット編集情報（クリップ位置・色・トランジション）----------------
def _dur(txt):
    """Duration 欄 '16816|00009a999999e93f'（整数フレーム|端数の double LE）→ float フレーム"""
    if txt is None or txt == "":
        return None
    txt = str(txt)
    if "|" in txt:
        n, frac = txt.split("|", 1)
        return int(n) + struct.unpack("<d", binascii.unhexlify(frac))[0]
    return float(txt)


def _color_from_blob(hx, cmap):
    """LockableBlob の FieldsBlob（BlobData = 00002711 00000003 80 28 <色番号>）→ 色名"""
    m = re.search(r"0000271100000003802([0-9a-f])([0-9a-f]{2})", hx.lower())
    if not m:
        return None
    code = int(m.group(2), 16)
    return cmap.get(code, "未較正(%d)" % code)


def _tc(frames, fps):
    if frames is None or not fps:
        return None
    f = int(round(frames))
    fp = int(round(fps))
    return "%02d:%02d:%02d:%02d" % (f // (3600 * fp), f // (60 * fp) % 60, f // fp % 60, f % fp)


# ---------------- クリップのエフェクト（音量・フェード）：EffectFiltersBA ----------------
def _varint(b, i):
    v = s = 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return v, i


def _pb(b):
    """protobuf の (field, wiretype, value) 列。wiretype 0=int、1=8バイト、2=bytes、5=4バイト"""
    out, i = [], 0
    while i < len(b):
        key, i = _varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 1:
            v, i = b[i:i + 8], i + 8
        elif wt == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        elif wt == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError("wiretype %d" % wt)
        out.append((f, wt, v))
    return out


KF_FLAGS_DEFAULT = 0x000C0000  # 画面で付けたキーフレームは全部この値（補間の種類と推測・未確定）


def decode_keyframes(b):
    """つまみのキーフレーム列（番号のメッセージの field10）。
    形式：int32BE（−16×個数）＋個数×［u32LE フレーム（**素材のフレーム番号**。クリップ先頭なら素材In）・u32LE フラグ・double LE 値］。
    起点は 2026-10-18 In=144 のクリップで書き出し実測（素材24/48に置くとクリップ全体が最後の値、素材168/192 でクリップ+1s/+2s に効いた）。
    UI-made keys (Resolve 21.1.1): +20 s → 480, +25 s → 600, +30 s 12 f → 732 at 24 fps; values −3 / −15 / +6 dB"""
    if len(b) < 4:
        return []
    n = -struct.unpack_from(">i", b, 0)[0] // 16
    out = []
    for k in range(n):
        o = 4 + 16 * k
        if o + 16 > len(b):
            break
        fr_, fl = struct.unpack_from("<II", b, o)
        out.append({"frame": fr_, "value": struct.unpack_from("<d", b, o + 8)[0], "flags": fl})
    return out


def encode_keyframes(points, flags=KF_FLAGS_DEFAULT):
    """[(フレーム, 値)] → field10 のバイト列（decode_keyframes の逆）。drp_compose 等の書き込み用"""
    pts = sorted(points)
    out = struct.pack(">i", -16 * len(pts))
    for fr_, v in pts:
        out += struct.pack("<II", int(fr_), flags) + struct.pack("<d", float(v))
    return out


# ---------------- タイムラインマーカー ----------------
# 置き場所：project.xml の Sm2SequenceLockableBlob（BlobOwner＝Sm2Sequence の DbId）。FieldsBlob＝QVariantMap
# {"BlobData": 00002711 ＋ u32BE 長さ ＋ 0x80（無圧縮）/0x81（zstd）＋ protobuf}。protobuf の field2 が
# マーカー一覧（field2 の繰り返し：{1: {1: zigzag(フレーム)}, 2: u32BE 2 ＋ u32BE 長さ ＋ {1: {1: 色ビット,
# 3: メモ, 3: 長さ（フレーム数の10進文字列）, 3: 名前, 6: customData}}}）。フレームはタイムライン開始からの位置
# （API の Timeline.GetMarkers と同じ）。2026-10-18 API AddMarker で作った書き出し4本（16色・長さ1〜24・
# 日本語・XML 記号・customData）で確認
LOCKABLE_TAG = 0x2711


def _zigzag(n):
    return (n << 1) ^ (n >> 63)


def _unzigzag(v):
    return (v >> 1) ^ -(v & 1)


def _vint(n):
    out = bytearray()
    while n > 127:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def _pbpack(fields):
    out = b""
    for f, w, v in fields:
        out += _vint(f * 8 + w)
        out += _vint(v) if w == 0 else (_vint(len(v)) + v if w == 2 else v)
    return out


def _zstd_decompress(data):
    try:
        from compression import zstd
        return zstd.decompress(data)
    except ImportError:
        try:
            import zstandard
        except ImportError:
            raise ValueError("zstd-compressed data: needs Python 3.14+ or `pip install zstandard`") from None
        return zstandard.ZstdDecompressor().decompressobj().decompress(data)


def lockable_payload(fields_blob):
    """LockableBlob の FieldsBlob（bytes）→ protobuf の中身。形式が違えば None"""
    try:
        d = parse_fieldsblob(fields_blob)
    except Exception:
        return None
    bd = d.get("BlobData")
    if not isinstance(bd, (bytes, bytearray)) or len(bd) < 9:
        return None
    tag, n = struct.unpack_from(">II", bd, 0)
    if tag != LOCKABLE_TAG or n != len(bd) - 8:
        return None
    if bd[8] == 0x80:
        return bytes(bd[9:])
    if bd[8] == 0x81:
        return _zstd_decompress(bytes(bd[9:]))
    return None


def lockable_fields_blob(payload):
    """protobuf の中身 → LockableBlob の FieldsBlob（bytes・無圧縮）。lockable_payload の逆"""
    bd = struct.pack(">II", LOCKABLE_TAG, len(payload) + 1) + b"\x80" + payload
    key = "BlobData".encode("utf-16-be")
    return (struct.pack(">II", 1, 1) + struct.pack(">I", len(key)) + key +
            struct.pack(">IB", 12, 0) + struct.pack(">I", len(bd)) + bd)


def decode_markers(payload, colors):
    """LockableBlob の protobuf → [{frame, color, name, note, duration, custom_data}]（frame はタイムライン開始から）"""
    out = []
    for f, w, v in _pb(payload):
        if (f, w) != (2, 2):
            continue
        for ef, ew, ev in _pb(v):
            if ew != 2 or ef not in (1, 2):
                continue
            e = {}
            for a, b_, c in _pb(ev):
                e.setdefault(a, c)
            if ef == 1:
                pos = e.get(1, 0)
                if not isinstance(pos, int):
                    raise ValueError("unexpected legacy marker position")
                frame = pos
            else:
                pos = e.get(1, b"")
                if not isinstance(pos, bytes):
                    raise ValueError("unexpected marker position")
                frame = _unzigzag(dict((a, c) for a, b_, c in _pb(pos)).get(1, 0))
            val = e.get(2, b"")
            if len(val) < 8 or struct.unpack_from(">I", val, 4)[0] != len(val) - 8:
                raise ValueError("unexpected marker record")
            body = dict((a, c) for a, b_, c in _pb(val[8:])).get(1, b"")
            code, texts, custom = 0, [], ""
            for a, b_, c in _pb(body):
                if a == 1 and b_ == 0:
                    code = c
                elif a == 3 and b_ == 2:
                    texts.append(c.decode("utf-8"))
                elif a == 6 and b_ == 2:
                    custom = c.decode("utf-8")
            if len(texts) != 3:
                raise ValueError("unexpected marker text fields")
            out.append({"frame": frame, "color": colors.get(code, "未較正(%d)" % code),
                        "name": texts[2], "note": texts[0], "duration": int(texts[1]), "custom_data": custom})
    return sorted(out, key=lambda m: m["frame"])


def encode_markers(markers, colors):
    """[{frame, color, name, note, duration, custom_data}] → field2（マーカー一覧）の中身。decode_markers の逆"""
    codes = {v: k for k, v in colors.items()}
    entries = []
    for m in sorted(markers, key=lambda m: m["frame"]):
        if m["color"] not in codes:
            raise ValueError("unknown marker color: %s" % m["color"])
        body = [(1, 0, codes[m["color"]]), (3, 2, m.get("note", "").encode("utf-8")),
                (3, 2, str(int(m.get("duration", 1))).encode()), (3, 2, m.get("name", "").encode("utf-8"))]
        if m.get("custom_data"):
            body.append((6, 2, m["custom_data"].encode("utf-8")))
        inner = _pbpack([(1, 2, _pbpack(body))])
        val = struct.pack(">II", 2, len(inner)) + inner
        pos = _zigzag(int(m["frame"]))
        entries.append((2, 2, _pbpack([(1, 2, _pbpack([(1, 0, pos)]) if pos else b""), (2, 2, val)])))
    return _pbpack(entries)


def timeline_start_frame(timeline_xml, fps):
    """タイムラインの開始フレーム＝Sm2Sequence の MediaExtents（double LE 開始秒・長さ秒）の開始秒 × fps。
    2026-10-18 書き出し・読み込みで確認：開始秒 3600 → Timeline.GetStartFrame() 86400（24fps）、0 → 0。見つからなければ None"""
    m = re.search(r"<Sm2Sequence DbId=[^>]*>.*?<MediaExtents>([0-9a-fA-F]{32})</MediaExtents>", timeline_xml, re.S)
    if not m or not fps:
        return None
    return int(round(struct.unpack("<d", binascii.unhexlify(m.group(1))[:8])[0] * fps))


def clip_effects(blob):
    """EffectFiltersBA → [{type, params{id: double}}]。
    形式：u32BE 版(2)・u32BE 長さ（フラグ1バイトを含む）・フラグ（0x80=無圧縮／0x81=zstd）・protobuf。
    protobuf：field1(繰返し)=エフェクト {1:種別, 9(繰返し):つまみ {1:番号, 3:{1:{2:double}}}}"""
    if not blob or len(blob) < 9:
        return []
    ln = struct.unpack_from(">I", blob, 4)[0]
    flag, payload = blob[8], blob[9:8 + ln]
    if flag == 0x81:
        try:
            from compression import zstd  # Python 3.14+
        except ImportError:
            try:
                import zstandard
                payload = zstandard.ZstdDecompressor().decompressobj().decompress(payload)
            except ImportError:
                return [{"type": None, "params": {}, "error": "zstd 圧縮（Python 3.14 以上か zstandard が必要）"}]
        else:
            payload = zstd.decompress(payload)
    elif flag != 0x80:
        return [{"type": None, "params": {}, "error": "未知のフラグ 0x%02x" % flag}]
    out = []
    for f, wt, v in _pb(payload):
        if f != 1 or wt != 2:
            continue
        eff = {"type": None, "params": {}}
        for f2, wt2, v2 in _pb(v):
            if f2 == 1 and wt2 == 0:
                eff["type"] = v2
            elif f2 == 9 and wt2 == 2 and v2:
                pid, val = None, None
                for f3, wt3, v3 in _pb(v2):
                    if f3 == 1 and wt3 == 0:
                        pid = v3
                    elif f3 == 3 and wt3 == 2:
                        for f4, wt4, v4 in _pb(v3):
                            if f4 == 1 and wt4 == 2:
                                for f5, wt5, v5 in _pb(v4):
                                    if f5 == 2 and wt5 == 1:
                                        val = struct.unpack("<d", v5)[0]
                                    elif f5 == 7 and wt5 == 2 and len(v5) % 8 == 0:
                                        # 点の列（double・ビッグエンディアン）。フェードのカーブ点で観測
                                        val = list(struct.unpack(">%dd" % (len(v5) // 8), v5))
                    elif f3 == 10 and wt3 == 2:
                        eff.setdefault("keyframes", {})[pid] = decode_keyframes(v3)
                if pid is not None:
                    eff["params"][pid] = val
        out.append(eff)
    return out


def clip_plugins(blob, pspec):
    """クリップ単位の内蔵FX（Voice Isolation・Dialogue Leveler 等）。クリップの FieldsBlob
    （u32BE 版2・u32BE 長さ・フラグ 0x80/0x81(zstd)・protobuf）内の文字列 "FL::ClipFX" の後ろに zlib で
    プラグイン記録（トラックと同じ「bmd:<名前>:<ID>」＋つまみ64バイト名＋float32）が入る。
    無効にすると記録自体が消える（＝記録があれば有効）。2026-10-18 API SetVoiceIsolationState／SetProperty で確認"""
    if not blob or len(blob) < 9 or blob[8] not in (0x80, 0x81):
        return []
    ln = struct.unpack_from(">I", blob, 4)[0]
    pl = blob[9:8 + ln]
    if blob[8] == 0x81:
        try:
            from compression import zstd
            pl = zstd.decompress(pl)
        except ImportError:
            try:
                import zstandard
                pl = zstandard.ZstdDecompressor().decompressobj().decompress(pl)
            except ImportError:
                return [{"plugin": "?", "params": {}, "error": "zstd 圧縮（Python 3.14 以上か zstandard が必要）"}]
    i = pl.find(b"FL::ClipFX")
    if i < 0:
        return []
    zi = pl.find(b"\x78\x9c", i)
    if zi < 0:
        return []
    try:
        raw = zlib.decompressobj().decompress(pl[zi:])
    except zlib.error:
        return []
    out = []
    hits = list(re.finditer(rb"bmd:([A-Za-z \-]+):(\d+)", raw))
    for k, m in enumerate(hits):
        s = m.start()
        end = hits[k + 1].start() if k + 1 < len(hits) else len(raw)
        name = m.group(1).decode()
        spec = pspec.get(name, {})
        dec = {}
        for pm in re.finditer(PARAM_RE, raw[s:end]):
            q = s + pm.start()
            nm = pm.group(1)
            if q + 68 > len(raw) or any(c != 0 for c in raw[q + len(nm):q + 64]):
                continue
            v = struct.unpack_from("<f", raw, q + 64)[0]
            sp = spec.get(nm.decode())
            if sp:
                text, conf = decode_param(sp, v)
                dec[sp["label"]] = {"value": text, "raw": round(v, 6), "conf": conf}
        out.append({"plugin": name, "params": dec})
    return out


def clip_audio_fx(blob, emap):
    """clip_effects を map.yaml clip_effects で名前付きに。{fade_in: フレーム, fade_out:, volume_db:}"""
    res = {}
    for eff in clip_effects(blob):
        spec = emap.get(eff["type"])
        if not spec:
            continue
        for pid, val in eff["params"].items():
            nm = spec["params"].get(pid)
            if nm and nm not in res:
                res[nm] = val
        for pid, kfs in eff.get("keyframes", {}).items():
            nm = spec["params"].get(pid)
            if nm and kfs:
                res[nm + "_keyframes"] = kfs
    return res


def _items_from_xml(seq_xml):
    """SeqContainer の XML から [ {track, kind, name, start, duration, in, ...} ] を返す"""
    out = []
    counts = {}
    for tm in re.finditer(r"<Sm2TiTrack DbId=\"[^\"]+\">(.*?)</Sm2TiTrack>", seq_xml, re.S):
        body = tm.group(1)
        ty = re.search(r"<Type>(\d+)</Type>", body)
        tkey = ty.group(1) if ty else None
        counts[tkey] = counts.get(tkey, 0) + 1
        nm = re.search(r"<UserDefinedName>([^<]*)</UserDefinedName>|<UserDefinedName/>", body)
        tname = nm.group(1) if nm and nm.group(1) else "@%s%d" % ("A" if tkey == "1" else "V", counts[tkey])
        for im in re.finditer(r"<(Sm2Ti\w+) DbId=\"([^\"]+)\">(.*?)</\1>", body, re.S):
            kind, dbid, ib = im.group(1), im.group(2), im.group(3)
            g = lambda tag: (re.search(r"<%s>([^<]*)</%s>" % (tag, tag), ib) or [None, None])[1]
            out.append({"track_type": "audio" if ty and ty.group(1) == "1" else "video", "track": tname,
                        "kind": kind, "id": dbid, "name": g("Name"), "pretty": g("PrettyType"),
                        "start": int(g("Start")) if g("Start") else None, "duration": _dur(g("Duration")),
                        "in": float(g("In")) if g("In") else 0.0, "alignment": g("AlignmentType"),
                        "position": g("Position"), "fx": g("EffectFiltersBA"),
                        "track_index": counts[tkey], "media_path": g("MediaFilePath"), "media_ref": g("MediaRef"),
                        "fields": (re.search(r"^\s*<FieldsBlob>([0-9a-fA-F]*)</FieldsBlob>", ib, re.M) or [None, None])[1]})
    return out


def edits_from_drp(path, cmap, mcolors=None):
    mcolors = mcolors or {}
    res = []
    with zipfile.ZipFile(path) as z:
        pj = z.read("project.xml").decode("utf-8", "replace")
        colors, markers = {}, {}
        for m in re.finditer(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>\s*<BlobOwner>([^<]+)</BlobOwner>", pj):
            c = _color_from_blob(m.group(1), cmap)
            if c:
                colors[m.group(2)] = c
        for m in re.finditer(r"<Sm2SequenceLockableBlob DbId=\"[^\"]+\">\s*<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>\s*"
                             r"<BlobOwner>([^<]+)</BlobOwner>", pj):
            try:
                payload = lockable_payload(binascii.unhexlify(m.group(1)))
                if payload is not None:
                    markers[m.group(2)] = decode_markers(payload, mcolors)
            except ValueError as e:
                markers[m.group(2)] = None
                sys.stderr.write("マーカーを読めない（%s）\n" % e)
        mp = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith("MpFolder.xml"))
        for n in z.namelist():
            if not n.startswith("SeqContainer/"):
                continue
            x = z.read(n).decode("utf-8", "replace")
            cid = re.search(r"<Sm2SequenceContainer DbId=\"([^\"]+)\"", x)
            # タイムライン名・fps：MpFolder の Sm2Timeline のうち Sequence が一致するもの
            tl_name, fps = "(名前不明)", None
            seq = re.search(r"<Sequence>([^<]+)</Sequence>", x)
            seq_id, start_frame = None, None
            for tm in re.finditer(r"<Sm2Timeline DbId=[^>]*>(.*?)</Sm2Timeline>", mp, re.S):
                if seq and seq.group(1) in tm.group(1):
                    nm = re.search(r"<Name>([^<]*)</Name>", tm.group(1))
                    tl_name = nm.group(1) if nm else tl_name
                    fr_ = re.search(r"<FrameRate>([0-9a-f]{16})", tm.group(1))
                    if fr_:
                        fps = struct.unpack("<d", binascii.unhexlify(fr_.group(1)))[0]
                    sq = re.search(r'<Sm2Sequence DbId="([^"]+)"', tm.group(1))
                    seq_id = sq.group(1) if sq else None
                    start_frame = timeline_start_frame(tm.group(1), fps)
                    break
            items = _items_from_xml(x)
            for it in items:
                it["color"] = colors.get(it["id"])
            res.append({"timeline": tl_name, "fps": fps, "items": items, "markers": markers.get(seq_id),
                        "start_frame": start_frame})
    return res


def edits_from_db(path, cmap, mcolors=None):
    mcolors = mcolors or {}
    con = sqlite3.connect("file:%s?mode=ro&immutable=1" % path, uri=True)
    colors = {}
    try:
        for fb, owner in con.execute("select hex(FieldsBlob), BlobOwner from BtLockableBlob where FieldsBlob is not null"):
            c = _color_from_blob(fb, cmap)
            if c:
                colors[owner] = c
    except sqlite3.Error:
        pass
    markers = {}
    try:
        for fb, owner in con.execute("select FieldsBlob, BlobOwner from BtLockableBlob where FieldsBlob is not null"):
            payload = lockable_payload(bytes(fb))
            if payload is not None and owner not in colors:
                ms = decode_markers(payload, mcolors)
                if ms:
                    markers[owner] = ms
    except (sqlite3.Error, ValueError):
        pass
    res = []
    for tl_name, seq in con.execute("select Name, Sequence from Sm2Timeline"):
        items = []
        q = ("select k.Type, k.UserDefinedName, i.DbType, i.Sm2TiItem_id, i.Name, i.PrettyType, i.Start, i.Duration, "
             "i.\"In\", i.AlignmentType, i.Position, i.EffectFiltersBA, i.FieldsBlob from Sm2TiItem i join Sm2TiTrack k on i.Sm2TiTrack_id = k.Sm2TiTrack_id "
             "where k.Sequence = ? order by k.rowid, i.Start")
        for ty, tn, kind, iid, nm, pt, st, du, inn, al, po, fx, fb in con.execute(q, (seq,)):
            items.append({"track_type": "audio" if ty == 1 else "video", "track": tn or "", "kind": kind, "id": iid,
                          "name": nm, "pretty": pt, "start": int(st) if st not in (None, "") else None, "duration": _dur(du),
                          "in": float(inn) if inn not in (None, "") else 0.0,
                          "alignment": str(al) if al is not None else None, "position": str(po) if po is not None else None,
                          "color": colors.get(iid), "fx": bytes(fx) if fx else None,
                          "fields": bytes(fb) if fb else None})
        if items:
            res.append({"timeline": tl_name, "fps": None, "items": items, "markers": markers.get(seq), "start_frame": None})
    con.close()
    return res


def read_edits(path, timeline=None):
    with open(MAP_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cmap = cfg.get("clip_colors", {})
    amap = cfg.get("transition_alignment", {})
    emap = cfg.get("clip_effects", {})
    mcolors = cfg.get("marker_colors", {})
    res = edits_from_drp(path, cmap, mcolors) if path.lower().endswith(".drp") else edits_from_db(path, cmap, mcolors)
    out = []
    for tl in res:
        if timeline and tl["timeline"] != timeline:
            continue
        rows = []
        for it in tl["items"]:
            st, du = it["start"], it["duration"]
            row = {"track": it["track"], "type": it["track_type"], "kind": it["kind"].replace("Sm2Ti", ""),
                   "name": it["name"], "start": st, "end": (st + du) if st is not None and du is not None else None,
                   "duration": du, "src_in": it["in"], "src_out": (it["in"] + du) if du is not None else None,
                   "color": it.get("color")}
            fx = it.get("fx")
            if isinstance(fx, str):
                fx = binascii.unhexlify(fx) if fx else None
            if fx:
                row.update(clip_audio_fx(fx, emap))
            fb = it.get("fields")
            if isinstance(fb, str):
                fb = binascii.unhexlify(fb) if fb else None
            cps = clip_plugins(fb, cfg.get("plugins", {})) if fb else []
            if cps:
                row["clip_plugins"] = cps
            if it["kind"] == "Sm2TiTransition":
                row["transition"] = it["pretty"]
                row["alignment"] = amap.get(int(it["alignment"]), it["alignment"]) if it["alignment"] else None
            if tl["fps"]:
                row["start_tc"] = _tc(st, tl["fps"])
            rows.append(row)
        marks = []
        for mk in tl.get("markers") or []:  # None = present but unreadable (see stderr)
            mk = dict(mk, offset=mk["frame"])
            mk["frame"] = mk["offset"] + tl["start_frame"] if tl.get("start_frame") is not None else None
            marks.append(mk)
        out.append({"timeline": tl["timeline"], "fps": tl["fps"], "start_frame": tl.get("start_frame"),
                    "items": rows, "markers": marks})
    return out


def _curve_text(key, v):
    """フェードのカーブ点 [位置%, レベル(0.1 dB)] → 表示。
    位置＝フェード区間の先頭からの％、レベル＝その位置での音量（0.1 dB 単位、−60＝−6.0 dB）。直線（音量の一次変化）は記録なし。
    カーブは書いた点をちょうど通る（書き出し実測：位置25・50・75・78%）。点が50%のときは直線の dB 曲線の一定倍、
    それ以外の位置での点以外の形の式は未特定。値はクリップ音量（番号95）に対する相対値。
    根拠：書き出し音量の実測（位置25・50・75・78%）と GUI で作った7例。FORMAT.md「Fade curve」"""
    import math
    head = "In" if key == "fade_in_curve" else "Out"
    if not isinstance(v, list) or len(v) != 2:
        return "%s カーブ=%s" % (head, v)
    pos, lv = v
    x = pos / 100.0
    amp = x if key == "fade_in_curve" else 1.0 - x
    straight = 20 * math.log10(amp) if 0 < amp < 1 else None
    db = lv / 10.0
    if straight is None:
        side = ""
    elif abs(db - straight) < 0.05:
        side = "・直線と同じ"
    else:
        side = "・直線 %.1f dB より%s" % (straight, "上に凸" if db > straight else "下に凸")
    return "%s カーブ点 位置%g%%で %.1f dB%s" % (head, pos, db, side)


def edits_markdown(res):
    lines = []
    for tl in res:
        lines.append("## タイムライン：%s（%s fps）" % (tl["timeline"], tl["fps"]))
        lines.append("| トラック | 種類 | 名前 | 開始 | 終了 | 長さ | ソースIn | ソースOut | 色 | フェードIn | フェードOut | フェードカーブ | クリップ音量 | 音量キーフレーム | クリップFX | 備考 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in tl["items"]:
            note = ""
            if r["kind"] == "Transition":
                note = "%s／配置=%s" % (r.get("transition"), r.get("alignment"))
            f = lambda v: "" if v is None else (("%g" % v) if isinstance(v, float) else str(v))
            lines.append("| %s | %s | %s | %s%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                r["track"], r["kind"], r["name"] or "", f(r["start"]),
                ("（%s）" % r["start_tc"]) if r.get("start_tc") else "", f(r["end"]), f(r["duration"]),
                f(r["src_in"]) if r["kind"] != "Transition" else "", f(r["src_out"]) if r["kind"] != "Transition" else "",
                r["color"] or "", f(r.get("fade_in")), f(r.get("fade_out")),
                "／".join(_curve_text(k, r[k]) for k in ("fade_in_curve", "fade_out_curve") if r.get(k)),
                ("%g dB" % r["volume_db"]) if r.get("volume_db") is not None else "",
                "／".join("素材%df%s %+g dB" % (k["frame"], ("（クリップ%+.2fs）" % ((k["frame"] - (r["src_in"] or 0)) / tl["fps"])) if tl.get("fps") else "", k["value"])
                         for k in r.get("volume_db_keyframes", [])),
                "／".join("%s（%s）" % (c["plugin"], "、".join("%s=%s" % (k, v["value"]) for k, v in c["params"].items()))
                         for c in r.get("clip_plugins", [])), note))
        if tl.get("markers"):
            lines.append("")
            lines.append("| マーカー位置 | 開始から | 色 | 名前 | メモ | 長さ | customData |")
            lines.append("|---|---|---|---|---|---|---|")
            for mk in tl["markers"]:
                lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                    "" if mk["frame"] is None else mk["frame"], mk["offset"], mk["color"], mk["name"],
                    mk["note"].replace("|", "\\|"), mk["duration"], mk["custom_data"]))
        lines.append("")
    lines.append("単位はフレーム（タイムラインのfps）。開始＝タイムライン上の位置、ソースIn/Out＝素材内の位置。フェードIn/Out＝クリップのフェード長（フレーム。EffectFiltersBA）。フェードのカーブ形状は未対応")
    return "\n".join(lines)


# ---------------- 出力 ----------------
CONF_MARK = {"law": "※", "direct": "", "two_point": "²", "calib": "※", "assumed": "?", "uncal": "✗", "raw": "✗", "なし": ""}


def to_markdown(res):
    lines = []
    for tl in res:
        lines.append("## タイムライン：%s" % tl["timeline"])
        for s in tl["strips"]:
            lines.append("\n### %s（%s・列%d）" % (s["name"], s["type"], s["column"]))
            if s["values"]:
                lines.append("| 項目 | 値 | 生値 |")
                lines.append("|---|---|---|")
                for k, v in s["values"].items():
                    lines.append("| %s | %s%s | %s |" % (k, v["value"], CONF_MARK.get(v["conf"], ""), v["raw"]))
            for p in s["plugins"]:
                ps = "、".join("%s=%s%s" % (k, v["value"], CONF_MARK.get(v["conf"], "")) for k, v in p["params"].items())
                lines.append("- プラグイン %s %s：%s" % (p["slot"], p["plugin"], ps))
        lines.append("")
    lines.append("記号：無印=直読（既知値と独立照合済み）／²=2点較正／※=画面照合表／?=1点のみ・範囲仮定／✗=未較正・意味未確定")
    return "\n".join(lines)


def check_expect(res, exp):
    """expect.yaml：{timeline:, strips: {名前: {項目: 期待値文字列}, ...}} と突き合わせる"""
    ok, ng = 0, []
    for tl in res:
        if exp.get("timeline") and tl["timeline"] != exp["timeline"]:
            continue
        by = {s["name"]: s for s in tl["strips"]}
        for nm, items in exp["strips"].items():
            s = by.get(nm)
            for key, want in items.items():
                got = None
                if s:
                    if key in s["values"]:
                        got = s["values"][key]["value"]
                    else:
                        for p in s["plugins"]:
                            pk = key.split(".", 1)
                            if len(pk) == 2 and p["plugin"] == pk[0] and pk[1] in p["params"]:
                                got = p["params"][pk[1]]["value"]
                if got == str(want):
                    ok += 1
                else:
                    ng.append((nm, key, want, got))
    return ok, ng


def configure_stdio():
    """Keep redirected Windows CLI output UTF-8, independently of its code page."""
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")


def main(argv=None, prog=None):
    configure_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, prog=prog)
    ap.add_argument("path")
    ap.add_argument("--timeline")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="対応表にないプラグインのつまみも生値で出す")
    ap.add_argument("--expect", help="期待値YAML。一致数と不一致を表示し、不一致があれば終了コード1")
    ap.add_argument("--edits", action="store_true", help="ミキサー設定の代わりにカット編集情報（クリップ位置・色・トランジション）を出す")
    a = ap.parse_args(argv)
    if a.edits:
        er = read_edits(a.path, a.timeline)
        print(json.dumps(er, ensure_ascii=False, indent=1) if a.json else edits_markdown(er))
        return
    res = read(a.path, a.timeline, a.all)
    if not res:
        print("FLStudioModelBA を持つタイムラインが見つからない", file=sys.stderr)
        sys.exit(2)
    if a.expect:
        exp = yaml.safe_load(open(a.expect, encoding="utf-8"))
        ok, ng = check_expect(res, exp)
        print("一致 %d 件／不一致 %d 件" % (ok, len(ng)))
        for nm, key, want, got in ng:
            print("  ✗ %s %s：期待 %s／実際 %s" % (nm, key, want, got))
        sys.exit(1 if ng else 0)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    else:
        print(to_markdown(res))


if __name__ == "__main__":
    main()
