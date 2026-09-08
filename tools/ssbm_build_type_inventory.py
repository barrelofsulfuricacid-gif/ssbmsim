"""Compile native gameplay type metadata using the configured runner's exact flags.

Run under WSL. This compiles an offline debug object and never links or executes
gameplay. The production runner and its optimization flags remain unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def production_command(commands):
    target = 'CMakeFiles/ssbm_native_host_providers.dir/src/ssbm/native_compat/native_fighter_state.c.o'
    matches = []
    for line in commands.splitlines():
        words = shlex.split(line)
        if '-c' not in words or '-o' not in words:
            continue
        if words[words.index('-o') + 1] == target:
            matches.append(line)
    if len(matches) != 1:
        raise ValueError(f'expected one production fighter-state compile command; found {len(matches)}')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    commands = subprocess.check_output(['ninja', '-C', str(build), '-t', 'commands'], text=True)
    configured = production_command(commands)
    source = output / 'native_state_types.c'
    obj = output / 'native_state_types.o'
    source.write_text('''#include <melee/ft/types.h>
#include <melee/it/types.h>
#include <melee/gr/types.h>
#include <melee/cm/types.h>
#include <sysdolphin/baselib/fobj.h>
#include <sysdolphin/baselib/jobj.h>
#include <sysdolphin/baselib/gobjproc.h>
Fighter *pf_schema_fighter;
Item *pf_schema_item;
HSD_JObj *pf_schema_joint;
''')
    command = shlex.split(configured)
    filtered = []
    index = 0
    while index < len(command):
        if command[index] in ('-o', '-c', '-MT', '-MF'):
            index += 2
            continue
        if command[index] == '-MD':
            index += 1
            continue
        filtered.append(command[index])
        index += 1
    filtered += ['-O0', '-g3', '-gdwarf-4', '-fno-eliminate-unused-debug-types',
                 '-c', str(source), '-o', str(obj)]
    subprocess.run(filtered, cwd=build, check=True)
    report = dict(schema=1, configured_command=configured, inventory_command=filtered,
                  compiler_version=subprocess.check_output([filtered[0], '--version'], text=True),
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  object_sha256=hashlib.sha256(obj.read_bytes()).hexdigest(),
                  claim_boundary='offline native type metadata; no original ABI proof')
    (output / 'build-identity.json').write_text(json.dumps(report, indent=2) + '\n')
    print(obj)


if __name__ == '__main__':
    main()
