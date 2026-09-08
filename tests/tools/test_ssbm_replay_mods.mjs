import assert from "node:assert/strict";
import { replayMods } from "../../tools/ssbm_replay_mods.mjs";
const nop = { type: 4, address: 0x8021aae4,
  contents: Uint8Array.from(Buffer.from("0421aae460000000", "hex")) };
assert.deepEqual(replayMods({ codes: [] }), { schema: 1, fdSceneMode: 0 });
assert.equal(replayMods({ codes: [nop] }).fdSceneMode, 1);
const preserve = { type: 0xc2, address: 0x8021aae4, contents: Buffer.from(
  "c221aae4000000063c60804d83e35f907fc3f3783d808021618cb2e87d8903a6" +
  "4e8004213c60804d93e35f9083fe002c6000000000000000", "hex") };
assert.equal(replayMods({ codes: [preserve] }).fdSceneMode, 2);
assert.throws(() => replayMods(undefined), /unverified/);
assert.throws(() => replayMods({ codes: [nop, nop] }), /Duplicate/);
assert.throws(() => replayMods({ codes: [{ ...nop, contents: Buffer.alloc(8) }] }), /Unsupported/);
console.log("ssbm-replay-mods=pass");
