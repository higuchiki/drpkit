#!/usr/bin/env python3
"""Developer tool: remove machine / user details from a Resolve .drp before committing it as a test fixture.

    python3 tools/sanitize_drp.py IN.drp OUT.drp     # OUT must not exist
    python3 tools/sanitize_drp.py --check FILE.drp ...  # exit 1 if anything private is found

What it rewrites (same byte length, so no protobuf / Qt length field changes):
  - absolute paths in the project settings blob (SM_Config: cache, gallery, capture folders)
  - the machine id stored as SysId / in Sm2MultiSysData and media-pool folder blobs
  - the Resolve user UUID (<User> in project.xml) -> a fixed public UUID

--check looks for home / volume / mount paths (macOS, Linux, Windows), any e-mail address, a machine id or user
UUID other than the neutral ones, in plain text, UTF-16 and inside hex blobs, zlib / qCompress and zstd streams,
unpacked recursively.
Compressed project settings are decompressed, rewritten and recompressed (needs Python 3.14+ or `zstandard`).
Everything else is copied byte for byte; the result is re-scanned before it is written.
"""
import argparse
import io
import os
import re
import struct
import sys
import zipfile
import zlib

PRIVATE_PATH = re.compile(rb"/(?:Users|Volumes|home|private/var)/")
SYSID_XML = re.compile(r"<(SysId|LockSysId)>([0-9A-Fa-f]{12})</\1>")
SYSID_BLOB = re.compile(rb"\x0a\x0c([0-9A-F]{12})")  # protobuf field 1, length 12: the machine id
NEUTRAL_ID = b"000000000000"
PUBLIC_USER = "00000000-0000-4000-8000-000000000000"  # fixed user UUID for published fixtures
USER_XML = re.compile(r"<(User)>([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})</\1>")


def _zstd():
    try:
        from compression import zstd
        return zstd.decompress, zstd.compress
    except ImportError:
        import zstandard
        return (lambda b: zstandard.ZstdDecompressor().decompressobj().decompress(b),
                lambda b: zstandard.ZstdCompressor().compress(b))


def neutral(n):
    base = b"/drpkit-fixture/"
    return (base + b"x" * max(0, n - len(base)))[:n]


def scrub_paths(b):
    """Overwrite every length-prefixed string that contains a private absolute path with a same-length neutral path."""
    out = bytearray(b)
    for m in PRIVATE_PATH.finditer(b):
        occ = m.start()
        for s in range(occ, max(0, occ - 4096) - 1, -1):
            for vlen in (1, 2):
                if s - vlen < 0:
                    continue
                v = b[s - vlen:s]
                if vlen == 1 and v[0] < 0x80:
                    n = v[0]
                elif vlen == 2 and v[0] >= 0x80 and v[1] < 0x80:
                    n = (v[0] & 0x7F) | (v[1] << 7)
                else:
                    continue
                if s + n >= m.end() and s + n <= len(b):
                    try:
                        b[s:s + n].decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    out[s:s + n] = neutral(n)
                    break
            else:
                continue
            break
        else:
            raise ValueError("cannot delimit private path at %d" % occ)
    return bytes(out)


def scrub_blob(raw):
    """raw blob bytes -> sanitized bytes (same container format)."""
    dec, comp = _zstd()
    b = SYSID_BLOB.sub(lambda m: b"\x0a\x0c" + NEUTRAL_ID, raw)
    # Qt byte-array wrappers [u32 version][u32 length][0x81][zstd frame] anywhere in the blob
    for k in reversed([m.start() for m in re.finditer(re.escape(b"\x81\x28\xb5\x2f\xfd"), b)]):
        if k < 8:
            continue
        ver, n = struct.unpack_from(">II", b, k - 8)
        if n != len(b) - k and k - 8 + 8 + n > len(b):
            continue
        frame = b[k + 1:k + n] if k + n <= len(b) else b[k + 1:]
        try:
            payload = dec(frame)
        except Exception:
            continue
        clean = SYSID_BLOB.sub(lambda m: b"\x0a\x0c" + NEUTRAL_ID, scrub_paths(payload))
        if clean == payload:
            continue
        newframe = comp(clean)
        delta = len(newframe) - len(frame)
        b = b[:k - 8] + struct.pack(">II", ver, n + delta) + b"\x81" + newframe + b[k + n:]
        b = _fix_outer_lengths(b, k - 8, delta)
    return b


def _fix_outer_lengths(b, inner_start, delta):
    """After resizing the byte array at inner_start, fix the enclosing QByteArray length (u32 right before it)
    and a leading [u32 2][u32 total] blob header if present."""
    if delta == 0:
        return b
    if inner_start >= 4:
        n = struct.unpack_from(">I", b, inner_start - 4)[0]
        if inner_start + n - delta <= len(b) - delta and n - delta >= 8:
            b = b[:inner_start - 4] + struct.pack(">I", n + delta) + b[inner_start:]
    if len(b) >= 8 and struct.unpack_from(">I", b, 0)[0] == 2 and struct.unpack_from(">I", b, 4)[0] == len(b) - 8 - delta:
        b = b[:4] + struct.pack(">I", len(b) - 8) + b[8:]
    return b


def scrub_xml(text):
    text = SYSID_XML.sub(lambda m: "<%s>%s</%s>" % (m[1], NEUTRAL_ID.decode(), m[1]), text)
    text = USER_XML.sub(lambda m: "<%s>%s</%s>" % (m[1], PUBLIC_USER, m[1]), text)
    def blob(m):
        raw = bytes.fromhex(m[2])
        clean = scrub_blob(raw)
        return "<%s>%s</%s>" % (m[1], clean.hex() if clean != raw else m[2], m[1])
    return re.sub(r"<(\w+)>([0-9a-fA-F]{16,})</\1>", blob, text)


# ---------------- check ----------------
# Text patterns, searched in every decoded view (latin-1, UTF-16 BE / LE) of every stream.
PATTERNS = [
    re.compile(r"/(?:Users|Volumes|home|mnt|media|root|private/var)/[^/\x00-\x1f\s<>\"]+"),  # home / volume / mount paths
    re.compile(r"(?i)(?<![A-Z])[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]"),             # Windows profile paths
    re.compile(r"CloudStorage|GoogleDrive|Dropbox|OneDrive|iCloud"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),       # any e-mail address
]
HEX_RUN = re.compile(rb"[0-9a-fA-F]{16,}")
MAX_DEPTH = 6


def _views(s):
    yield s.decode("latin-1")
    for enc in ("utf-16-be", "utf-16-le"):
        for off in (0, 1):
            yield s[off:len(s) - (len(s) - off) % 2].decode(enc, "replace")


def _zstd_frame(b):
    """Decompress the zstd frame at the start of b, ignoring whatever follows it."""
    try:
        from compression import zstd
        return zstd.ZstdDecompressor().decompress(b)
    except ImportError:
        import zstandard
        return zstandard.ZstdDecompressor().decompressobj().decompress(b)


def _unpacked(b):
    """Every stream hidden in b: hex text, zlib (also qCompress = u32 size + zlib) and zstd frames."""
    dec = _zstd_frame
    out = []
    for m in HEX_RUN.finditer(b):
        h = m.group(0)
        out.append(bytes.fromhex(h[:len(h) // 2 * 2].decode()))
    for m in re.finditer(re.escape(b"\x28\xb5\x2f\xfd"), b):
        try:
            out.append(dec(b[m.start():]))
        except Exception:
            pass
    k = b.find(b"\x78")
    while k != -1 and k + 1 < len(b):
        if b[k + 1] in (0x01, 0x5E, 0x9C, 0xDA) and (b[k] * 256 + b[k + 1]) % 31 == 0:
            d = zlib.decompressobj()
            try:
                data = d.decompress(b[k:])
                if d.eof and data:
                    out.append(data)
            except zlib.error:
                pass
        k = b.find(b"\x78", k + 1)
    return out


def findings(data):
    hits = set()
    for name, raw in data.items():
        seen = set()
        todo = [(raw, 0)]
        while todo:
            s, depth = todo.pop()
            key = hash(s)
            if key in seen:
                continue
            seen.add(key)
            for text in _views(s):
                for m in SYSID_XML.finditer(text):
                    if m[2].encode() != NEUTRAL_ID:
                        hits.add((name, "SysId " + m[2]))
                for m in USER_XML.finditer(text):
                    if m[2].lower() != PUBLIC_USER:
                        hits.add((name, "user UUID " + m[2]))
                for p in PATTERNS:
                    for m in p.finditer(text):
                        hits.add((name, m.group(0)))
            for m in SYSID_BLOB.finditer(s):
                if m[1] != NEUTRAL_ID:
                    hits.add((name, "machine id " + m[1].decode()))
            if depth < MAX_DEPTH:
                todo.extend((x, depth + 1) for x in _unpacked(s))
    return sorted(hits)


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        return z.infolist(), {i.filename: z.read(i) for i in z.infolist()}, z.comment


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        bad = 0
        for f in a.files:
            h = findings(read_zip(f)[1])
            if h:
                bad += 1
                print(f, h)
        print("%d of %d files contain private details" % (bad, len(a.files)))
        return 1 if bad else 0
    if len(a.files) != 2:
        ap.error("IN.drp OUT.drp")
    src, dst = a.files
    if os.path.exists(dst):
        ap.error("output exists: " + dst)
    infos, data, comment = read_zip(src)
    out = {n: (scrub_xml(b.decode("utf-8")).encode("utf-8") if n.endswith(".xml") else b) for n, b in data.items()}
    left = findings(out)
    if left:
        ap.exit(2, "still private after sanitizing: %s\n" % left)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.comment = comment
        for i in infos:
            z.writestr(i, out[i.filename])
    with open(dst, "xb") as f:
        f.write(buf.getvalue())
    print("%s: %d entries, %d changed" % (dst, len(out), sum(out[n] != data[n] for n in out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
