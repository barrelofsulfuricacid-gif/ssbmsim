#!/usr/bin/env python3
"""Fast unit tests for the fail-closed SSBM UCF oracle policy."""

from __future__ import annotations

from pathlib import Path
import tempfile
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ssbm_ucf_oracle as oracle  # noqa: E402


def write_config(text: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / "GALE01r2.ini"
    path.write_text(text, encoding="ascii", newline="\n")
    return directory, path


class GeckoParserTests(unittest.TestCase):
    def test_c2_row_count_skips_comments_and_parses_following_04(self) -> None:
        directory, path = write_config(
            """# generated configuration
[Gecko_Enabled]
$Example

[Gecko]
# source provenance
$Example [author]
* human-readable description
C2000100 00000002 # Example/C2.asm
11111111 22222222
# comments do not consume a C2 payload row
33333333 44444444 # second row
04000200 AABBCCDD # Example/Write.asm
"""
        )
        self.addCleanup(directory.cleanup)

        enabled, groups = oracle.parse_gecko_config(path)

        self.assertEqual(enabled, {"$Example"})
        self.assertEqual(len(groups["$Example"]), 2)
        self.assertEqual(groups["$Example"][0]["address"], 0x80000100)
        self.assertEqual(
            groups["$Example"][0]["payload"],
            bytes.fromhex("11111111222222223333333344444444"),
        )
        self.assertEqual(groups["$Example"][1]["address"], 0x80000200)
        self.assertEqual(groups["$Example"][1]["payload"], b"\xaa\xbb\xcc\xdd")

    def test_truncated_c2_fails_closed(self) -> None:
        directory, path = write_config(
            """[Gecko_Enabled]
$Example
[Gecko]
$Example
C2000100 00000002
11111111 22222222
"""
        )
        self.addCleanup(directory.cleanup)

        with self.assertRaisesRegex(RuntimeError, "truncated C2"):
            oracle.parse_gecko_config(path)


class LocalCapturePolicyTests(unittest.TestCase):
    TEMPLATE = """# template
[Gecko_Enabled]
$Optional: Extract Menu Info
{extra_codes}

[Gecko]
$Optional: Extract Menu Info [author]
C21A4FA4 00000001 # placeholder
60000000 00000000
"""

    def test_expected_groups_track_ffw_without_enabling_convenience_mods(self) -> None:
        generated = oracle._expected_local_config(
            self.TEMPLATE,
            enable_fast_forward=True,
            allow_native_capsule_spawning=False,
        )
        directory, path = write_config(generated)
        self.addCleanup(directory.cleanup)

        enabled, _ = oracle.parse_gecko_config(path)

        self.assertEqual(
            enabled,
            {
                oracle.EXTRACT_MENU_GROUP,
                oracle.BOT_INPUT_GROUP,
                oracle.FAST_FORWARD_GROUP,
            },
        )
        self.assertTrue(enabled.isdisjoint(oracle.FORBIDDEN_LOCAL_GROUPS))

    def test_native_capsule_group_is_exactly_the_authorized_five_writes(self) -> None:
        generated = oracle._expected_local_config(
            self.TEMPLATE,
            enable_fast_forward=False,
            allow_native_capsule_spawning=True,
        )
        directory, path = write_config(generated)
        self.addCleanup(directory.cleanup)
        _, groups = oracle.parse_gecko_config(path)

        hooks = oracle._enrich_exact_group(groups, oracle.NATIVE_CAPSULE_GROUP)

        self.assertEqual(len(hooks), 5)
        self.assertTrue(all(hook["code_type"] == "04" for hook in hooks))
        self.assertEqual(hooks[0]["runtime_proof_bytes"], "38600004")
        self.assertEqual(hooks[-1]["runtime_proof_bytes"], "4e800020")

    def test_authorized_group_payload_drift_fails_closed(self) -> None:
        generated = oracle._expected_local_config(
            self.TEMPLATE,
            enable_fast_forward=False,
            allow_native_capsule_spawning=True,
        ).replace("0416AE80 38600004", "0416AE80 38600005")
        directory, path = write_config(generated)
        self.addCleanup(directory.cleanup)
        _, groups = oracle.parse_gecko_config(path)

        with self.assertRaisesRegex(RuntimeError, "payload drifted"):
            oracle._enrich_exact_group(groups, oracle.NATIVE_CAPSULE_GROUP)


class FakeMemory:
    def __init__(self, values: dict[int, bytes]):
        self.values = values

    def read_bytes(self, address: int, size: int) -> bytes:
        for start, value in self.values.items():
            if start <= address and address + size <= start + len(value):
                offset = address - start
                return value[offset : offset + size]
        return b"\x00" * size


def relative_branch(address: int, target: int) -> bytes:
    displacement = (target - address) & 0x03FFFFFC
    return (0x48000000 | displacement).to_bytes(4, "big")


def runtime_provenance() -> tuple[dict[str, object], FakeMemory]:
    c2_address = 0x80001000
    c2_target = 0x80001100
    c2_proof = bytes.fromhex("1122334455667788")
    write_address = 0x80002000
    write_value = bytes.fromhex("aabbccdd")
    c2_hook = {
        "address": c2_address,
        "code_type": "C2",
        "runtime_proof_offset": 0,
        "runtime_proof_bytes": c2_proof.hex(),
    }
    write_hook = {
        "address": write_address,
        "code_type": "04",
        "runtime_proof_offset": 0,
        "runtime_proof_bytes": write_value.hex(),
    }
    provenance: dict[str, object] = {
        "schema": oracle.POLICY_SCHEMA,
        "restored_hooks": [],
        "ucf_hooks": [],
        "observer_initializers": [],
        "observer_transport_hooks": [c2_hook],
        "fast_forward_hooks": [],
        "scenario_setup_hooks": [write_hook],
        "runtime_verified": False,
    }
    memory = FakeMemory(
        {
            c2_address: relative_branch(c2_address, c2_target),
            c2_target: c2_proof,
            write_address: write_value,
        }
    )
    return provenance, memory


class RuntimeProofTests(unittest.TestCase):
    def test_c2_and_direct_write_proofs_must_both_match(self) -> None:
        provenance, memory = runtime_provenance()

        oracle.verify_ucf084_oracle(memory, provenance)

        self.assertIs(provenance["runtime_verified"], True)

    def test_c2_payload_mismatch_fails_closed(self) -> None:
        provenance, memory = runtime_provenance()
        memory.values[0x80001100] = bytes.fromhex("1122334455667789")

        with self.assertRaisesRegex(RuntimeError, "payload mismatch"):
            oracle.verify_ucf084_oracle(memory, provenance)

    def test_direct_write_mismatch_fails_closed(self) -> None:
        provenance, memory = runtime_provenance()
        memory.values[0x80002000] = bytes.fromhex("aabbccd0")

        with self.assertRaisesRegex(RuntimeError, "direct-write"):
            oracle.verify_ucf084_oracle(memory, provenance)


if __name__ == "__main__":
    unittest.main()
