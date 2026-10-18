"""Offline, exclusive-output DRP composition from a template + media + cut list. See README.md ("Compose").

Analysis-grade tool: always work on copies; no warranty (see LICENSE)."""
import sys
import argparse
import csv
import io
import json
import math
from fractions import Fraction
from pathlib import Path
import re
import struct
import subprocess
import uuid
import zipfile
from xml.sax.saxutils import escape, unescape
from . import reader as fr
from ._atomic import write_new_file


def uid():
    return str(uuid.uuid4())


def blocks(text, tag):
    return list(re.finditer(r'<' + tag + r'\b[^>]*>.*?</' + tag + '>', text, re.S))


def get(text, tag):
    m = re.search(r'<' + tag + r'(?:>(.*?)</' + tag + r'>|\s*/>)', text, re.S)
    if not m:
        raise ValueError('missing tag: ' + tag)
    return unescape(m[1] or '')


def put(text, tag, value):
    pat = r'<' + tag + r'(?:>.*?</' + tag + r'>|\s*/>)'
    value = escape(str(value))
    text, n = re.subn(pat, lambda _: '<%s>%s</%s>' % (tag, value, tag), text, count=1, flags=re.S)
    if n != 1:
        raise ValueError('missing tag: ' + tag)
    return text


def vint(n):
    out = bytearray()
    while n > 127:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def pbpack(fields):
    out = b''
    for f, w, v in fields:
        out += vint(f * 8 + w)
        out += vint(v) if w == 0 else (vint(len(v)) + v if w == 2 else v)
    return out


def unpack_blob(hx):
    b = bytes.fromhex(hx)
    version, size = struct.unpack('>II', b[:8])
    if version != 2 or size != len(b) - 8:
        raise ValueError('unsupported blob header')
    if b[8] == 128:
        return b[9:]
    if b[8] == 129:
        try:
            from compression import zstd
            return zstd.decompress(b[9:])
        except ImportError:
            import zstandard
            return zstandard.ZstdDecompressor().decompressobj().decompress(b[9:])
    raise ValueError('unsupported compression')


def pack_blob(payload):
    return (struct.pack('>II', 2, len(payload) + 1) + b'\x80' + payload).hex()


def qstr(value):
    b = value.encode('utf-16-be')
    return struct.pack('>I', len(b)) + b


def qpatch(blob, updates):
    """Patch known QVariantMap values, copying every other encoded value verbatim."""
    r = fr._R(blob)
    version, n = r.u32(), r.u32()
    out = blob[:8]
    found = set()
    for _ in range(n):
        start = r.o
        key = fr._qstr(r)
        pos = r.o
        typ = struct.unpack_from('>I', blob, pos)[0]
        fr._qvar(r)
        if key not in updates:
            out += blob[start:r.o]
            continue
        found.add(key)
        val = updates[key]
        enc = {2: lambda: struct.pack('>i', val), 3: lambda: struct.pack('>I', val),
               4: lambda: struct.pack('>q', val), 6: lambda: struct.pack('>d', val),
               10: lambda: qstr(val), 12: lambda: struct.pack('>I', len(val)) + val}
        if typ not in enc:
            raise ValueError('unsupported QVariant: ' + key)
        out += blob[start:pos + 5] + enc[typ]()
    if found != set(updates) or r.o != len(blob):
        raise ValueError('unexpected QVariantMap shape')
    return out


def list_map_patch(blob, updates):
    # Observed single Qt list item: version/count/key "0"/QByteArray/map.
    if len(blob) < 23 or blob[:19] != bytes.fromhex('00000001000000010000000200300000000c00'):
        raise ValueError('only single audio stream supported')
    size = struct.unpack_from('>I', blob, 19)[0]
    if size != len(blob) - 23:
        raise ValueError('bad audio map length')
    data = qpatch(blob[23:], updates)
    return blob[:19] + struct.pack('>I', len(data)) + data


def qedit(blob, updates, remove=()):
    """Typed Qt map upsert/removal; preserve unrelated encoded values verbatim."""
    r = fr._R(blob)
    version, count = r.u32(), r.u32()
    entries = {}
    for _ in range(count):
        start = r.o
        key = fr._qstr(r)
        fr._qvar(r)
        if key in entries:
            raise ValueError('duplicate Qt key')
        entries[key] = blob[start:r.o]
    if version != 1 or r.o != len(blob):
        raise ValueError('unexpected Qt map')
    for key in remove:
        entries.pop(key, None)
    for key, (typ, value) in updates.items():
        enc = {2: lambda: struct.pack('>i', value), 3: lambda: struct.pack('>I', value),
               10: lambda: qstr(value), 12: lambda: struct.pack('>I', len(value)) + value}
        entries[key] = qstr(key) + struct.pack('>IB', typ, 0) + enc[typ]()
    return struct.pack('>II', 1, len(entries)) + b''.join(entries[k] for k in sorted(entries, reverse=True))


def qmap(updates):
    return qedit(struct.pack('>II', 1, 0), updates)


def list_map_edit(blob, updates, remove=()):
    list_map_patch(blob, {})  # Validate the observed single-stream wrapper.
    data = qedit(blob[23:], updates, remove)
    return blob[:19] + struct.pack('>I', len(data)) + data


def channel_vector(ref, channels):
    return qmap({str(i): (12, qmap(dict({'MediaRef': (10, ref)},
                    **({'ChannelIdx': (2, i)} if i else {})))) for i in range(channels)})


def virtual_audio(blob, channels):
    return qpatch(blob, {'ChannelsBA': struct.pack('>II', 2, channels) +
                         b''.join(struct.pack('>I', 0x4001+i) for i in range(channels)),
                         'AudioType': 1 if channels == 1 else 0})


def probe(path, strict=True):
    path = Path(path).resolve(strict=True)
    data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                              '-show_format', '-of', 'json', str(path)]))
    streams = data['streams']
    if len(streams) != 1 or streams[0]['codec_type'] != 'audio':
        raise ValueError('one audio stream required')
    s = streams[0]
    duration = float(s.get('duration', data['format'].get('duration', 'nan')))
    rate, channels = int(s['sample_rate']), int(s['channels'])
    if not math.isfinite(duration) or duration <= 0 or rate <= 0:
        raise ValueError('invalid audio duration/rate')
    codec, container = s['codec_name'], data['format']['format_name'].split(',')
    bits = int(s.get('bits_per_raw_sample') or s.get('bits_per_sample') or 0)
    # Resolve 21.1.1 captures T_*: CodecName / BitDepth enum / Clip field18.
    if codec in ('pcm_s16le', 'pcm_s24le', 'pcm_f32le') and 'wav' in container:
        name, depth, flags = 'Linear PCM', {'pcm_s16le': 1, 'pcm_s24le': 2, 'pcm_f32le': 3}[codec], 32768
    elif codec == 'flac' and 'flac' in container and bits in (16, 24):
        name, depth, flags = 'FLAC', {16: 1, 24: 2}[bits], 32778
    elif codec == 'aac' and 'm4a' in container and s.get('profile') == 'LC':
        name, depth, flags = 'AAC', 3, 32772
    elif codec == 'mp3' and 'mp3' in container:
        name, depth, flags = 'MP3', 3, 32776
    elif strict:
        raise ValueError('unsupported audio container/codec/bit depth')
    else:
        name, depth, flags = None, None, None
    if strict and (rate not in (44100, 48000) or channels not in (1, 2)):
        raise ValueError('replacement requires 44.1/48 kHz mono/stereo')
    time_base = Fraction(s.get('time_base', '1/%d' % rate))
    samples = round(int(s['duration_ts']) * time_base * rate) if 'duration_ts' in s else round(duration * rate)
    content_duration = samples / rate
    if codec == 'mp3':
        # Resolve stores all encoded MP3 frames, unlike ffprobe's gapless duration.
        packet_ticks = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
                        '-show_packets', '-show_entries', 'packet=duration', '-of', 'json', str(path)])
        packets = json.loads(packet_ticks)['packets']
        samples = round(sum(int(p['duration']) for p in packets) * time_base * rate)
    return dict(path=str(path), duration=samples/rate, content_duration=content_duration,
                samples=samples, rate=rate, channels=channels, codec=name, bit_depth=depth,
                clip_flags=flags, channel_layout=channels if s.get('channel_layout') in ('mono', 'stereo') else None)


def replace_media(block, info):
    tracks = bytes.fromhex(get(block, 'TracksBA'))
    old_channels = fr.parse_fieldsblob(tracks[23:])['NumChannels']
    if old_channels != info['channels'] and get(block, 'VirtualAudioTracksBA'):
        raise ValueError('channel change requires default media virtual tracks')
    tracks = list_map_patch(tracks, {'SampleRate': info['rate'], 'Duration': info['samples'],
                                   'NumChannels': info['channels'], 'CodecName': info['codec'],
                                   'BitDepth': info['bit_depth']})
    tracks = list_map_edit(tracks, {'ChannelLayout': (2, info['channel_layout'])}
                          if info['channel_layout'] is not None else {},
                          () if info['channel_layout'] is not None else ('ChannelLayout',))
    block = put(block, 'TracksBA', tracks.hex())
    p = Path(info['path'])
    vals = {1: str(p.parent).encode(), 2: p.name.encode(),
            3: __import__('time').ctime(p.stat().st_mtime).encode(), 13: p.stat().st_mtime_ns // 1000,
            5: info['codec'].encode(), 18: info['clip_flags']}
    fields = fr._pb(unpack_blob(get(block, 'Clip')))
    if not set(vals).issubset({f for f, w, v in fields}):
        raise ValueError('missing media codec/path fields')
    block = put(block, 'Clip', pack_blob(pbpack([(f, w, vals.get(f, v)) for f, w, v in fields])))
    outer = fr._pb(unpack_blob(get(block, 'FieldsBlob')))
    found = False
    new = []
    for f, w, v in outer:
        if (f, w) == (1, 2):
            nested = []
            for ff, ww, vv in fr._pb(v):
                if (ff, ww) == (5, 2):
                    ref = re.search(r'<BtAudioInfo DbId="([^"]+)"', block)[1]
                    old_map = fr.parse_fieldsblob(vv[23:])
                    updates = {'MediaExtents': (12, struct.pack('<dd', 0, info['duration'])),
                               'CodecName': (10, info['codec'])}
                    remove = []
                    if info['rate'] != 48000:
                        updates['SampleRate'] = (3, info['rate'])
                    else:
                        remove.append('SampleRate')
                    if old_channels != info['channels']:
                        if old_map['ChannelVecBA'] != channel_vector(ref, old_channels):
                            raise ValueError('channel change requires default media channel mapping')
                        updates['ChannelVecBA'] = (12, channel_vector(ref, info['channels']))
                        if info['channels'] == 2:
                            updates['Type'] = (3, 0)
                        else:
                            remove.append('Type')
                    if info['bit_depth'] != 3:
                        updates['BitDepth'] = (3, info['bit_depth'])
                    else:
                        remove.append('BitDepth')  # Default 32-bit is omitted in all captures.
                    vv = list_map_edit(vv, updates, remove)
                    found = True
                nested.append((ff, ww, vv))
            v = pbpack(nested)
        new.append((f, w, v))
    if not found:
        raise ValueError('media extents missing')
    block = put(block, 'FieldsBlob', pack_blob(pbpack(new)))
    return put(block, 'Name', p.name)


def fades(fade_in, fade_out, volume_db=0, volume_keyframes=None):
    """クリップの EffectFiltersBA（種別124）。volume_keyframes＝[(素材のフレーム番号, dB)]（クリップ先頭＝素材In。In=144 の実測で確定）。
    キーフレーム間は dB で直線補間、最初より前は最初の値・最後より後は最後の値（2026-10-18 書き出し実測）"""
    params = []
    for pid, value in ((95, volume_db), (97, fade_in), (98, fade_out)):
        scalar = pbpack([(2, 1, struct.pack('<d', value))])
        fields = [(1, 0, pid), (3, 2, pbpack([(1, 2, scalar)]))]
        if pid == 95 and volume_keyframes:
            fields.append((10, 2, fr.encode_keyframes(volume_keyframes)))
        param = pbpack(fields)
        params.append((9, 2, param))
    return pack_blob(pbpack([(1, 2, pbpack([(1, 0, 124), (7, 0, 0)] + params + [(9, 2, b''), (9, 2, b'')]))]))


def integer(value, label):
    if isinstance(value, bool):
        raise ValueError(label + ' must be integer frames')
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(label + ' must be integer frames') from None
    if not math.isfinite(x) or x != int(x) or x < 0:
        raise ValueError(label + ' must be nonnegative integer frames')
    return int(x)


def inherited_effects(hx, fade_in, fade_out, volume_keyframes=None):
    """Keep prototype effects/volume; cut-table fades and explicit keyframes win.

    Clip-internal VI/DL live in FieldsBlob, which compose copies verbatim.
    None means inherit source-coordinate volume automation; [] clears it.
    """
    if not hx:
        return fades(fade_in, fade_out, volume_keyframes=volume_keyframes)
    outer = fr._pb(unpack_blob(hx))
    fresh = fr._pb(fr._pb(unpack_blob(fades(fade_in, fade_out)))[0][2])
    defaults = {fr._pb(v)[0][2]: v for f, w, v in fresh if (f, w) == (9, 2) and v}
    seen = 0
    result = []
    for f, w, v in outer:
        if (f, w) == (1, 2):
            effect = fr._pb(v)
            if (1, 0, 124) in effect:
                seen += 1
                params, found = [], set()
                for ff, ww, vv in effect:
                    if (ff, ww) == (9, 2) and vv:
                        fields = fr._pb(vv)
                        pid = next((x for k, wire, x in fields if (k, wire) == (1, 0)), None)
                        if pid in (95, 97, 98):
                            if pid in found:
                                raise ValueError('duplicate clip volume/fade parameter')
                            found.add(pid)
                        if pid in (97, 98):
                            vv = defaults[pid]
                        elif pid in (99, 100):
                            vv = b''  # New cut-table fades are linear.
                        elif pid == 95 and volume_keyframes is not None:
                            fields = [x for x in fields if x[0] != 10]
                            if volume_keyframes:
                                fields.append((10, 2, fr.encode_keyframes(volume_keyframes)))
                            vv = pbpack(fields)
                    params.append((ff, ww, vv))
                for pid in (95, 97, 98):
                    if pid not in found:
                        value = defaults[pid]
                        if pid == 95 and volume_keyframes:
                            value += pbpack([(10, 2, fr.encode_keyframes(volume_keyframes))])
                        params.append((9, 2, value))
                v = pbpack(params)
        result.append((f, w, v))
    if seen > 1:
        raise ValueError('multiple clip volume effects unsupported')
    if not seen:
        result.extend(fr._pb(unpack_blob(fades(fade_in, fade_out, volume_keyframes=volume_keyframes))))
    return pack_blob(pbpack(result))


def load_table(path):
    path = Path(path)
    if path.suffix.lower() == '.csv':
        with path.open(newline='', encoding='utf-8-sig') as f:
            return {'units': 'frames', 'cuts': list(csv.DictReader(f))}
    return json.loads(path.read_text())


def normalize(table, tracks):
    if table.get('units') != 'frames':
        raise ValueError('units must be frames; source_out is exclusive; timeline_start is absolute')
    rows = []
    allowed = {'track', 'tracks', 'source_in', 'source_out', 'timeline_start', 'color', 'fade_in', 'fade_out', 'crossfade',
               'volume_keyframes', 'media'}
    for raw in table['cuts']:
        if set(raw) - allowed:
            raise ValueError('unknown cut columns: ' + str(set(raw) - allowed))
        if 'track' in raw and 'tracks' in raw:
            raise ValueError('use track OR tracks')
        selected = raw.get('tracks', [raw.get('track')])
        if selected == 'all':
            selected = list(tracks)
        if not isinstance(selected, list) or not selected:
            raise ValueError('tracks must be all or a list of 1-based indexes')
        for t in selected:
            t = integer(t, 'track')
            if t not in tracks:
                raise ValueError('unknown track: ' + str(t))
            row = {k: integer(raw.get(k) or 0, k) for k in ('fade_in', 'fade_out', 'crossfade')}
            row.update({k: integer(raw[k], k) for k in ('source_in', 'source_out', 'timeline_start')})
            row.update(track=t, color=raw.get('color') or None)
            # media: this cut's own audio file (e.g. several BGM files on one track); empty = the track's --media
            mfile = raw.get('media')
            if mfile is not None and not isinstance(mfile, str):
                raise ValueError('media must be a file path')
            row['media'] = mfile.strip() if mfile and mfile.strip() else None
            if row['media'] == '@template':
                raise ValueError('@template is only valid in --media')
            # volume_keyframes: [[素材フレーム, dB], ...]（素材フレーム番号。クリップ先頭＝source_in）
            kfs = raw.get('volume_keyframes')
            if isinstance(kfs, str):
                kfs = json.loads(kfs) if kfs.strip() else None
            row['volume_keyframes'] = None if kfs is None else [(integer(k[0], 'keyframe frame'), float(k[1])) for k in kfs]
            d = row['source_out'] - row['source_in']
            if d <= 0 or row['fade_in'] + row['fade_out'] > d:
                raise ValueError('empty/reversed cut or fades exceed duration')
            rows.append(row)
    if not rows:
        raise ValueError('empty cut table')
    return sorted(rows, key=lambda r: (r['track'], r['timeline_start']))


def clone_media_block(block):
    """Copy a media-pool audio item under fresh ids (item, embedded audio info, UniqueMediaPoolItemId).
    The embedded audio info id is also referenced (UTF-16) from the item's channel mapping; it is renamed there."""
    item = re.match(r'<Sm2MpAudioClip DbId="([^"]+)"', block)[1]
    infos = re.findall(r'<BtAudioInfo DbId="([^"]+)"', block)
    if len(infos) != 1:
        raise ValueError('one embedded audio stream per media item required')
    new_item, new_info = uid(), uid()
    payload = unpack_blob(get(block, 'FieldsBlob'))
    old16, new16 = infos[0].encode('utf-16-be'), new_info.encode('utf-16-be')
    if payload.count(old16) != 1 or block.count(item) != 1 or block.count(infos[0]) != 1:
        raise ValueError('unexpected media item references')
    block = put(block, 'FieldsBlob', pack_blob(payload.replace(old16, new16)))
    block = block.replace('DbId="%s"' % item, 'DbId="%s"' % new_item, 1).replace('DbId="%s"' % infos[0], 'DbId="%s"' % new_info, 1)
    block = put(block, 'UniqueMediaPoolItemId', uid())
    return new_item, block


MARKER_KEYS = {'frame', 'offset', 'color', 'name', 'note', 'duration', 'custom_data'}


def normalize_markers(table, start_frame, colors):
    """table['markers'] -> [{frame (from timeline start), color, name, note, duration, custom_data}] or None (keep template)."""
    raw = table.get('markers')
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError('markers must be a list')
    out, seen = [], set()
    for m in raw:
        if not isinstance(m, dict) or set(m) - MARKER_KEYS:
            raise ValueError('unknown marker columns: ' + str(set(m) - MARKER_KEYS if isinstance(m, dict) else m))
        if ('frame' in m) == ('offset' in m):
            raise ValueError('marker needs frame (absolute, like timeline_start) OR offset (from timeline start)')
        if 'frame' in m:
            if start_frame is None:
                raise ValueError('timeline start unknown; give marker offset instead of frame')
            off = integer(m['frame'], 'marker frame') - start_frame
            if off < 0:
                raise ValueError('marker before timeline start (%d)' % start_frame)
        else:
            off = integer(m['offset'], 'marker offset')
        name = m.get('name')
        if not isinstance(name, str) or not name:
            raise ValueError('marker name required (Resolve refuses unnamed markers)')
        color = m.get('color', 'Blue')
        if color not in colors.values():
            raise ValueError('unknown marker color: ' + str(color))
        duration = integer(m.get('duration', 1), 'marker duration')
        if duration < 1:
            raise ValueError('marker duration must be >= 1 frame')
        for k in ('note', 'custom_data'):
            if not isinstance(m.get(k, ''), str):
                raise ValueError('marker %s must be text' % k)
        if off in seen:
            raise ValueError('two markers at the same frame')
        seen.add(off)
        out.append({'frame': off, 'color': color, 'name': name, 'note': m.get('note', ''), 'duration': duration,
                    'custom_data': m.get('custom_data', '')})
    return sorted(out, key=lambda x: x['frame'])


SEQ_BLOB_RE = r'<Element>\s*<Sm2SequenceLockableBlob DbId="[^"]+">\s*<FieldsBlob>([0-9a-fA-F]*)</FieldsBlob>\s*<BlobOwner>%s</BlobOwner>.*?</Sm2SequenceLockableBlob>\s*</Element>'


def write_markers(pj, sequence_id, markers, colors):
    """Replace the timeline's marker list (protobuf field 2 of its Sm2SequenceLockableBlob); other fields stay verbatim."""
    found = list(re.finditer(SEQ_BLOB_RE % re.escape(sequence_id), pj, re.S))
    if len(found) > 1:
        raise ValueError('several lockable blobs for one timeline')
    new_list = fr.encode_markers(markers, colors)
    if found:
        m = found[0]
        payload = fr.lockable_payload(bytes.fromhex(m[1]))
        if payload is None:
            raise ValueError('unsupported timeline lockable blob')
        rest = [x for x in fr._pb(payload) if x[:2] != (2, 2)]
        if any(x[0] == 2 for x in rest):
            raise ValueError('unexpected marker list encoding')
        fields = rest + ([(2, 2, new_list)] if markers else [])
        blob = pbpack(sorted(fields, key=lambda x: x[0]))
        block = m[0][:m.start(1) - m.start()] + fr.lockable_fields_blob(blob).hex() + m[0][m.end(1) - m.start():]
        if not fields:
            block = ''
        return pj[:m.start()] + block + pj[m.end():], rest
    if not markers:
        return pj, []
    if '</LocableBlobSet>' not in pj:
        raise ValueError('project lacks LockableBlobs container')
    block = ('<Element><Sm2SequenceLockableBlob DbId="%s"><FieldsBlob>%s</FieldsBlob><BlobOwner>%s</BlobOwner>'
             '<DbSavedTime>0</DbSavedTime></Sm2SequenceLockableBlob></Element>'
             % (uid(), fr.lockable_fields_blob(pbpack([(2, 2, new_list)])).hex(), sequence_id))
    return pj.replace('</LocableBlobSet>', block + '</LocableBlobSet>', 1), []


def compose(src, dst, media, table, timeline=None, keep_clip_fx=False, media_base=None):
    """media: {1-based audio track index: path}. All audio tracks must be mapped.
    A cut row may name its own file in 'media' (relative paths resolve against media_base); each extra file
    becomes a new media-pool item cloned from the track's template item.
    All template audio Items are replaced; unselected tracks become empty.
    Every byte outside media blocks/audio Items/color ownership is preserved.
    """
    if Path(dst).exists():
        raise FileExistsError(dst)
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        original = {i.filename: z.read(i) for i in infos}
        comment = z.comment
    if len(original) != len(infos):
        raise ValueError('duplicate ZIP names')
    entries = dict(original)
    seqs = [n for n in entries if n.startswith('SeqContainer/') and n.endswith('.xml')]
    if timeline is not None:
        # タイムライン名 → Sm2Timeline の Sequence → その Sequence を持つ SeqContainer（2026-10-18 複数タイムラインのテンプレ対応）
        tl_blocks = []
        for n, data in entries.items():
            if n.endswith('MpFolder.xml'):
                for m in blocks(data.decode(), 'Sm2Timeline'):
                    if get(m[0], 'Name') == timeline:
                        tl_blocks.append(m[0])
        if len(tl_blocks) != 1:
            raise ValueError('timeline not found or not unique: ' + timeline)
        # SeqContainer の <Sequence> の ID が、そのタイムラインの記録の中に現れる（reader の edits_from_drp と同じ対応づけ）
        seqs = [n for n in seqs if re.search(r'<Sequence>([^<]+)</Sequence>', entries[n].decode())
                and re.search(r'<Sequence>([^<]+)</Sequence>', entries[n].decode())[1] in tl_blocks[0]]
    if len(seqs) != 1:
        raise ValueError('exactly one sequence container required (use --timeline for multi-timeline templates)')
    seqname = seqs[0]
    seq = entries[seqname].decode()
    ts = [m[0] for m in blocks(seq, 'Sm2TiTrack') if get(m[0], 'Type') == '1']
    media = {int(k): v for k, v in media.items()}
    if set(media) != set(range(1, len(ts) + 1)):
        raise ValueError('map every template audio track; unused tracks are cleared')
    rows = normalize(table, media)
    # media の値 '@template'＝テンプレートの素材をそのまま使う（差し替えない）。WAV 等 FLAC 以外のテンプレートでも
    # カット・フェード・キーフレーム・クロスフェードだけ組める（2026-10-18 実テンプレート試験で追加）
    keep = {t for t, p in media.items() if p == '@template'}
    probes = {}
    for t, p in media.items():
        if t in keep:
            mp = [get(m[0], 'MediaFilePath') for m in blocks(ts[t - 1], 'Sm2TiAudioClip')]
            if len(set(mp)) != 1:
                raise ValueError('@template needs one media file per track')
            probes[t] = probe(mp[0], strict=False)
        else:
            probes[t] = probe(p)
    def resolved(p):
        q = Path(p).expanduser()
        if not q.is_absolute() and media_base is not None:
            q = Path(media_base) / q
        return str(q.resolve(strict=True))
    extras = {}  # (track, absolute path) -> probe
    for row in rows:
        if row['media'] is None:
            continue
        path = resolved(row['media'])
        if path == probes[row['track']]['path']:
            row['media'] = None
            continue
        row['media'] = path
        if (row['track'], path) not in extras:
            extras[(row['track'], path)] = probe(path)
    owners = {}
    for t, info in probes.items():
        owners.setdefault(info['path'], set()).add(t)
    for t, path in extras:
        owners.setdefault(path, set()).add(t)
    if any(len(v) > 1 for v in owners.values()):
        raise ValueError('the same media file on several tracks is unsupported')
    fpses = fr.edits_from_drp(str(src), {})
    fps = next((x['fps'] for x in fpses if timeline is None or x['timeline'] == timeline), None)
    if not fps or fps <= 0:
        raise ValueError('timeline fps missing')
    prototypes, refs, removed = {}, {}, set()
    for t, track in enumerate(ts, 1):
        clips = blocks(track, 'Sm2TiAudioClip')
        if not clips:
            raise ValueError('each track requires a prototype audio clip')
        refset = {get(m[0], 'MediaRef') for m in clips}
        if len(refset) != 1:
            raise ValueError('one media-pool item per track required')
        prototypes[t] = min(clips, key=lambda m: fr._dur(get(m[0], 'Start')) or 0)[0]
        refs[t] = refset.pop()
        for m in blocks(track, 'Sm2TiAudioClip') + blocks(track, 'Sm2TiTransition'):
            removed.add(re.search('DbId="([^"]+)"', m[0])[1])
        # Reject unsupported Items instead of silently dropping them.
        kinds = re.findall(r'<(Sm2Ti\w+) DbId=', get(track, 'Items'))
        if any(k not in ('Sm2TiAudioClip', 'Sm2TiTransition') for k in kinds):
            raise ValueError('unsupported item kind')
    if len(set(refs.values())) != len(refs):
        raise ValueError('shared media across tracks is unsupported')
    touched_media, added_media = set(), set()
    for n, data in list(entries.items()):
        if not n.endswith('MpFolder.xml'):
            continue
        text = data.decode()
        for m in reversed(blocks(text, 'Sm2MpAudioClip')):
            ref = re.search('DbId="([^"]+)"', m[0])[1]
            if ref in refs.values():
                t = next(t for t, r in refs.items() if r == ref)
                template_channels = fr.parse_fieldsblob(bytes.fromhex(get(m[0], 'TracksBA'))[23:])['NumChannels']
                clones = []
                for (et, path), info in sorted(extras.items()):
                    if et != t:
                        continue
                    info['template_channels'] = template_channels
                    info['ref'], block = clone_media_block(m[0])
                    clones.append('<Element>' + replace_media(block, info) + '</Element>')
                    added_media.add(info['ref'])
                new = m[0]
                if t not in keep:
                    probes[t]['template_channels'] = template_channels
                    new = replace_media(m[0], probes[t])
                probes[t]['ref'] = ref
                close = text.index('</Element>', m.end()) + len('</Element>')
                if text[m.end():close - len('</Element>')].strip():
                    raise ValueError('unexpected media pool layout')
                text = text[:m.start()] + new + text[m.end():close] + ''.join(clones) + text[close:]
                touched_media.add(ref)
        entries[n] = text.encode()
    if any('ref' not in info for info in extras.values()):
        raise ValueError('media references missing')
    if touched_media != set(refs.values()):
        raise ValueError('media references missing')
    cfg = fr.yaml.safe_load(Path(fr.MAP_PATH).read_text(encoding='utf-8'))
    colors = {v: k for k, v in cfg['clip_colors'].items()}
    mcolors = cfg['marker_colors']
    # The output timeline starts at the first cut (Sequence MediaExtents below); absolute marker frames are relative to it.
    start_frame = min(r['timeline_start'] for r in rows)
    markers = normalize_markers(table, start_frame, mcolors)
    color_blocks = []
    # Cross Fade 0DB body taken from a Resolve 21.1.1 export; no clip UUID references in this format.
    transition = '<Sm2TiTransition DbId="{id}"><FieldsBlob>00000002000000158012120000002c789c636660642016000000da0005</FieldsBlob><PrettyType>Cross Fade 0DB</PrettyType><Name>Transition</Name><Start>{start}</Start><Duration>{duration}</Duration><LinkedItemSync/><WasDisbanded>false</WasDisbanded><MarkersBA/><UiMemento>0</UiMemento><Flags>0</Flags><PriorityIndex>0</PriorityIndex><EffectFiltersBA/><ImportExportMetadataBA/><RenderTextEnabled>true</RenderTextEnabled><RenderTextGanged>true</RenderTextGanged><RenderTextPrefixed>true</RenderTextPrefixed><AlignmentType>2</AlignmentType><Position>2</Position></Sm2TiTransition>'
    for t, track in enumerate(ts, 1):
        selected = [r for r in rows if r['track'] == t]
        items, prev = [], None
        for row in selected:
            info = extras[(t, row['media'])] if row['media'] else probes[t]
            row['_info'] = info
            a, b, start = (row[k] for k in ('source_in', 'source_out', 'timeline_start'))
            dur = b - a
            if b > min(info['duration'], info['content_duration']) * fps + 1e-6:
                raise ValueError('source_out exceeds media')
            if prev and start < prev['timeline_start'] + prev['source_out'] - prev['source_in']:
                raise ValueError('overlapping clips unsupported; use adjacent cuts + crossfade')
            cross = row['crossfade']
            if cross:
                half = cross // 2
                if cross % 2 or not prev or start != prev['timeline_start'] + prev['source_out'] - prev['source_in']:
                    raise ValueError('crossfade requires even frames and an adjacent preceding cut')
                pinfo = prev['_info']
                if half > min(a, dur, prev['source_out'] - prev['source_in']) or prev['source_out'] + half > min(pinfo['duration'], pinfo['content_duration']) * fps:
                    raise ValueError('crossfade lacks source handles or clip length')
                if row['fade_in'] or prev['fade_out'] or (prev['crossfade'] + cross) / 2 > prev['source_out'] - prev['source_in']:
                    raise ValueError('crossfade conflicts with fade or preceding transition')
                items.append(transition.format(id=uid(), start=start-half, duration=cross))
            clip = prototypes[t]
            clip = re.sub(r'DbId="[^"]+"', 'DbId="' + uid() + '"', clip, count=1)
            cid = re.search('DbId="([^"]+)"', clip)[1]
            effects = (inherited_effects(get(clip, 'EffectFiltersBA'), row['fade_in'], row['fade_out'], row['volume_keyframes'])
                       if keep_clip_fx else fades(row['fade_in'], row['fade_out'], 0, row['volume_keyframes']))
            vals = {'Start': start, 'Duration': dur, 'In': a, 'Name': Path(info['path']).name,
                    'MediaRef': info['ref'], 'MediaFilePath': info['path'], 'EffectFiltersBA': effects,
                    'MediaTimemapBA': (b'\x02' + struct.pack('>d', max(0, info['duration'] - 1 / fps))).hex(),
                    'LinkedItemSync': '', 'MarkersBA': '', 'RenderCacheBA': ''}
            for k, v in vals.items():
                clip = put(clip, k, v)
            if 'template_channels' in info and info['template_channels'] != info['channels']:
                virtual = bytes.fromhex(get(clip, 'VirtualAudioTrackBA'))
                if virtual != virtual_audio(virtual, info['template_channels']):
                    raise ValueError('channel change requires default clip channel mapping')
                clip = put(clip, 'VirtualAudioTrackBA', virtual_audio(virtual, info['channels']).hex())
            items.append(clip)
            if row['color']:
                if row['color'] not in colors:
                    raise ValueError('unknown color: ' + str(row['color']))
                hx = '0000000100000001000000100042006c006f006200440061007400610000000c000000000b00002711000000038028%02x' % colors[row['color']]
                color_blocks.append('<Element><Sm2TiItemLockableBlob DbId="%s"><FieldsBlob>%s</FieldsBlob><BlobOwner>%s</BlobOwner><DbSavedTime>0</DbSavedTime></Sm2TiItemLockableBlob></Element>' % (uid(), hx, cid))
            prev = row
        new_track = put(track, 'Items', '')
        # XML content, not escaped text.
        new_track = new_track.replace('<Items></Items>', '<Items>' + ''.join('<Element>' + it + '</Element>' for it in items) + '</Items>')
        seq = seq.replace(track, new_track, 1)
    # Sequence MediaExtents stores start seconds and span seconds, not end.
    first = min(r['timeline_start'] for r in rows)
    last = max(r['timeline_start'] + r['source_out'] - r['source_in'] for r in rows)
    sequence_id = get(ts[0], 'Sequence')
    for n in list(entries):
        if n.endswith('MpFolder.xml'):
            text = entries[n].decode()
            for m in blocks(text, 'Sm2Sequence'):
                if 'DbId="' + sequence_id + '"' in m[0].split('>', 1)[0]:
                    text = text.replace(m[0], put(m[0], 'MediaExtents', struct.pack('<dd', first / fps, (last-first) / fps).hex()), 1)
            entries[n] = text.encode()
    entries[seqname] = seq.encode()
    pj = entries['project.xml'].decode()
    for m in reversed(list(re.finditer(r'<Element>\s*<Sm2TiItemLockableBlob\b.*?</Sm2TiItemLockableBlob>\s*</Element>', pj, re.S))):
        if get(m[0], 'BlobOwner') in removed:
            pj = pj[:m.start()] + pj[m.end():]
    kept_fields = None
    if markers is not None:
        pj, kept_fields = write_markers(pj, sequence_id, markers, mcolors)
    if color_blocks:
        # Discover the enclosing vector from actual project schema.
        tag = 'LocableBlobSet'
        if '<' + tag not in pj:
            raise ValueError('project lacks LockableBlobs container')
        pj = pj.replace('</LocableBlobSet>', ''.join(color_blocks) + '</LocableBlobSet>', 1)
    entries['project.xml'] = pj.encode()
    audit = verify_preservation(original, entries, added_media, sequence_id if markers is not None else None)
    if markers is not None:
        written = [b for b in re.finditer(SEQ_BLOB_RE % re.escape(sequence_id), pj, re.S)]
        payload = fr.lockable_payload(bytes.fromhex(written[0][1])) if written else b''
        if fr.decode_markers(payload, mcolors) != markers or [x for x in fr._pb(payload) if x[:2] != (2, 2)] != kept_fields:
            raise ValueError('marker write verification failed')
    # Build entire archive first; validation errors never create an output file.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.comment = comment
        for info in infos:
            z.writestr(info, entries[info.filename])
    write_new_file(dst, buf.getvalue(), lambda tmp: verify_cuts(tmp, ts, rows, markers, keep_clip_fx, timeline, cfg))
    for row in rows:
        row.pop('_info', None)
    return {'fps': fps, 'timeline_start_frame': start_frame, 'markers': markers, 'cuts': rows, 'media': probes, 'extra_media': [dict(info, track=t) for (t, _), info in sorted(extras.items())],
            'preservation': audit}


def verify_cuts(path, tracks, rows, markers, keep_clip_fx, timeline, cfg):
    """Read the written file back with the reader and compare every audio item with the cut table.

    Checked per clip: track, order, timeline position, source In/Out, fades, volume keyframes (when the cut table
    sets them, or when clip effects are not inherited), clip color, media file and media-pool reference; per
    crossfade: position and length. Any difference raises ValueError, so no output file is created.
    """
    emap = cfg.get('clip_effects', {})
    res = fr.edits_from_drp(path, cfg.get('clip_colors', {}), cfg.get('marker_colors', {}))
    if timeline is not None:
        res = [x for x in res if x['timeline'] == timeline]
    if len(res) != 1:
        raise ValueError('cut verification: written timeline not found')
    written = [it for it in res[0]['items'] if it['track_type'] == 'audio']
    expected = []
    for t in range(1, len(tracks) + 1):
        for row in (r for r in rows if r['track'] == t):
            info = row['_info']
            a, b, start = row['source_in'], row['source_out'], row['timeline_start']
            if row['crossfade']:
                expected.append({'track_index': t, 'kind': 'Sm2TiTransition', 'start': start - row['crossfade'] // 2,
                                 'duration': row['crossfade']})
            kfs = row['volume_keyframes']
            if kfs is None and not keep_clip_fx:
                kfs = []
            expected.append({'track_index': t, 'kind': 'Sm2TiAudioClip', 'start': start, 'duration': b - a,
                             'in': float(a), 'name': Path(info['path']).name, 'media_path': info['path'],
                             'media_ref': info['ref'], 'color': row['color'] or None,
                             'fade_in': float(row['fade_in']), 'fade_out': float(row['fade_out']),
                             'keyframes': None if kfs is None else sorted((int(f), float(v)) for f, v in kfs)})
    if len(written) != len(expected):
        raise ValueError('cut verification: %d audio items written, %d expected' % (len(written), len(expected)))
    for k, (w, e) in enumerate(zip(written, expected), 1):
        got = {'track_index': w['track_index'], 'kind': w['kind'], 'start': w['start'], 'duration': w['duration']}
        if e['kind'] == 'Sm2TiAudioClip':
            fx = fr.clip_audio_fx(bytes.fromhex(w['fx']), emap) if w['fx'] else {}
            got.update({'in': w['in'], 'name': unescape(w['name'] or ''), 'media_path': unescape(w['media_path'] or ''),
                        'media_ref': w['media_ref'], 'color': w.get('color'),
                        'fade_in': fx.get('fade_in'), 'fade_out': fx.get('fade_out'),
                        'keyframes': (None if e['keyframes'] is None else
                                      sorted((p['frame'], p['value']) for p in fx.get('volume_db_keyframes', [])))})
        for key, value in e.items():
            if got.get(key) != value:
                raise ValueError('cut verification failed at audio item %d (%s): written %r, expected %r'
                                 % (k, key, got.get(key), value))
    if markers is not None:
        if (res[0]['markers'] or []) != markers:
            raise ValueError('cut verification: markers differ')


def verify_preservation(before, after, added_media=(), marker_owner=None):
    if before.keys() != after.keys():
        raise ValueError('archive membership changed')
    changed = []
    def mask(n, b):
        s = b.decode()
        if n.startswith('SeqContainer/'):
            for m in blocks(s, 'Sm2TiTrack'):
                if get(m[0], 'Type') == '1':
                    s = s.replace(m[0], put(m[0], 'Items', ''), 1)
        elif n.endswith('MpFolder.xml'):
            for ref in added_media:
                s, k = re.subn(r'<Element><Sm2MpAudioClip DbId="%s">.*?</Sm2MpAudioClip></Element>' % ref, '', s, flags=re.S)
                if k > 1:
                    raise ValueError('duplicate added media item')
            for m in blocks(s, 'Sm2MpAudioClip'):
                normalized = m[0]
                for tag in ('FieldsBlob', 'Name', 'TracksBA', 'Clip'):
                    normalized = put(normalized, tag, '')
                s = s.replace(m[0], normalized, 1)
            for m in blocks(s, 'Sm2Sequence'):
                s = s.replace(m[0], put(m[0], 'MediaExtents', ''), 1)
        elif n == 'project.xml':
            s = re.sub(r'<Element>\s*<Sm2TiItemLockableBlob\b.*?</Sm2TiItemLockableBlob>\s*</Element>', '', s, flags=re.S)
            s = re.sub(r'<LockableBlobs\s*/>', '<LockableBlobs></LockableBlobs>', s)
            if marker_owner:
                s = re.sub(SEQ_BLOB_RE % re.escape(marker_owner), '', s, flags=re.S)
        return s
    for n in before:
        if before[n] == after[n]:
            continue
        if not n.endswith('.xml') or mask(n, before[n]) != mask(n, after[n]):
            raise ValueError('unexpected change outside cuts/media/colors: ' + n)
        # Sequence FieldsBlob, including compressed FLStudioModelBA, stays literal.
        if n.endswith('MpFolder.xml'):
            a = [get(m[0], 'FieldsBlob') for m in blocks(before[n].decode(), 'Sm2Sequence')]
            b = [get(m[0], 'FieldsBlob') for m in blocks(after[n].decode(), 'Sm2Sequence')]
            if a != b:
                raise ValueError('mixer changed')
        changed.append(n)
    return {'same_entries': len(before), 'changed_entries': changed, 'mixer_byte_identical': True,
            'outside_cuts_media_colors_extents_identical': True}


def main(argv=None, prog=None):
    ap = argparse.ArgumentParser(description=__doc__, prog=prog)
    ap.add_argument('template')
    ap.add_argument('output')
    ap.add_argument('--cuts', required=True)
    ap.add_argument('--media', action='append', required=True, metavar='TRACK=FILE')
    ap.add_argument('--timeline', help='template timeline name (required when the template has several timelines)')
    ap.add_argument('--keep-clip-fx', action='store_true', help='inherit earliest clip volume, automation and effects on each audio track; cut-table fades/keyframes take precedence')
    args = ap.parse_args(argv)
    try:
        mapping = {}
        for item in args.media:
            t, p = item.split('=', 1)
            if int(t) in mapping:
                raise ValueError('duplicate media track')
            mapping[int(t)] = p
        result = compose(args.template, args.output, mapping, load_table(args.cuts), args.timeline, args.keep_clip_fx,
                         media_base=Path(args.cuts).resolve().parent)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as e:
        ap.exit(2, str(e) + '\n')


if __name__ == '__main__':
    main()
