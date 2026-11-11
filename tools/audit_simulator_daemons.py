"""Boot-check GoldenNugget daemon switches on a disposable CoreSimulator.

Requires inventory.json made from launchctl print system/user on that simulator.
Never targets the host launchd. Results apply only to the specified runtime.
Usage: python tools/audit_simulator_daemons.py REPORT_DIRECTORY
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

root = Path(sys.argv[1]).resolve()
config = json.loads((root / 'inventory.json').read_text())
udid = config['device']
services = config['services']
if not re.fullmatch(r'[A-F0-9-]{36}', udid):
    raise ValueError('Expected explicit simulator UUID')


def sim(*args, timeout=30):
    try:
        p = subprocess.run(['xcrun', 'simctl', *args], capture_output=True,
                           text=True, timeout=timeout)
        return {'code': p.returncode, 'out': p.stdout, 'err': p.stderr}
    except subprocess.TimeoutExpired as e:
        output = e.stdout or ''
        if isinstance(output, bytes):
            output = output.decode(errors='replace')
        return {'code': -1, 'out': output, 'err': 'timeout'}


def launch(*args):
    return sim('spawn', udid, 'launchctl', *args)


def snapshot():
    result = {}
    for label in ('com.apple.SpringBoard', 'com.apple.backboardd'):
        p = launch('print', 'user/501/' + label)
        result[label] = {'code': p['code']}
        for key in ('pid', 'runs', 'state'):
            m = re.search(r'^\s*' + key + r' = (.+)$', p['out'], re.M)
            result[label][key] = m.group(1) if m else None
    return result


def boot_check(name, keys):
    folder = root / name
    folder.mkdir(exist_ok=True)
    result = {'name': name, 'keys': keys, 'started': time.time()}
    for label in keys:
        p = launch('disable', services[label] + '/' + label)
        if p['code']:
            raise RuntimeError(f'Cannot disable {label}: {p}')
    result['shutdown'] = sim('shutdown', udid, timeout=60)
    result['boot'] = sim('boot', udid, timeout=60)
    result['bootstatus'] = sim('bootstatus', udid, '-b', timeout=150)
    (folder / 'bootstatus.txt').write_text(result['bootstatus']['out'])
    result['disabled'] = {}
    result['target_jobs'] = {}
    for domain in set(services.values()):
        p = launch('print-disabled', domain)
        (folder / (domain.replace('/', '-') + '-disabled.txt')).write_text(p['out'])
        for label in keys:
            if services[label] == domain:
                result['disabled'][label] = f'"{label}" => disabled' in p['out']
    for label in keys:
        p = launch('print', services[label] + '/' + label)
        result['target_jobs'][label] = p
    result['samples'] = [snapshot()]
    for _ in range(3):
        time.sleep(5)
        result['samples'].append(snapshot())
    result['screenshot'] = sim('io', udid, 'screenshot', str(folder / 'screen.png'))
    stable = all(
        all(s[label].get('state') == 'running' and s[label].get('pid')
            for s in result['samples']) and
        len({s[label].get('pid') for s in result['samples']}) == 1
        for label in ('com.apple.SpringBoard', 'com.apple.backboardd'))
    # A timeout/unstable shell is a candidate, never proof of a device bootloop.
    effective = all(result['disabled'].values()) and all(
        p['code'] != 0 and 'Could not find service' in p['err']
        for p in result['target_jobs'].values())
    result['verdict'] = ('booted_stable' if stable and effective and
                         result['bootstatus']['code'] == 0 else 'needs_investigation')
    result['duration'] = round(time.time() - result['started'], 1)
    (folder / 'result.json').write_text(json.dumps(result, indent=2))
    # Restore before the next independent case. The next boot applies enables.
    for label in keys:
        p = launch('enable', services[label] + '/' + label)
        if p['code']:
            raise RuntimeError(f'Cannot reenable {label}: {p}')
    return {k: result[k] for k in ('name', 'keys', 'verdict', 'duration')}


cases = [('baseline', [])]
cases += [('key-' + k, [k]) for k in sorted(services)]
for group, keys in config['groups'].items():
    present = [k for k in keys if k in services]
    if len(present) > 1:
        cases.append(('group-' + group, present))
cases.append(('combined-present', sorted(services)))
if '--repeat' in sys.argv:
    label = sys.argv[sys.argv.index('--repeat') + 1]
    cases = [('repeat-' + label, [label])]
if '--control' in sys.argv:
    cases = [('control-after-investigation', [])]
if '--final-control' in sys.argv:
    cases = [('control-final', [])]
results_path = root / 'results.json'
results = json.loads(results_path.read_text()) if results_path.exists() else []
completed = {r['name'] for r in results}
print(f'{len(cases)} cases; {len(completed)} already completed', flush=True)
for name, keys in cases:
    if name in completed:
        continue
    print(f'START {name}', flush=True)
    r = boot_check(name, keys)
    results.append(r)
    results_path.write_text(json.dumps(results, indent=2))
    print(json.dumps(r), flush=True)
    if r['verdict'] != 'booted_stable':
        print('Stopping for investigation; overrides reenabled.', flush=True)
        break
else:
    print('COMPLETE', flush=True)
