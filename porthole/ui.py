"""Terminal output. No dependencies, honours NO_COLOR and non-tty."""

import os
import sys

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def bold(s): return _c("1", s)
def dim(s): return _c("2", s)
def red(s): return _c("31", s)
def green(s): return _c("32", s)
def yellow(s): return _c("33", s)
def blue(s): return _c("34", s)
def cyan(s): return _c("36", s)


TIER_NAMES = {
    1: "native port",
    2: "emulated console",
    3: "interpreted",
    4: "translation layer",
}

_STATUS_COLOR = {
    "supported": green,
    "partial": yellow,
    "experimental": yellow,
    "planned": dim,
    "blocked": red,
}


def status(s: str) -> str:
    return _STATUS_COLOR.get(s, dim)(s)


def tier(n: int) -> str:
    return f"tier {n} · {TIER_NAMES.get(n, '?')}"


def field(label: str, value: str, width: int = 10) -> str:
    return f"  {dim(label.ljust(width))}{value}"


def heading(s: str) -> str:
    return f"\n{bold(s)}"


def warn(s: str) -> None:
    print(f"{yellow('warning')} {s}", file=sys.stderr)


def error(s: str) -> None:
    print(f"{red('error')} {s}", file=sys.stderr)


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"
