"""解析用：.drp の FLStudioModelBA（Fairlight ミキサー設定）のチャンネル設定表へ任意の値を書き込んだ別drpを作る。

目的は換算表づくり（書き込んだ保存値 → Resolve に読み込ませて画面値を読む）。本番プロジェクトには使わない。
入力 drp は読むだけ。全変更を読み直して検証してから、出力を排他的に新規作成する（既存ファイルは上書きしない。
途中でエラーになったら出力ファイルは作らない）。

使い方:
  drpkit write IN.drp OUT.drp --set 'Track1:0x10d=51996' --set 'Bus 1:0x11d=1' ...
    名前 = トラック名（0xBC の名前）または 'Bus 1'。ステレオは同名の全列に書く
    内部名が空のトラックも @A1 / @A2 で指定できる（strip_id 0 / 1）。
    EQ band2〜5の周波数はHz・ノブ位置・帯域の3項目を同時指定する。
    例：Bus 1 band2 1000Hz（無料版19.1.3で確認）:
      --set 'Bus 1:0xf2=1000' --set 'Bus 1:0x335=218' --set 'Bus 1:0x289=1'
    自動換算：--eq-freq 'Bus 1:2=1234'（バンド1〜6、整数Hz）
    Resolve再読み込み時に値が正規化される例がある。再出力後は --verify-eq で照合する。
    値 = int32（10進 or 0x..）
    --timeline 名前 = 書き込むタイムライン。drp 内に対象タイムラインが複数あるときは必須（未指定なら拒否）
  drpkit write IN.drp --dump-item 0x10d     # 各表のその項目の値を表示
"""
import sys

import argparse
import binascii
import io
import math
import os
import re
import struct
import zipfile
import zlib

from . import reader as fr  # noqa: E402
from ._atomic import write_new_file  # noqa: E402


def _eq_law():
    with open(fr.MAP_PATH, encoding='utf-8') as stream:
        return fr.yaml.safe_load(stream)['eq_frequency_law']


def encode_eq_frequency(band, hz, preferred_range=None, law=None):
    """Encode integer Hz plus the linked logarithmic knob and (mid-band) range.

    GUI-entered Hz uses the nearest logarithmic knob position. Untouched factory
    defaults may carry a truncated Hz value with a different knob; do not fit the
    inverse to those defaults. The Hz record retains the exact integer.
    """
    law = _eq_law() if law is None else law
    if isinstance(band, bool) or not isinstance(band, int) or band not in range(1, 7):
        raise ValueError('EQ band must be 1..6')
    if isinstance(hz, bool):
        raise ValueError('EQ frequency must be finite integer Hz')
    try:
        frequency = float(hz)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError('EQ frequency must be finite integer Hz') from error
    if not math.isfinite(frequency) or not frequency.is_integer():
        raise ValueError('EQ frequency must be finite integer Hz (1 Hz resolution)')
    hz = int(frequency)
    ranges = law['ranges']
    if band in (1, 6):
        selected = law['fixed_bands'][band]
        candidates = [selected]
    else:
        candidates = list(range(len(ranges)))
        if preferred_range in candidates:
            candidates.remove(preferred_range)
            candidates.insert(0, preferred_range)
    selected = next((index for index in candidates
                     if ranges[index]['min_hz'] <= hz <= ranges[index]['max_hz']), None)
    if selected is None:
        raise ValueError('EQ band %d frequency %s Hz is outside its supported range' % (band, hz))
    limits = ranges[selected]
    position = law['steps'] * math.log(hz / limits['min_hz']) / math.log(limits['log_max_hz'] / limits['min_hz'])
    knob = max(0, min(law['steps'], math.floor(position + 0.5 + 1e-10)))
    result = {0xf0 + band: hz, 0x333 + band: knob}
    if 2 <= band <= 5:
        result[0x287 + band] = selected
    return result


def _selected_columns(tab, name):
    return (fr.track_aliases(tab).get(name, []) if name.startswith('@A')
            else [i for i, stored in enumerate(tab['names']) if stored == name])


def frequency_sets(model, requests, raw_sets=()):
    """Expand (strip, band, Hz) requests; refuse overlapping raw/semantic writes."""
    if not requests:
        return []
    tabs, output, occupied = fr.channel_tables(model), [], set()
    law = _eq_law()
    for name, band, hz in requests:
        matches = [(i, tab, _selected_columns(tab, name)) for i, tab in enumerate(tabs)
                   if _selected_columns(tab, name)]
        if len(matches) != 1:
            raise ValueError('EQ target %r must match exactly one mixer table' % name)
        index, tab, cols = matches[0]
        ranges = tab['items'].get(0x287 + band, []) if 2 <= band <= 5 else []
        preferred = {ranges[col] for col in cols if col < len(ranges)}
        encoded = encode_eq_frequency(band, hz, next(iter(preferred)) if len(preferred) == 1 else None, law)
        cells = {(index, col, item) for col in cols for item in encoded}
        if occupied & cells:
            raise ValueError('Duplicate/overlapping EQ frequency requests')
        for raw_name, item, _ in raw_sets:
            if item in encoded and set(cols) & set(_selected_columns(tab, raw_name)):
                raise ValueError('Raw --set conflicts with --eq-freq for %s band %s' % (name, band))
        if any(item not in tab['items'] for item in encoded):
            raise ValueError('EQ target does not contain all required frequency records')
        occupied.update(cells)
        output.extend((name, item, value) for item, value in encoded.items())
    return output


def verify_eq_frequencies(path, requests, timeline=None):
    """Compare requested Hz with an actual re-export; return all mismatches."""
    models = [m for m in fr.load_models(path) if timeline is None or m['timeline'] == timeline]
    if len(models) != 1:
        raise ValueError('Verification requires exactly one selected timeline')
    tabs, mismatches = fr.channel_tables(models[0]['model']), []
    for name, band, hz in requests:
        encoded = encode_eq_frequency(band, hz)
        expected = encoded[0xf0 + band]
        matches = [(tab, _selected_columns(tab, name)) for tab in tabs if _selected_columns(tab, name)]
        if len(matches) != 1:
            raise ValueError('Verification target %r is missing or ambiguous' % name)
        tab, cols = matches[0]
        values = tab['items'].get(0xf0 + band, [])
        actual = [values[col] if col < len(values) else None for col in cols]
        if any(value != expected for value in actual):
            mismatches.append({'name': name, 'band': band, 'expected_hz': expected, 'actual_hz': actual})
    return mismatches


def _locate_model(blob):
    """FieldsBlob（QVariantMap）の中で FLStudioModelBA の bytearray の位置 (長さ欄offset, データoffset, 長さ) を返す"""
    r = fr._R(blob)
    r.u32()
    n = r.u32()
    for _ in range(n):
        k = fr._qstr(r)
        t = struct.unpack_from(">I", blob, r.o)[0]
        if k == "FLStudioModelBA":
            assert t == 12, t
            lo = r.o + 5
            ln = struct.unpack_from(">I", blob, lo)[0]
            return lo, lo + 4, ln
        fr._qvar(r)
    return None


def _qcompress(raw):
    return struct.pack(">I", len(raw)) + zlib.compress(raw, 9)


def apply_sets(model, sets):
    """sets: [(名前, 項目番号, 値)]。チャンネル設定表のint32をその場で書き換える"""
    b = bytearray(model)
    tabs = fr.channel_tables(bytes(b))
    # Mid-band frequency is redundant state: Resolve restores Hz from the knob
    # and selected range on import. Do not report a Hz-only write as successful.
    requested = {(name, item) for name, item, _ in sets}
    for name, item, val in sets:
        if 0x0f2 <= item <= 0x0f5:
            band = item - 0x0f0
            companions = (0x333 + band, 0x287 + band)
            if any((name, key) not in requested for key in companions):
                raise SystemExit('EQ band %d frequency requires matching knob 0x%x and range 0x%x --set values; Hz alone is not applied by Resolve' % (band, *companions))
    done = []
    for name, item, val in sets:
        hit = False
        for tab in tabs:
            cols = _selected_columns(tab, name)
            if not cols:
                continue
            # 表内の該当レコードの位置を探す（_parse_records の位置情報を使う）
            recs = _records_with_pos(bytes(b), tab)
            if item not in recs:
                raise SystemExit("表 %s に項目 0x%x がない" % (tab["names"][:2], item))
            p, n = recs[item]
            for c in cols:
                struct.pack_into("<i", b, p + 12 + 4 * c, val)
                hit = True
            done.append((name, item, val, cols))
        if not hit:
            raise SystemExit("名前 %s の列が見つからない" % name)
    return bytes(b), done


def _records_with_pos(b, tab):
    if 'record_start' in tab:
        recs, _ = fr._parse_records(b, tab['record_start'])
        out = {}
        for p, item, n, _ in recs:
            out.setdefault(item, (p, n))
        if tab['names'] and tab['names'][0].startswith('Bus'):
            for p, item, n, _ in fr._bus_part_a_records(b, tab['record_start'], len(tab['names'])):
                out.setdefault(item, (p, n))
        return out
    pat = struct.pack("<II", 1, fr.NAMES_ITEM)
    for m in re.finditer(re.escape(pat), b):
        o = m.start()
        n = struct.unpack_from("<I", b, o + 8)[0]
        for c in range(max(0, o - 0x8000), o):
            if b[c:c + 4] != b"\x01\x00\x00\x00":
                continue
            it, nn = struct.unpack_from("<II", b, c + 4)
            if nn != n or it > fr.NAMES_ITEM:
                continue
            r, _ = fr._parse_records(b, c, stop=o + 1)
            if not any(x[0] == o for x in r):
                continue
            recs, _ = fr._parse_records(b, c)
            names = next(x[3] for x in recs if x[1] == fr.NAMES_ITEM)
            if names == tab["names"]:
                out = {}
                for p, item, nn2, _v in recs:
                    out.setdefault(item, (p, nn2))
                return out
            break
    raise SystemExit("表の位置が見つからない")


def _raw_cells(model):
    """{(表番号, 列, 項目): int32}。空名の別表を衝突させない。"""
    out = {}
    for table_index, tab in enumerate(fr.channel_tables(model)):
        for item, vals in tab["items"].items():
            if item == fr.NAMES_ITEM:
                continue
            for col, v in enumerate(vals):
                out[(table_index, col, item)] = v
    return out


def _verify(old, new, done):
    """書き換え後の表を読み直し、指定したセルだけが指定値に変わったことを確かめる"""
    a, b = _raw_cells(old), _raw_cells(new)
    if set(a) != set(b):
        raise SystemExit("検証失敗：表の構造が変わった（出力は作らない）")
    want = {}
    for table_index, tab in enumerate(fr.channel_tables(old)):
        for name, item, val, cols in done:
            matched = (fr.track_aliases(tab).get(name, []) if name.startswith('@A')
                       else [c for c, nm in enumerate(tab['names']) if nm == name])
            if matched == cols:
                for c in cols:
                    want[(table_index, c, item)] = val
    changed = {k for k in a if a[k] != b[k]}
    for k, v in want.items():
        if b.get(k) != v:
            raise SystemExit("検証失敗：%s が %r（期待 %d）。出力は作らない" % (k, b.get(k), v))
    extra = changed - set(want)
    if extra:
        raise SystemExit("検証失敗：指定外のセルが変わった %s。出力は作らない" % sorted(extra)[:5])


def _targets(zin):
    """[(MpFolder.xmlのパス, タイムライン名)] FLStudioModelBA を持つ FieldsBlob ごと"""
    out = []
    for info in zin.infolist():
        if not info.filename.endswith("MpFolder.xml"):
            continue
        t = zin.read(info.filename).decode("utf-8")
        for m in re.finditer(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", t):
            hx = m.group(1)
            if "0046004c00530074" in hx.lower() and _locate_model(binascii.unhexlify(hx)):
                out.append((info.filename, fr.timeline_name_at(t, m.start())))
    return out


def build_drp(src, sets, timeline=None, raw_patch=None, eq_frequencies=None):
    """書き換えた drp を bytes で返す（ファイルは作らない）。全変更を検証してから返す"""
    zin = zipfile.ZipFile(src)
    targets = _targets(zin)
    names = sorted({tl for _, tl in targets})
    if not targets:
        raise SystemExit("FLStudioModelBA を持つタイムラインがない")
    if timeline is None:
        if len(targets) > 1:
            raise SystemExit("対象タイムラインが複数ある。--timeline で1つ指定する：%s" % names)
    elif timeline not in names:
        raise SystemExit("タイムライン %r がない：%s" % (timeline, names))
    elif sum(1 for _, tl in targets if tl == timeline) > 1:
        raise SystemExit("同名タイムライン %r が複数ある（書き込まない）" % timeline)
    buf = io.BytesIO()
    zout = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    log = []
    for info in zin.infolist():
        data = zin.read(info.filename)
        if info.filename.endswith("MpFolder.xml"):
            t = data.decode("utf-8")

            def sub(m):
                hx = m.group(1)
                if "0046004c00530074" not in hx.lower():
                    return m.group(0)
                if timeline is not None and fr.timeline_name_at(t, m.start()) != timeline:
                    return m.group(0)
                blob = binascii.unhexlify(hx)
                loc = _locate_model(blob)
                if not loc:
                    return m.group(0)
                lo, do, ln = loc
                model = zlib.decompress(blob[do + 4:do + ln])
                try:
                    expanded = list(sets) + frequency_sets(model, eq_frequencies or [], sets)
                except ValueError as error:
                    raise SystemExit(str(error)) from error
                new, done = apply_sets(model, expanded)
                if raw_patch:
                    new = raw_patch(new)
                else:
                    _verify(model, new, done)
                log.extend(done)
                comp = _qcompress(new)
                nb = blob[:lo] + struct.pack(">I", len(comp)) + comp + blob[do + ln:]
                return "<FieldsBlob>%s</FieldsBlob>" % binascii.hexlify(nb).decode()

            t = re.sub(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", sub, t)
            data = t.encode("utf-8")
        zi = zipfile.ZipInfo(info.filename, info.date_time)
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = info.external_attr
        zout.writestr(zi, data)
    zout.close()
    zin.close()
    out = buf.getvalue()
    # 出来上がった zip を読み直して、対象タイムラインのモデルが読めることを確認
    re_models = fr.models_from_drp(io.BytesIO(out))
    if len(re_models) != len(fr.models_from_drp(src)):
        raise SystemExit("検証失敗：出力のタイムライン数が変わった（出力は作らない）")
    return out, log


def rewrite_drp(src, dst, sets, timeline=None, raw_patch=None, eq_frequencies=None):
    """src は読むだけ。全変更を検証し終えてから dst を排他的作成（既存なら失敗・上書きしない）"""
    if os.path.exists(dst):
        raise SystemExit("出力先が既にある（上書きしない）：%s" % dst)
    data, log = build_drp(src, sets, timeline, raw_patch, eq_frequencies)
    n_models = len(fr.models_from_drp(src))

    def check(tmp):
        # 書き出した一時ファイルそのものを読み直し、タイムライン数が元と同じことを確認してから改名する
        if len(fr.models_from_drp(tmp)) != n_models:
            raise SystemExit("検証失敗：書き出したファイルを読み直せない（出力は作らない）")

    try:
        write_new_file(dst, data, check)
    except FileExistsError:
        raise SystemExit("出力先が既にある（上書きしない）：%s" % dst)
    return log


def _int(s):
    return int(s, 0)


def main(argv=None, prog=None):
    fr.configure_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, prog=prog)
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?")
    ap.add_argument("--set", action="append", default=[], help="名前:項目番号=値")
    ap.add_argument('--eq-freq', action='append', default=[], metavar='NAME:BAND=HZ',
                    help='Set EQ frequency in integer Hz; automatically synchronize knob and range (band 1..6)')
    ap.add_argument('--verify-eq', action='store_true',
                    help='Read-only: compare src/re-export with --eq-freq requests; exit 1 on mismatch; no dst')
    ap.add_argument("--dump-item", type=_int, action="append", default=[])
    ap.add_argument("--timeline", help="書き込むタイムライン名（対象が複数あるときは必須）")
    a = ap.parse_args(argv)
    if a.dump_item:
        for mdl in fr.load_models(a.src):
            if a.timeline and mdl["timeline"] != a.timeline:
                continue
            for tab in fr.channel_tables(mdl["model"]):
                for it in a.dump_item:
                    print(mdl["timeline"], tab["names"][:6], "0x%x" % it, tab["items"].get(it, "なし")[:6] if tab["items"].get(it) else "なし")
        return
    sets = []
    for s in a.set:
        nm, rest = s.rsplit(":", 1)
        it, v = rest.split("=")
        sets.append((nm, _int(it), _int(v)))
    frequencies = []
    for specification in a.eq_freq:
        try:
            name, rest = specification.rsplit(':', 1)
            band, hz = rest.split('=')
            frequencies.append((name, int(band), hz))
        except (ValueError, TypeError):
            ap.error('--eq-freq expects NAME:BAND=HZ')
    if a.verify_eq:
        if a.dst or a.set or not frequencies:
            ap.error('--verify-eq requires --eq-freq and no dst/--set')
        try:
            mismatches = verify_eq_frequencies(a.src, frequencies, a.timeline)
        except ValueError as error:
            ap.error(str(error))
        for mismatch in mismatches:
            print('EQ mismatch: %s' % mismatch)
        if not mismatches:
            print('EQ Hz verified: %d request(s)' % len(frequencies))
        return 1 if mismatches else 0
    if not a.dst:
        ap.error("出力先 OUT.drp が必要")
    log = rewrite_drp(a.src, a.dst, sets, a.timeline, eq_frequencies=frequencies)
    if frequencies:
        print('EQ Hz converted. Resolve may normalize values on import; re-export and run --verify-eq. '
              'Known Free 19.1.3 case: band5 1399 Hz becomes 1392 Hz even from a GUI-written DRP.', file=sys.stderr)
    for nm, it, v, cols in log:
        print("書込 %s 0x%x = %d（列%s）" % (nm, it, v, cols))


if __name__ == "__main__":
    main()
