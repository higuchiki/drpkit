"""drpkit command line: `drpkit read|write|compose ...`."""
import sys

from . import __version__

COMMANDS = {
    "read": ("reader", "read Fairlight mixer settings or edit information (read-only)"),
    "write": ("writer", "analysis only: write raw int32 mixer values into a new copy of a .drp"),
    "compose": ("compose", "build a new .drp from a template + media + cut list"),
}

USAGE = """usage: drpkit <command> [options]

commands:
%s

`drpkit <command> -h` shows the options of a command.
Never overwrites an existing output; every change is verified before the single write.
""" % "\n".join("  %-8s %s" % (k, v[1]) for k, v in COMMANDS.items())


def main(argv=None):
    from .reader import configure_stdio
    configure_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0 if argv else 2
    if argv[0] in ("-V", "--version"):
        print("drpkit " + __version__)
        return 0
    cmd = argv.pop(0)
    if cmd not in COMMANDS:
        sys.stderr.write("drpkit: unknown command %r\n\n%s" % (cmd, USAGE))
        return 2
    import importlib
    mod = importlib.import_module("drpkit." + COMMANDS[cmd][0])
    return mod.main(argv, prog="drpkit " + cmd) or 0


if __name__ == "__main__":
    sys.exit(main())
