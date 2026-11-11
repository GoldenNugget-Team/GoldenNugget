"""Merge the other architecture's wheels into the host environment, fail closed."""
from __future__ import annotations

import importlib.metadata as metadata
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

from packaging.utils import canonicalize_name, parse_wheel_filename

ARCHES = {'x86_64', 'arm64'}
MAGICS = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
          b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
          b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}


def arches(path: Path) -> set[str]:
    if path.is_symlink() or not path.is_file():
        return set()
    with path.open('rb') as stream:
        if stream.read(4) not in MAGICS:
            return set()
    return set(subprocess.check_output(['lipo', '-archs', str(path)], text=True).split())


def merge_binary(target: Path, other: Path) -> None:
    target_arches, other_arches = arches(target), arches(other)
    if ARCHES <= target_arches:
        return
    if not target_arches or not ARCHES <= target_arches | other_arches:
        raise RuntimeError(f'Incompatible architecture pair: {target}: {target_arches}, '
                           f'{other}: {other_arches}')
    with tempfile.TemporaryDirectory() as directory:
        slices = []
        for arch in sorted(ARCHES):
            original, present = ((target, target_arches) if arch in target_arches
                                 else (other, other_arches))
            slice_path = Path(directory) / arch
            if len(present) == 1:
                shutil.copy2(original, slice_path)
            else:
                subprocess.run(['lipo', str(original), '-thin', arch, '-output', str(slice_path)], check=True)
            slices.append(str(slice_path))
        output = Path(directory) / 'universal'
        subprocess.run(['lipo', '-create', *slices, '-output', str(output)], check=True)
        shutil.copymode(target, output)
        shutil.copy2(output, target)


def main() -> None:
    if sys.version_info[:2] != (3, 15):
        raise RuntimeError('The macOS build requires Python 3.15')
    if not ARCHES <= arches(Path(sys.base_prefix) / 'Python'):
        raise RuntimeError('Install the universal2 python.org framework, not a thin Python')
    host_arch = platform.machine()
    if host_arch not in ARCHES:
        raise RuntimeError(f'Unsupported build architecture: {host_arch}')
    other_arch = (ARCHES - {host_arch}).pop()
    site = Path(sysconfig.get_paths()['purelib'])
    built_wheels = Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        # The universal Crypto wheel omits optional Intel-only AVX extensions.
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps', '--only-binary=:all:',
                        '--platform', 'macosx_14_4_universal2', '--dest', str(work),
                        'pycryptodome==4.0.0'], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--force-reinstall',
                        str(next(work.glob('*.whl')))], check=True)
        for dist in list(metadata.distributions()):
            native = [Path(dist.locate_file(p)) for p in dist.files or []
                      if arches(Path(dist.locate_file(p)))]
            if not any(not ARCHES <= arches(p) for p in native):
                continue
            name, version = dist.metadata['Name'], dist.version
            dest = work / canonicalize_name(name)
            dest.mkdir()
            wheel = next((p for p in built_wheels.glob('*.whl')
                          if parse_wheel_filename(p.name)[0] == canonicalize_name(name)
                          and str(parse_wheel_filename(p.name)[1]) == version), None)
            if wheel is None:
                # PySide and shiboken must come from the source builds, never PyPI.
                if canonicalize_name(name) in {'pyside6', 'shiboken6'}:
                    raise RuntimeError(f'Missing source-built {other_arch} wheel: {name}=={version}')
                subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps',
                                '--only-binary=:all:', '--platform', f'macosx_14_4_{other_arch}',
                                '--python-version', '3.15', '--implementation', 'cp',
                                '--abi', 'cp315', '--abi', 'abi3', '--abi', 'abi3t',
                                '--dest', str(dest), f'{name}=={version}'], check=True)
                wheel = next(dest.glob('*.whl'))
            unpacked = dest / 'unpacked'
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(unpacked)
            # Preserve architecture-specific codec libraries under their original names.
            for other in unpacked.rglob('*'):
                if not arches(other):
                    continue
                target = site / other.relative_to(unpacked)
                if target.exists():
                    merge_binary(target, other)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(other, target)
            for path in native:
                if path.suffix == '.so' and not ARCHES <= arches(path):
                    raise RuntimeError(f'Extension is still thin: {path}')
            print(f'Universal2: {name}=={version}', flush=True)


if __name__ == '__main__':
    main()
