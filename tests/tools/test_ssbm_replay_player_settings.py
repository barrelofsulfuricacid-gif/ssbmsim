"""Recorded human-slot settings must reach native fighter initialization."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_ssbm_endpoint_cache import full, recording


class ReplayPlayerSettingsTests(unittest.TestCase):
    def test_cpu_levels_follow_active_port_order(self):
        replay = recording()
        players = full.active_players(replay['settings'])
        players[0]['cpuLevel'] = 2
        players[1]['cpuLevel'] = 9
        with patch.object(full.subprocess, 'run', return_value=SimpleNamespace(stdout='')) as run:
            full.run_native(replay, replay['settings'], players, Path('/runner'), Path('/pack'))
        args = run.call_args.args[0]
        self.assertEqual(args[args.index('--ports') + 1], '1,3')
        self.assertEqual(args[args.index('--cpu-levels') + 1], '2,9')

    def test_missing_or_invalid_cpu_levels_fail_closed(self):
        for value in (None, -1, 10, True, 1.5):
            replay = recording()
            full.active_players(replay['settings'])[0]['cpuLevel'] = value
            with self.subTest(value=value), self.assertRaisesRegex(full.ReplayError, 'CPU level'):
                full.validate_replay(replay)

    def test_recorded_levels_zero_through_nine_are_preserved(self):
        for value in range(10):
            replay = recording()
            for player in full.active_players(replay['settings']):
                player['cpuLevel'] = value
            _, players = full.validate_replay(replay)
            self.assertEqual([p['cpuLevel'] for p in players], [value, value])


if __name__ == '__main__':
    unittest.main()
