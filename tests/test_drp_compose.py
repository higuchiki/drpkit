"""drp_compose tests. Synthetic audio and anonymized fixtures only; no Resolve process needed.

tests/compose/
  template-synthetic-01.drp   4-track template (Track 1-4), mixer with EQ/Dynamics/plugins
  examples/                   cut tables + generated sine FLACs; the composed .drp files are built in setUpClass
  formats/                    28 Resolve 21.1.1 exports, one per audio format (WAV16/24/32f, FLAC16/24, AAC, MP3
                              x 44.1/48 kHz x mono/stereo), their audio, and what Resolve reported for each
  clipfx/                     two exports whose clips carry Voice Isolation / Dialogue Leveler
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drpkit import compose as c
from drpkit import reader as fr
import hashlib
import json
import re
import struct
import subprocess
import tempfile
import shutil
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
COMPOSE=ROOT/'tests'/'compose'
EXAMPLES=COMPOSE/'examples'
FIXTURE=COMPOSE/'template-synthetic-01.drp'


def contents(p):
    with zipfile.ZipFile(p) as z:return {n:z.read(n) for n in z.namelist()}


class ComposeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work=Path(tempfile.mkdtemp(prefix='drpkit-compose-'))
        cls.audio={i:EXAMPLES/'audio'/('tone-%02d.flac'%i) for i in range(1,5)}
        cls.table=json.loads((EXAMPLES/'four-tracks-01.json').read_text())
        cls.original=hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        # The three example outputs are composed here (not shipped), so they point at this checkout's audio.
        cls.generated={}
        for name in ['simple-01','four-tracks-01','crossfade-01']:
            cls.generated[name]=cls.work/(name+'.drp')
            c.compose(FIXTURE,cls.generated[name],cls.audio,json.loads((EXAMPLES/(name+'.json')).read_text()))

    @classmethod
    def tearDownClass(cls):shutil.rmtree(cls.work, ignore_errors=True)

    def output(self):return self.work/(c.uid()+'.drp')

    def test_round_trip_reader_cli_all_three(self):
        for name in ['simple-01','four-tracks-01','crossfade-01']:
            with self.subTest(name=name):
                expected=c.normalize(json.loads((EXAMPLES/(name+'.json')).read_text()),self.audio)
                raw=subprocess.check_output([sys.executable,str(ROOT/'fairlight_reader.py'),str(self.generated[name]),'--edits','--json'])
                result=json.loads(raw)[0]
                clips=[r for r in result['items'] if r['kind']=='AudioClip']
                self.assertEqual(len(clips),len(expected))
                for e,r in zip(expected,clips):
                    self.assertEqual(r['track'],'Track %d'%e['track'])
                    for a,b in [('start','timeline_start'),('src_in','source_in'),('src_out','source_out'),('fade_in','fade_in'),('fade_out','fade_out'),('color','color')]:
                        self.assertEqual(r[a],e[b],(name,a))
                transitions=[r for r in result['items'] if r['kind']=='Transition']
                exp=[e for e in expected if e['crossfade']]
                self.assertEqual(len(exp),len(transitions))
                for e,r in zip(exp,transitions):
                    self.assertEqual(r['start'],e['timeline_start']-e['crossfade']/2)
                    self.assertEqual(r['duration'],e['crossfade'])
                    self.assertEqual(r['transition'],'Cross Fade 0DB')

    def test_subtraction_mixer_and_archive(self):
        before=contents(FIXTURE)
        model=fr.load_models(str(FIXTURE))[0]['model']
        for name in ['simple-01','four-tracks-01','crossfade-01']:
            after=contents(self.generated[name])
            self.assertEqual(before.keys(),after.keys())
            self.assertEqual(model,fr.load_models(str(self.generated[name]))[0]['model'])
            c.verify_preservation(before,after)
            self.assertEqual(before['Gallery.xml'],after['Gallery.xml'])
        self.assertEqual(self.original,hashlib.sha256(FIXTURE.read_bytes()).hexdigest())

    def test_media_metadata_and_ids(self):
        after=contents(self.generated['four-tracks-01'])
        allids=[]
        for n,b in after.items():
            s=b.decode();allids+=re.findall('DbId="([^"]+)"',s)
            if not n.endswith('MpFolder.xml'):continue
            for m in c.blocks(s,'Sm2MpAudioClip'):
                b=m[0];meta=fr.parse_fieldsblob(bytes.fromhex(c.get(b,'TracksBA'))[23:])
                self.assertEqual((meta['SampleRate'],meta['NumChannels'],meta['Duration']),(48000,1,960000))
                fields={f:v for f,w,v in fr._pb(c.unpack_blob(c.get(b,'Clip')))}
                path=Path(fields[1].decode())/fields[2].decode()
                self.assertTrue(path.is_file())
                self.assertEqual(c.probe(path)['samples'],meta['Duration'])
                outer=fr._pb(c.unpack_blob(c.get(b,'FieldsBlob')))
                nested=fr._pb(next(v for f,w,v in outer if f==1))
                mp=next(v for f,w,v in nested if f==5)
                ext=fr.parse_fieldsblob(mp[23:])['MediaExtents']
                self.assertEqual(struct.unpack('<dd',ext),(0,20))
            for m in c.blocks(s,'Sm2Sequence'):
                self.assertEqual(struct.unpack('<dd',bytes.fromhex(c.get(m[0],'MediaExtents'))),(3600,7))
        self.assertEqual(len(allids),len(set(allids)))

    def reject(self,table,media=None):
        dest=self.output()
        with self.assertRaises((ValueError,KeyError,FileNotFoundError)):
            c.compose(FIXTURE,dest,media or self.audio,table)
        self.assertFalse(dest.exists())

    def test_invalid_cuts_no_output(self):
        base={'track':1,'source_in':24,'source_out':72,'timeline_start':86400}
        for patch in [{'source_in':73},{'source_out':9999},{'source_in':-1},{'timeline_start':1.5}, {'fade_in':49},{'track':5},{'color':'unknown'},{'crossfade':12}, {'source_out':'NaN'}, {'extra':1}]:
            with self.subTest(patch=patch):self.reject({'units':'frames','cuts':[dict(base,**patch)]})
        self.reject({'units':'seconds','cuts':[base]})
        self.reject({'units':'frames','cuts':[base,dict(base,timeline_start=86401)]})

    def test_crossfade_handles_and_odd_frames(self):
        base={'track':1,'source_in':24,'source_out':72,'timeline_start':86400}
        second={'track':1,'source_in':96,'source_out':144,'timeline_start':86448,'crossfade':24}
        for patch in [{'source_in':0,'source_out':48},{'crossfade':23},{'timeline_start':86449},{'fade_in':1}]:
            self.reject({'units':'frames','cuts':[base,dict(second,**patch)]})
        self.reject({'units':'frames','cuts':[dict(base,source_in=432,source_out=480),second]})

    def test_exclusive_output(self):
        dst=self.output();dst.write_bytes(b'KEEP')
        with self.assertRaises(FileExistsError):c.compose(FIXTURE,dst,self.audio,self.table)
        self.assertEqual(dst.read_bytes(),b'KEEP')

    def compose_tampered(self, tag, value_of, table=None, keep_clip_fx=False):
        """Compose with one clip field altered after it was set; verification must refuse and leave nothing."""
        folder=Path(tempfile.mkdtemp(dir=self.work))
        dest=folder/'out.drp'
        real=c.put
        def put(text, t, value):
            if t==tag:
                value=value_of(value)
            return real(text, t, value)
        c.put=put
        try:
            with self.assertRaises(ValueError) as cm:
                c.compose(FIXTURE,dest,self.audio,table or self.table,keep_clip_fx=keep_clip_fx)
        finally:
            c.put=real
        self.assertIn('cut verification', str(cm.exception))
        self.assertEqual(list(folder.iterdir()),[])

    def test_tampered_clip_is_rejected_without_output(self):
        self.compose_tampered('Duration', lambda v: 999999)
        self.compose_tampered('Duration', lambda v: v+1)
        self.compose_tampered('In', lambda v: v+1)
        self.compose_tampered('Start', lambda v: v+1)
        self.compose_tampered('MediaFilePath', lambda v: v+'.other')
        self.compose_tampered('MediaRef', lambda v: c.uid())
        self.compose_tampered('Name', lambda v: 'x'+v)
        self.compose_tampered('EffectFiltersBA', lambda v: c.fades(1, 0), keep_clip_fx=True)
    def compose_with_file_tampered(self, name, edit):
        """Alter the temporary output on disk just before verification: the check must read the file itself."""
        folder=Path(tempfile.mkdtemp(dir=self.work))
        dest=folder/'out.drp'
        real=c.verify_cuts
        def spy(path,*args):
            with zipfile.ZipFile(path) as z:
                infos=z.infolist();data={i.filename:z.read(i) for i in infos}
            seq=[n for n in data if n.startswith('SeqContainer/')][0]
            changed=edit(data[seq].decode())
            self.assertNotEqual(changed,data[seq].decode())
            data[seq]=changed.encode()
            with zipfile.ZipFile(path,'w') as z:
                for i in infos:z.writestr(i,data[i.filename])
            return real(path,*args)
        c.verify_cuts=spy
        try:
            with self.assertRaises(ValueError) as cm:
                c.compose(FIXTURE,dest,self.audio,json.loads((EXAMPLES/(name+'.json')).read_text()))
        finally:
            c.verify_cuts=real
        self.assertIn('cut verification', str(cm.exception))
        self.assertEqual(list(folder.iterdir()),[])

    def test_tampered_file_is_rejected_without_output(self):
        def clip_field(tag,value):
            return lambda x: re.sub(r'(<Sm2TiAudioClip\b.*?<%s>)[^<]*(</%s>)'%(tag,tag), lambda m: m[1]+value+m[2], x, count=1, flags=re.S)
        self.compose_with_file_tampered('simple-01', clip_field('Duration','999999'))
        self.compose_with_file_tampered('simple-01', clip_field('In','1'))
        self.compose_with_file_tampered('four-tracks-01', clip_field('MediaFilePath','/elsewhere/tone.flac'))
        self.compose_with_file_tampered('crossfade-01',
            lambda x: re.sub(r'(<Sm2TiTransition\b.*?<Duration>)\d+(</Duration>)', lambda m: m[1]+'26'+m[2], x, count=1, flags=re.S))
        self.compose_with_file_tampered('simple-01',
            lambda x: re.sub(r'<Element><Sm2TiAudioClip\b.*?</Sm2TiAudioClip></Element>', '', x, count=1, flags=re.S))

    def test_failed_write_leaves_no_file(self):
        import drpkit._atomic as atomic
        folder=Path(tempfile.mkdtemp(dir=self.work))
        dest=folder/'out.drp'
        real=atomic.os.fsync
        def boom(fd):raise OSError('disk full (simulated)')
        atomic.os.fsync=boom
        try:
            with self.assertRaises(OSError):
                c.compose(FIXTURE,dest,self.audio,self.table)
        finally:
            atomic.os.fsync=real
        self.assertEqual(list(folder.iterdir()),[])
        c.compose(FIXTURE,dest,self.audio,self.table)
        self.assertEqual([p.name for p in folder.iterdir()],['out.drp'])

    def test_missing_media_mapping(self):
        self.reject(self.table,{1:self.audio[1]})
        self.reject(self.table,dict(self.audio,**{'1':self.work/'missing.flac'}))

    def test_sample_rate_and_channel_validation(self):
        d=Path(tempfile.mkdtemp(prefix='compose-rate-', dir=self.work))
        def make(name,rate,channels):
            p=d/name
            subprocess.run(['ffmpeg','-v','error','-n','-f','lavfi','-i',f'sine=duration=12:sample_rate={rate}','-ac',str(channels),'-sample_fmt','s16',str(p)],check=True)
            return p
        mono=make('mono.flac',44100,1)
        stereo=make('stereo.flac',48000,2)
        mapping=dict(self.audio);mapping[1]=mono
        dst=self.output();c.compose(FIXTURE,dst,mapping,self.table)
        found=[]
        for n,b in contents(dst).items():
            if n.endswith('MpFolder.xml'):
                for m in c.blocks(b.decode(),'Sm2MpAudioClip'):
                    meta=fr.parse_fieldsblob(bytes.fromhex(c.get(m[0],'TracksBA'))[23:]);found.append(meta['SampleRate'])
                    if meta['SampleRate']==44100:self.assertEqual(meta['Duration'],529200)
        self.assertIn(44100,found)
        mapping[1]=stereo
        dst=self.output();c.compose(FIXTURE,dst,mapping,self.table)
        first = fr.read_edits(str(dst))[0]['items'][0]
        self.assertEqual(first['duration'], 72)

    def test_fade_serialization_matches_saved_schema(self):
        # Resolve SetFades_48_24: same bytes except volume -6 dB -> 0 dB.
        expected='0a3b087c38004a0f085f1a0b0a091100000000000000004a0f08611a0b0a091100000000000048404a0f08621a0b0a091100000000000038404a004a00'
        self.assertEqual(c.unpack_blob(c.fades(48,24)).hex(),expected)

    def test_csv_and_cli(self):
        p=self.work/'cuts.csv';p.write_text('track,source_in,source_out,timeline_start,fade_in,fade_out\n1,24,72,86400,2,3\n')
        dst=self.output()
        cmd=[sys.executable,str(ROOT/'drp_compose.py'),str(FIXTURE),str(dst),'--cuts',str(p)]
        for t,a in self.audio.items():cmd+=['--media',f'{t}={a}']
        subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
        row=fr.read_edits(str(dst))[0]['items'][0]
        self.assertEqual((row['fade_in'],row['fade_out']),(2,3))

    def test_subtraction_detects_unrelated_change(self):
        before=contents(FIXTURE);after=dict(before)
        after['Gallery.xml']+=b' '
        with self.assertRaises(ValueError):c.verify_preservation(before,after)

    def test_keep_clip_fx_all_tracks_and_chronological_prototype(self):
        source = contents(FIXTURE)
        cfg = fr.yaml.safe_load(Path(fr.MAP_PATH).read_text(encoding="utf-8"))
        # Actual Resolve exports: copy only clip FX blobs into the synthetic fixture.
        blobs = []
        for name in ('API_VI_c1_vi55-01.drp', 'API_DL_m2_g6-01.drp'):
            saved = contents(COMPOSE/'clipfx'/name)
            candidates = [c.get(m[0], 'FieldsBlob') for n, b in saved.items()
                          if n.startswith('SeqContainer/') for m in c.blocks(b.decode(), 'Sm2TiAudioClip')]
            blobs.append(next(hx for hx in candidates if fr.clip_plugins(bytes.fromhex(hx), cfg['plugins'])))
        expected = {}
        for n, b in list(source.items()):
            if not n.startswith('SeqContainer/'):continue
            text = b.decode()
            tracks = [m[0] for m in c.blocks(text, 'Sm2TiTrack') if c.get(m[0], 'Type') == '1']
            for t, track in enumerate(tracks, 1):
                clip = c.blocks(track, 'Sm2TiAudioClip')[0][0]
                clip = c.put(clip, 'FieldsBlob', blobs[(t-1) % 2])
                clip = c.put(clip, 'Start', 86400)
                clip = c.put(clip, 'EffectFiltersBA', c.fades(7, 8, -t*2, [(24, -t), (96, -t-3)]))
                later = c.put(clip, 'Start', 86500)
                later = c.put(later, 'EffectFiltersBA', c.fades(0, 0, 9))
                later = re.sub(r'DbId="[^"]+"', 'DbId="'+c.uid()+'"', later, count=1)
                # XML order deliberately differs from timeline order.
                updated = c.put(track, 'Items', '').replace('<Items></Items>', '<Items><Element>'+later+'</Element><Element>'+clip+'</Element></Items>')
                text = text.replace(track, updated, 1)
                expected[t] = blobs[(t-1) % 2]
            source[n] = text.encode()
        template = self.output()
        with zipfile.ZipFile(template, 'x') as z:
            for n, b in source.items():z.writestr(n, b)
        dst = self.output()
        report = c.compose(template, dst, self.audio, self.table, keep_clip_fx=True)
        self.assertTrue(report['preservation']['mixer_byte_identical'])
        self.assertEqual(fr.load_models(str(template)), fr.load_models(str(dst)))
        for n, b in contents(dst).items():
            if not n.startswith('SeqContainer/'):continue
            tracks = [m[0] for m in c.blocks(b.decode(), 'Sm2TiTrack') if c.get(m[0], 'Type') == '1']
            for t, track in enumerate(tracks, 1):
                clips = c.blocks(track, 'Sm2TiAudioClip')
                self.assertEqual(len(clips), 2)
                for m in clips:
                    self.assertEqual(c.get(m[0], 'FieldsBlob'), expected[t])
                    effect = fr.clip_effects(bytes.fromhex(c.get(m[0], 'EffectFiltersBA')))[0]
                    self.assertEqual(effect['params'][95], -t*2)
                    self.assertEqual(effect['keyframes'][95][0]['value'], -t)
        # Existing default remains zero dB. CLI must actually pass the new flag.
        default = self.output(); c.compose(template, default, self.audio, self.table)
        self.assertEqual(fr.read_edits(str(default))[0]['items'][0]['volume_db'], 0)
        cli = self.output()
        cmd = [sys.executable, str(ROOT/'drp_compose.py'), str(template), str(cli), '--keep-clip-fx',
               '--cuts', str(EXAMPLES/'four-tracks-01.json')]
        for t, a in self.audio.items():cmd += ['--media', f'{t}={a}']
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        self.assertEqual(fr.read_edits(str(cli))[0]['items'][0]['volume_db'], -2)

    def test_inherited_effects_overrides_and_unknown_preservation(self):
        original = c.fades(7, 8, -6, [(24, -12), (96, 0)])
        other = (1, 2, c.pbpack([(1, 0, 987), (55, 2, b'opaque FX')]))
        hx = c.pack_blob(c.pbpack(fr._pb(c.unpack_blob(original)) + [other, (77, 2, b'opaque envelope')]))
        for kfs in (None, [], [(48, -3)]):
            result = c.inherited_effects(hx, 2, 3, kfs)
            fields = fr._pb(c.unpack_blob(result))
            self.assertEqual(fields[-2:], [other, (77, 2, b'opaque envelope')])
            effect = fr.clip_effects(bytes.fromhex(result))[0]
            self.assertEqual(effect['params'], {95: -6, 97: 2, 98: 3})
            actual = [(k['frame'], k['value']) for k in effect.get('keyframes', {}).get(95, [])]
            self.assertEqual(actual, [(24, -12), (96, 0)] if kfs is None else kfs)

    def test_inherited_effects_empty_and_missing_volume(self):
        self.assertEqual(c.inherited_effects('', 2, 3), c.fades(2, 3))
        other = c.pbpack([(1, 2, c.pbpack([(1, 0, 987)]))])
        result = fr.clip_effects(bytes.fromhex(c.inherited_effects(c.pack_blob(other), 2, 3)))
        self.assertEqual([e['type'] for e in result], [987, 124])
        self.assertEqual(result[-1]['params'], {95: 0, 97: 2, 98: 3})

    def test_csv_keyframes_inherit_clear_and_override(self):
        base = dict(track=1, source_in=24, source_out=96, timeline_start=86400)
        for value, expected in [('', None), ('[]', []), ('[[48,-6]]', [(48, -6)])]:
            rows = c.normalize({'units': 'frames', 'cuts': [dict(base, volume_keyframes=value)]}, self.audio)
            self.assertEqual(rows[0]['volume_keyframes'], expected)

    def test_inherited_effects_compression_and_ambiguous_volume(self):
        payload = c.unpack_blob(c.fades(7, 8, -6))
        try:
            from compression import zstd
            compressed = zstd.compress(payload)
        except ImportError:
            import zstandard
            compressed = zstandard.ZstdCompressor().compress(payload)
        hx = (struct.pack('>II', 2, len(compressed)+1)+b'\x81'+compressed).hex()
        result = fr.clip_effects(bytes.fromhex(c.inherited_effects(hx, 2, 3)))
        self.assertEqual(result[0]['params'], {95: -6, 97: 2, 98: 3})
        with self.assertRaisesRegex(ValueError, 'multiple clip volume'):
            c.inherited_effects(c.pack_blob(payload+payload), 0, 0)
        missing = c.pack_blob(c.pbpack([(1, 2, c.pbpack([(1, 0, 124), (7, 0, 0)]))]))
        result = fr.clip_effects(bytes.fromhex(c.inherited_effects(missing, 2, 3, [(24, -3)])))[0]
        self.assertEqual(result['params'], {95: 0, 97: 2, 98: 3})
        self.assertEqual(result['keyframes'][95][0]['value'], -3)

class FormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = COMPOSE/'formats'
        cls.captures = json.loads((cls.base/'resolve_capture-01.json').read_text())
        cls.manifest = json.loads((cls.base/'audio-manifest-01.json').read_text())
        cls.data, cls.probes, cls.media, cls.clips = {}, {}, {}, {}
        cls.hashes = {}
        for item in cls.manifest:
            name = item['requested_drp']
            path = cls.base/name
            cls.hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            cls.data[name] = contents(path)
            cls.probes[name] = c.probe(cls.base/item['audio'])
            cls.media[name] = next(m[0] for n,b in cls.data[name].items() if n.endswith('MpFolder.xml')
                                   for m in c.blocks(b.decode(), 'Sm2MpAudioClip'))
            cls.clips[name] = next(m[0] for n,b in cls.data[name].items() if n.startswith('SeqContainer/')
                                   for m in c.blocks(b.decode(), 'Sm2TiAudioClip'))
        cls.work = Path(tempfile.mkdtemp(prefix='drpkit-formats-'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    @staticmethod
    def track(block):
        return fr.parse_fieldsblob(bytes.fromhex(c.get(block, 'TracksBA'))[23:])

    @staticmethod
    def info(block):
        outer = fr._pb(c.unpack_blob(c.get(block, 'FieldsBlob')))
        nested = fr._pb(next(v for f,w,v in outer if (f,w)==(1,2)))
        return fr.parse_fieldsblob(next(v for f,w,v in nested if (f,w)==(5,2))[23:])

    def test_probe_matches_28_resolve_exports(self):
        for name,p in self.probes.items():
            with self.subTest(name=name):
                captured = self.track(self.media[name])
                for key, prop in [('CodecName','codec'),('BitDepth','bit_depth'),('SampleRate','rate'),('NumChannels','channels'),('Duration','samples')]:
                    self.assertEqual(captured[key], p[prop])
                self.assertEqual(captured.get('ChannelLayout'), p['channel_layout'])
                self.assertEqual(struct.unpack('<dd', self.info(self.media[name])['MediaExtents']), (0,p['duration']))
                self.assertEqual(self.captures[name]['props']['Online Status'], 'Online')
                self.assertEqual(self.captures[name]['props']['Audio Bit Depth'], str({1:16,2:24,3:32}[p['bit_depth']]))

    def test_all_784_media_replacements_match_independent_captures(self):
        for src, template in self.media.items():
            for name,p in self.probes.items():
                with self.subTest(src=src, target=name):
                    result = c.replace_media(template, p)
                    expected = self.track(self.media[name]); actual = self.track(result)
                    expected['UniqueId'] = self.track(template)['UniqueId']
                    self.assertEqual(actual, expected)
                    expected = self.info(self.media[name]); actual = self.info(result)
                    ref = re.search(r'<BtAudioInfo DbId="([^"]+)"', template)[1]
                    expected['ChannelVecBA'] = c.channel_vector(ref, p['channels'])
                    self.assertEqual(actual, expected)
                    fields = {f:v for f,w,v in fr._pb(c.unpack_blob(c.get(result,'Clip')))}
                    target = {f:v for f,w,v in fr._pb(c.unpack_blob(c.get(self.media[name],'Clip')))}
                    for key in (5,15,16,18):self.assertEqual(fields[key],target[key])
        for name,h in self.hashes.items():
            self.assertEqual(hashlib.sha256((self.base/name).read_bytes()).hexdigest(),h)

    def test_56_compositions_preserve_mixer_and_target_channels(self):
        from unittest.mock import patch
        table = c.load_table(self.base/'cuts-01.json')
        for src in ('T_WAV16_48000_1ch-01.drp','T_FLAC16_48000_2ch-01.drp'):
            for name,p in self.probes.items():
                with self.subTest(src=src,target=name):
                    dst=self.work/(src[:-4]+'_'+name)
                    with patch.object(c, 'probe', return_value=dict(p)):
                        report=c.compose(self.base/src,dst,{1:p['path']},table,keep_clip_fx=True)
                    self.assertTrue(report['preservation']['mixer_byte_identical'])
                    self.assertEqual(fr.load_models(str(self.base/src)),fr.load_models(str(dst)))
                    target_virtual=c.get(self.clips[name],'VirtualAudioTrackBA')
                    entries=contents(dst)
                    clips=[m[0] for n,b in entries.items() if n.startswith('SeqContainer/')
                           for m in c.blocks(b.decode(),'Sm2TiAudioClip')]
                    self.assertEqual(len(clips),2)
                    for clip, row in zip(clips,table['cuts']):
                        self.assertEqual(c.get(clip,'VirtualAudioTrackBA'),target_virtual)
                        for key,col in [('Start','timeline_start'),('In','source_in')]:
                            self.assertEqual(int(c.get(clip,key)),row[col])
                        self.assertEqual(int(c.get(clip,'Duration')),72)
                        self.assertEqual(c.get(clip,'MediaFilePath'),p['path'])
                    c.verify_preservation(self.data[src],entries)

    def test_unsupported_format_rejected_without_output(self):
        p=self.work/'unsupported-01.wav'
        subprocess.run(['ffmpeg','-v','error','-n','-f','lavfi','-i','sine=duration=1:sample_rate=48000',
                        '-c:a','pcm_s32le',str(p)],check=True)
        dst=self.work/'unsupported-01.drp'
        with self.assertRaisesRegex(ValueError,'unsupported audio'):
            c.compose(self.base/'T_WAV16_48000_1ch-01.drp',dst,{1:p},c.load_table(self.base/'cuts-01.json'))
        self.assertFalse(dst.exists())

    def test_custom_channel_mapping_rejected_without_output(self):
        name='T_FLAC16_48000_2ch-01.drp'
        entries=dict(self.data[name])
        for n,b in list(entries.items()):
            if not n.startswith('SeqContainer/'):continue
            clip=self.clips[name]
            raw=bytes.fromhex(c.get(clip,'VirtualAudioTrackBA'))
            swapped=c.qpatch(raw,{'ChannelsBA':struct.pack('>IIII',2,2,0x4002,0x4001)})
            entries[n]=b.decode().replace(clip,c.put(clip,'VirtualAudioTrackBA',swapped.hex())).encode()
        template=self.work/'custom-01.drp'
        with zipfile.ZipFile(template,'x') as z:
            for n,b in entries.items():z.writestr(n,b)
        dst=self.work/'custom-result-01.drp'
        mono=self.probes['T_WAV16_48000_1ch-01.drp']['path']
        with self.assertRaisesRegex(ValueError,'default clip channel mapping'):
            c.compose(template,dst,{1:mono},c.load_table(self.base/'cuts-01.json'))
        self.assertFalse(dst.exists())

class KeyframeTest(unittest.TestCase):
    def test_fades_volume_keyframes_roundtrip(self):
        blob = bytes.fromhex(c.fades(0, 0, 0, [(96, -12.0), (48, 0.0)]))
        eff = fr.clip_effects(blob)[0]
        self.assertEqual(eff["keyframes"][95], [{"frame": 48, "value": 0.0, "flags": fr.KF_FLAGS_DEFAULT},
                                                {"frame": 96, "value": -12.0, "flags": fr.KF_FLAGS_DEFAULT}])
        self.assertNotIn("keyframes", fr.clip_effects(bytes.fromhex(c.fades(0, 0)))[0])

if __name__=='__main__':unittest.main(verbosity=2)
