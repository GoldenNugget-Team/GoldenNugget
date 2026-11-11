"""Validate both Mach-O slices, dependency closure and the macOS 14.4 floor."""
import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from macholib.mach_o import (
    LC_BUILD_VERSION,
    LC_LOAD_WEAK_DYLIB,
    LC_RPATH,
    LC_VERSION_MIN_MACOSX,
)
from macholib.MachO import MachO

app = Path(sys.argv[1]).resolve()
frameworks = app / 'Contents/Frameworks'
executable = app / 'Contents/MacOS'
magic = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}

@lru_cache(None)
def archs(p):
    return set(subprocess.check_output(['lipo', '-archs', str(p)], text=True).split())
files = []
for p in app.rglob('*'):
    if p.is_symlink() or not p.is_file():
        continue
    with p.open('rb') as f:
        if f.read(4) in magic:
            files.append(p)
errors = []
conditional = []
maximum = {}
minimum = 14 << 16 | 4 << 8
for p in files:
    a = archs(p)
    if not {'x86_64', 'arm64'} <= a:
        conditional.append((str(p.relative_to(app)), sorted(a)))
        if not ('cv2' in p.parts and p.suffix == '.dylib'):
            errors.append(('unexpected thin binary', str(p)))
    m = MachO(str(p))
    for header in m.headers:
        arch = {16777223: 'x86_64', 16777228: 'arm64'}.get(header.header.cputype)
        if not arch:
            errors.append(('unexpected architecture', str(p), header.header.cputype))
            continue
        for cmd, obj, data in header.commands:
            v = obj.minos if cmd.cmd == LC_BUILD_VERSION else obj.version if cmd.cmd == LC_VERSION_MIN_MACOSX else 0
            maximum[arch] = max(maximum.get(arch, 0), v)
            if v > minimum:
                errors.append(('requires macOS above 14.4', str(p.relative_to(app)), arch, v))
        rpaths = [frameworks, executable]
        for cmd, obj, data in header.commands:
            if cmd.cmd == LC_RPATH:
                raw = data.rstrip(b'\x00').decode()
                raw = raw.replace('@loader_path', str(p.parent)).replace('@executable_path', str(executable))
                if not raw.startswith('@'):
                    rpaths.append(Path(raw))
        for idx, name, lib in header.walkRelocatables():
            if header.commands[idx][0].cmd == LC_LOAD_WEAK_DYLIB:
                continue
            if lib.startswith(('/usr/lib/', '/System/Library/')):
                continue
            if lib.startswith('@loader_path/'):
                candidates = [p.parent / lib[len('@loader_path/'):]]
            elif lib.startswith('@executable_path/'):
                candidates = [executable / lib[len('@executable_path/'):]]
            elif lib.startswith('@rpath/'):
                candidates = [r / lib[len('@rpath/'):] for r in rpaths]
            else:
                candidates = [Path(lib)]
            found = next((c.resolve() for c in candidates if c.exists()), None)
            if found is None:
                errors.append((arch, str(p.relative_to(app)), lib, 'missing'))
            elif not found.is_relative_to(app):
                errors.append((arch, str(p.relative_to(app)), lib, 'outside bundle'))
            elif arch not in archs(found):
                errors.append((arch, str(p.relative_to(app)), lib, 'wrong architecture'))
report = {'mach_o_files': len(files), 'architecture_specific_codec_libraries': conditional, 'errors': errors, 'maximum_deployment_target': {a: f'{v >> 16}.{v >> 8 & 255}.{v & 255}' for a, v in maximum.items()}}
print(json.dumps(report, indent=2))
if errors:
    raise SystemExit(1)
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
