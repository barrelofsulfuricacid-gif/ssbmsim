"""Verify every stage animation callback mode on the native host ABI."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]
class StageCallbackArguments(unittest.TestCase):
    def test_all_argument_modes(self):
        d = json.loads((ROOT / "tools/host_adaptations/granime.json").read_text())
        dispatch = next(r["new"] for r in d["replacements"] if r["old"].startswith("typedef void (*Callback1)"))
        pre = "#include <stdint.h>\n#include <assert.h>\ntypedef uint32_t u32; typedef float f32; typedef int HSD_Type; typedef struct {int x;} HSD_AObj; typedef union {f32 f;u32 d;void *v;} callbackArg;\n"
        names = ["A", "AF", "AV", "AU", "AO", "AOF", "AOV", "AOU", "AOT", "AOTF", "AOTV", "AOTU"]
        pre += "enum {" + ",".join("AOBJ_ARG_"+n for n in names) + "};\n"
        pre += "static HSD_AObj a; static int o, v; static unsigned seen;\n"
        callbacks = []
        for i, name in enumerate(names):
            params = ["HSD_AObj *ap"]
            checks = ["ap == &a"]
            if "O" in name:
                params.append("void *op"); checks.append("op == &o")
            if "T" in name:
                params.append("HSD_Type kind"); checks.append("kind == 11")
            if name.endswith("F"):
                params.append("f32 value"); checks.append("value == 3.25f")
            elif name.endswith("V"):
                params.append("void *value"); checks.append("value == &v")
            elif name.endswith("U"):
                params.append("u32 value"); checks.append("value == 0xdeadbeefU")
            callbacks.append("static void cb%d(%s) {assert(%s); seen |= 1U << %d;}" % (i, ",".join(params), " && ".join(checks), i))
        calls = []
        for i, name in enumerate(names):
            setup = "arg.f = 3.25f;" if name.endswith("F") else "arg.v = &v;" if name.endswith("V") else "arg.d = 0xdeadbeefU;"
            calls.append(setup + "grAnime_801C6F50(&a,&o,11,(void*)cb%d,%d,&arg);" % (i,i))
        source = pre + dispatch + "\n".join(callbacks) + "int main(void){callbackArg arg;" + "".join(calls) + "assert(seen == 4095);return 0;}"
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/"test.c"; exe=Path(tmp)/"test"; c.write_text(source)
            subprocess.run(["cc","-O2","-fsanitize=address,undefined",str(c),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
if __name__ == "__main__": unittest.main()
