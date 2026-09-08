"""Exercise the actual SIS formatting adaptation at its native buffer boundary."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class SisFormatBounds(unittest.TestCase):
    def test_format_is_exact_or_fails_closed(self):
        adaptation = json.loads((ROOT / "tools/host_adaptations/hsd_3A64.json").read_text())
        block = next(r["new"] for r in adaptation["replacements"] if r["old"].startswith("vsnprintf("))
        source = "#include <stdio.h>\n#include <stdlib.h>\n#include <stdarg.h>\n"
        source += "static void format(const char *fmt, ...) { unsigned char buffer[128]; va_list args; va_start(args, fmt);"
        source += block
        source += "va_end(args); fputs((char*)buffer, stdout); }\nint main(int argc, char **argv) { format(\"%s\", argv[1]); return 0; }\n"
        with tempfile.TemporaryDirectory() as directory:
            c = Path(directory) / "bounds.c"
            exe = Path(directory) / "bounds"
            c.write_text(source)
            subprocess.run(["cc", "-O2", "-D_FORTIFY_SOURCE=2", "-Werror", str(c), "-o", str(exe)], check=True)
            for length in (0, 1, 63, 126, 127, 128, 129, 256):
                payload = "a" * length
                result = subprocess.run([str(exe), payload], capture_output=True)
                if length < 128:
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, payload.encode())
                else:
                    self.assertEqual(result.returncode, -6)
                    self.assertEqual(result.stdout, b"")

if __name__ == "__main__":
    unittest.main()
