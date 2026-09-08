"""Prepared screens retain inputs and endpoint proof without intermediate state."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import ssbm_native_full_match as full


def recording():
    pre = dict(physicalButtons=0x140, joystickX=-0.0, joystickY=0.625,
               cStickX=-1.0, cStickY=0.0, physicalLTrigger=0.25,
               physicalRTrigger=1.0, rawJoystickX=-128, rawJoystickY=127,
               rawCStickX=-1, rawCStickY=1)
    post = dict(actionStateId=14, positionX=1.0, positionY=0.0,
                facingDirection=1.0, percent=0.0, shieldSize=60.0,
                selfAirX=0.0, selfGroundX=0.0, selfY=0.0,
                selfAttackX=0.0, selfAttackY=0.0, hitlagRemaining=0.0,
                actionStateCounter=2.0, lastGroundId=0, stocksRemaining=4,
                jumpsRemaining=2, isAirborne=False)
    frame = dict(startSeed=0xffffffff,
                 players=[None, dict(pre=pre, post=post), None, dict(pre=pre, post=post)],
                 followers=[None, dict(pre=pre, post=post), None, None])
    return dict(schema=2, settings=dict(nativeReplayMods=dict(schema=1, fdSceneMode=0), players=[
        dict(playerIndex=p, type=0, characterId=c, characterColor=0,
             startStocks=4, controllerFix='UCF', cpuLevel=1) for p,c in ((3,18),(1,14))],
        isPAL=False, isTeams=False, timerType=2, startingTimerSeconds=480,
        itemSpawnBehavior=255, enabledItems=0, stageId=31, randomSeed=123),
        inputProvenance={k:True for k in ('exactRawMainX','exactRawMainY','exactRawCX','exactRawCY')},
        gameEnd={'gameEndMethod':2},
        frames=[dict(copy.deepcopy(frame), frame=f) for f in (-123,-122)])


class EndpointCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.replay = self.root/'test.slp'
        self.replay.write_bytes(b'recorded replay identity')
        self.prefix = self.root/'parser'
        package = self.prefix/'node_modules/@slippi/slippi-js'
        (package/'dist').mkdir(parents=True)
        (package/'package.json').write_text('{"version":"fixture"}')
        self.parser_code = package/'dist/parser.cjs'
        self.parser_code.write_text('fixture parser')
        self.cache = self.root/'cache'
        self.cache_path = full.extraction_cache_path(self.cache, full.sha256(self.replay), 'final-state')
        self.source = recording()

    def prepare(self):
        return full.prepare_endpoint(self.replay, self.prefix, self.cache, 'unused')

    def test_cold_and_warm_inputs_endpoint_followers_ports_and_signed_zero(self):
        with patch.object(full, 'extract_replay', return_value=self.source) as extract:
            cold = self.prepare()
            extract.assert_called_once_with(self.replay, self.prefix, None, 'unused', endpoint_inputs=True)
        with patch.object(full, 'extract_replay', side_effect=AssertionError('must use prepared cache')):
            warm = self.prepare()
        self.assertEqual(cold, warm)
        settings, players = full.validate_replay(self.source)
        self.assertEqual(warm['input_csv'], full.native_input(self.source, players))
        self.assertEqual([p['playerIndex'] for p in players], [1,3])
        self.assertEqual(warm['source_frames'], 2)
        self.assertEqual(warm['replay']['frames'], self.source['frames'][-1:])
        self.assertIn('-128,127,-1,1', warm['input_csv'])
        self.assertEqual(struct.pack('<f', warm['replay']['frames'][0]['players'][1]['pre']['joystickX']), b'\0\0\0\x80')
        self.assertNotEqual(self.cache_path, full.extraction_cache_path(self.cache, full.sha256(self.replay), 'all-frames'))

    def test_changed_parser_or_preparer_invalidates_prepared_inputs(self):
        with patch.object(full, 'extract_replay', return_value=self.source) as extract:
            self.prepare()
            self.parser_code.write_text('new parser')
            self.prepare()
            self.assertEqual(extract.call_count, 2)
            envelope = json.loads(self.cache_path.read_text())
            envelope['preparer_sha256'] = 'old-validator'
            self.cache_path.write_text(json.dumps(envelope))
            self.prepare()
            self.assertEqual(extract.call_count, 3)

    def test_corrupt_current_cache_is_not_silently_used_or_rebuilt(self):
        with patch.object(full, 'extract_replay', return_value=self.source):
            self.prepare()
        envelope = json.loads(self.cache_path.read_text())
        envelope['payload']['input_csv'] = envelope['payload']['input_csv'].replace('-128', '0')
        self.cache_path.write_text(json.dumps(envelope))
        with patch.object(full, 'extract_replay', side_effect=AssertionError('corruption must fail closed')):
            with self.assertRaisesRegex(full.ReplayError, 'checksum'):
                self.prepare()

    def test_missing_physical_input_or_frame_cannot_create_cache(self):
        for kind in ('raw', 'gap', 'follower', 'end'):
            with self.subTest(kind=kind):
                source = recording()
                if kind == 'raw': del source['frames'][0]['players'][1]['pre']['rawCStickY']
                if kind == 'gap': source['frames'][1]['frame'] += 1
                if kind == 'follower': del source['frames'][0]['followers']
                if kind == 'end': del source['gameEnd']
                with patch.object(full, 'extract_replay', return_value=source):
                    with self.assertRaises(full.ReplayError): self.prepare()
                self.assertFalse(self.cache_path.exists())

    def test_existing_full_cache_can_seed_without_overwriting_it(self):
        self.cache.mkdir()
        legacy = full.extraction_cache_path(self.cache, full.sha256(self.replay), 'all-frames')
        legacy.write_text(json.dumps(dict(schema=2,replay_sha256=full.sha256(self.replay),extractor_sha256=full.extractor_identity(),replay=self.source)))
        before = legacy.read_bytes()
        prepared = self.prepare()
        self.assertEqual(legacy.read_bytes(), before)
        self.assertEqual(prepared['source_frames'], 2)

    def test_old_full_cache_is_reextracted_when_patch_projection_changes(self):
        from types import SimpleNamespace
        self.cache.mkdir()
        path = full.extraction_cache_path(self.cache, full.sha256(self.replay), 'all-frames')
        old = recording()
        del old['settings']['nativeReplayMods']
        path.write_text(json.dumps(dict(schema=2, replay_sha256=full.sha256(self.replay),
                                       replay=old)))
        result = SimpleNamespace(returncode=0, stdout=json.dumps(self.source), stderr='')
        with patch.object(full.subprocess, 'run', return_value=result) as extract:
            refreshed = full.extract_replay(self.replay, self.prefix, self.cache, 'unused')
            extract.assert_called_once()
        self.assertEqual(refreshed['settings']['nativeReplayMods'], dict(schema=1, fdSceneMode=0))
        self.assertEqual(json.loads(path.read_text())['extractor_sha256'], full.extractor_identity())

    def test_missing_or_unknown_patch_settings_fail_before_simulation(self):
        for mods in (None, {}, dict(schema=1, fdSceneMode=3), dict(schema=1, fdSceneMode=True)):
            source = recording()
            source['settings']['nativeReplayMods'] = mods
            with self.subTest(mods=mods), self.assertRaisesRegex(full.ReplayError, 'modification'):
                full.validate_replay(source)


if __name__ == '__main__': unittest.main()
