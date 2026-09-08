// Offline projection of explicitly supported replay patches into native settings.
// These bytes identify configuration; they are never executed by the simulator.
const FD_SCENE_HOOK = 0x8021aae4;
const FD_RNG_PRESERVING_HOOK = Buffer.from(
  "c221aae4000000063c60804d83e35f907fc3f3783d808021618cb2e87d8903a6" +
  "4e8004213c60804d93e35f9083fe002c6000000000000000", "hex");

export function replayMods(geckoList) {
  if (!geckoList || !Array.isArray(geckoList.codes)) {
    throw new Error("Replay has no explicit Gecko list; legacy patch configuration is unverified");
  }
  let fdSceneMode = 0;
  let seen = false;
  for (const code of geckoList.codes) {
    if (code.address !== FD_SCENE_HOOK) continue;
    if (seen) throw new Error("Duplicate Final Destination scene hook");
    seen = true;
    const bytes = Buffer.from(code.contents);
    if (code.type === 4 && bytes.equals(Buffer.from("0421aae460000000", "hex"))) {
      fdSceneMode = 1;
    } else if (code.type === 0xc2 && bytes.equals(FD_RNG_PRESERVING_HOOK)) {
      fdSceneMode = 2;
    } else {
      throw new Error("Unsupported Final Destination scene hook payload");
    }
  }
  return { schema: 1, fdSceneMode };
}
