"""Minecraft-style ``key=value`` settings files (server.properties, client.properties).

Lines are ``key=value``; ``#`` starts a comment line; blank lines are ignored;
spaces around keys and values are trimmed; an empty value means "use the
default". Every key and value is validated against a list of Options, and
errors name the line, so a typo never silently changes a world.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


class PropertiesError(ValueError):
    """A settings file line is malformed or has an invalid value."""


@dataclass(frozen=True)
class Option:
    key: str                      # name in the file, e.g. "server-port"
    dest: str                     # argparse destination, e.g. "port"
    kind: str                     # "int", "str", "choice" or "path"
    default: Any = None           # None: empty in the file, resolved elsewhere
    help: str = ""
    section: str = ""
    choices: tuple[str, ...] = ()
    low: int | None = None
    high: int | None = None

    def convert(self, raw: str) -> Any:
        if self.kind == "int":
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{self.key} 需要整数") from exc
            if (self.low is not None and value < self.low) or (self.high is not None and value > self.high):
                raise ValueError(f"{self.key} 需要 {self.low}–{self.high} 的整数")
            return value
        if self.kind == "choice":
            if raw not in self.choices:
                raise ValueError(f"{self.key} 必须是 {' / '.join(self.choices)}")
            return raw
        return raw


def parse_properties(text: str, options: Sequence[Option]) -> dict[str, Any]:
    """Return {key: value} for the keys with non-empty values."""
    by_key = {option.key: option for option in options}
    result: dict[str, Any] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip().lstrip("﻿")
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise PropertiesError(f"第 {number} 行应为 key=value：{stripped}")
        key, raw = (part.strip() for part in stripped.split("=", 1))
        option = by_key.get(key)
        if option is None:
            raise PropertiesError(f"第 {number} 行：未知的设置 {key}")
        if raw == "":
            continue
        try:
            result[key] = option.convert(raw)
        except ValueError as exc:
            raise PropertiesError(f"第 {number} 行：{exc}") from exc
    return result


def render_properties(options: Sequence[Option], title: str) -> str:
    """A commented default file listing every option."""
    lines = [f"# {title}",
             "# 格式：key=value。值留空表示使用默认值；命令行参数会覆盖这里的设置。"]
    section = None
    for option in options:
        if option.section != section:
            section = option.section
            lines += ["", f"# ---- {section} ----"]
        lines.append(f"# {option.help}")
        lines.append(f"{option.key}={'' if option.default is None else option.default}")
    return "\n".join(lines).lstrip("\n") + "\n"


def load_properties(path: Path, options: Sequence[Option], title: str) -> tuple[dict[str, Any], bool]:
    """Read a settings file, creating a commented default one if it is missing.

    Returns (values, created).
    """
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_properties(options, title), encoding="utf-8")
        return parse_properties(path.read_text(encoding="utf-8"), options), True
    return parse_properties(path.read_text(encoding="utf-8-sig"), options), False


def resolve(args: Any, props: dict[str, Any], options: Sequence[Option], base_dir: Path,
            skip: Sequence[str] = ()) -> dict[str, Any]:
    """Command line > properties file > option default, keyed by dest.

    Relative ``path`` values from the file are resolved against ``base_dir``.
    """
    settings = {}
    for option in options:
        if option.dest in skip:
            continue
        given = getattr(args, option.dest, None)
        if given is not None:
            settings[option.dest] = given
        elif option.key in props:
            value = props[option.key]
            if option.kind == "path":
                value = str((Path(base_dir) / value).resolve())
            settings[option.dest] = value
        else:
            settings[option.dest] = option.default
    return settings
