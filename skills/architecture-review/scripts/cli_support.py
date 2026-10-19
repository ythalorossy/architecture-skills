"""CLI plumbing for the architecture-review scripts: the Python version guard
and the one-line, file-qualified error format.

    from scripts.cli_support import UserError, require_python, run_cli

`require_python()` must be the FIRST call in a CLI module, before any import
that needs 3.11 (`tomllib`), because those imports run at module load and would
otherwise crash with an opaque ImportError instead of the install hint.
"""
import sys
import traceback


MINIMUM = (3, 11)


def require_python():
    """Exit 1 with an install hint when the interpreter is older than 3.11."""
    if sys.version_info[:2] >= MINIMUM:
        return

    found = ".".join(str(part) for part in sys.version_info[:2])
    print(
        f"ERROR: Python 3.11+ is required (found {found}).\n"
        "Install a newer Python, for example:\n"
        "  uv python install 3.12\n"
        "  brew install python          (macOS)\n"
        "  https://www.python.org/downloads/  (Windows/Linux)",
        file=sys.stderr,
    )
    sys.exit(1)


class UserError(Exception):
    """An expected, user-facing input problem.

    Raised by library code (e.g. `render_c4.render`) so the CLI can report it
    as a single line naming the file involved, with no traceback.
    """

    def __init__(self, message, path=None):
        super().__init__(message)
        self.message = message
        self.path = path

    def __str__(self):
        return f"{self.path}: {self.message}" if self.path else self.message


def run_cli(main_fn, debug=False):
    """Run `main_fn`, mapping exceptions onto the documented exit codes.

    `UserError` prints `ERROR: <path>: <message>`; anything else prints
    `ERROR: internal error in <module>:<function>: <message> (re-run with
    --debug for the traceback)`. Both exit 1. With `debug`, the traceback is
    printed as well — but the exit code is unchanged.
    """
    try:
        main_fn()
    except UserError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as ex:
        origin = _origin(main_fn)
        print(
            f"ERROR: internal error in {origin}: {ex} "
            f"(re-run with --debug for the traceback)",
            file=sys.stderr,
        )
        if debug:
            traceback.print_exc()
        sys.exit(1)


def _origin(main_fn):
    """The innermost non-stdlib frame that raised, as `module:function`.

    The deepest frame is often json/encodings/pathlib internals, which tell
    the user nothing; the innermost frame of this skill's own code does.
    """
    fallback = f"{main_fn.__module__}:{main_fn.__name__}"
    best = None
    tb = sys.exc_info()[2]
    while tb is not None:
        module = tb.tb_frame.f_globals.get("__name__", "")
        if module.split(".")[0] not in sys.stdlib_module_names:
            best = f"{module}:{tb.tb_frame.f_code.co_name}"
        tb = tb.tb_next

    return best or fallback