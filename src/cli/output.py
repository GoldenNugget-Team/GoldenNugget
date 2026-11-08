"""One JSON document on stdout; bounded human/progress output on stderr."""
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from contextvars import ContextVar

_result = ContextVar('cli_result', default=None)
_json_mode = ContextVar('cli_json_mode', default=False)


def is_json():
    return _json_mode.get()


def set_result(data):
    _result.set(data)


class _TailWriter(io.TextIOBase):
    def __init__(self, stream):
        self.stream, self.tail = stream, ''

    def write(self, text):
        self.tail = (self.tail + text)[-16384:]
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()


def run_cli(argv, dispatch):
    separator = argv.index('--') if '--' in argv else len(argv)
    if '--json' not in argv[:separator]:
        return dispatch(argv)
    argv = [arg for arg in argv[:separator] if arg != '--json'] + argv[separator:]
    token = _result.set(None)
    mode_token = _json_mode.set(True)
    output = _TailWriter(sys.stderr)
    error = None
    code = 0
    try:
        with redirect_stdout(output), redirect_stderr(output):
            try:
                if not argv:
                    raise ValueError('A CLI command is required with --json.')
                code = dispatch(argv) or 0
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
                error = str(exc) if exc.code else None
            except KeyboardInterrupt:
                code, error = 130, 'Interrupted.'
            except Exception as exc:
                code, error = 1, str(exc)
        data = _result.get()
        if data is None:
            data = {'output': output.tail}
        if code and error is None:
            error = output.tail.strip() or 'Command failed.'
        print(json.dumps(dict(schema=1, command=argv[0] if argv else None,
                              success=code == 0, exit_code=code, data=data,
                              error=error), ensure_ascii=False))
        return code
    finally:
        _result.reset(token)
        _json_mode.reset(mode_token)
