#!/usr/bin/env python3
"""
Проверка политики пиннинга образов.

Правила:
  * REPLACE_WITH_PINNED_DIGEST в Dockerfile → error.
  * ':latest' в Dockerfile или compose → error.
  * Тег без @sha256: в Dockerfile → warning (error при --strict).
  * Образ без @sha256: и без ${VAR} в compose → warning.
  * COPY --from=<stage> (алиас AS) не проверяется — это внутренняя
    ссылка multi-stage сборки.

Использование:
    python scripts/check-image-pinning.py [--strict] <path>...

Exit code: 0 при только warning (без --strict); 1 при error или
при warning в --strict.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("::error::PyYAML required (pip install pyyaml)")
    sys.exit(1)


# --- Dockerfile regexes ---------------------------------------------------
# [ \t] вместо \s: \s матчит \n, из-за чего ^\s*FROM может "съесть"
# предыдущую пустую строку и указать неверный offset в сообщении.

_FROM_PREFIX = r"^[ \t]*FROM"
_FLAG = r"(?:[ \t]+--[A-Za-z0-9_-]+=[^ \t\n]+)*"

FROM_RE = re.compile(
    _FROM_PREFIX + _FLAG + r"[ \t]+(\S+)",
    re.MULTILINE | re.IGNORECASE,
)
COPY_FROM_RE = re.compile(
    r"^[ \t]*COPY[ \t]+--from=(\S+)",
    re.MULTILINE | re.IGNORECASE,
)
STAGE_RE = re.compile(
    _FROM_PREFIX + _FLAG + r"[ \t]+\S+[ \t]+AS[ \t]+(\S+)",
    re.MULTILINE | re.IGNORECASE,
)


class Report:
    def __init__(self, strict: bool):
        self.err = 0
        self.warn = 0
        self.strict = strict

    def error(self, path: Path, msg: str) -> None:
        print(f"::error file={path}::{msg}")
        self.err += 1

    def warning(self, path: Path, msg: str) -> None:
        print(f"::warning file={path}::{msg}")
        self.warn += 1

    def exit_code(self) -> int:
        if self.err:
            return 1
        if self.strict and self.warn:
            print(
                f"image-pinning: strict mode: {self.warn} warning(s) "
                f"→ error"
            )
            return 1
        return 0


def _check_image_ref(
    ref: str, path: Path, ctx: str, rep: Report
) -> None:
    if "REPLACE_WITH_PINNED_DIGEST" in ref:
        rep.error(path, f"{ctx}: placeholder in image ref: {ref}")
        return
    if ref.endswith(":latest"):
        rep.error(path, f"{ctx}: ':latest' not allowed: {ref}")
        return
    if "@sha256:" not in ref:
        rep.warning(path, f"{ctx}: image without digest: {ref}")


def _check_dockerfile(path: Path, rep: Report) -> None:
    text = path.read_text(encoding="utf-8")
    stages = set(STAGE_RE.findall(text))

    for m in FROM_RE.finditer(text):
        _check_image_ref(m.group(1), path,
                         f"FROM@L{_line(text, m.start())}", rep)

    for m in COPY_FROM_RE.finditer(text):
        src = m.group(1)
        if src in stages:
            continue
        _check_image_ref(
            src, path, f"COPY --from@L{_line(text, m.start())}", rep
        )


def _check_compose(path: Path, rep: Report) -> None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        rep.error(path, f"cannot parse YAML: {e}")
        return
    if data is None:
        # Пустой YAML/только комментарии — валидно, проверять нечего.
        return
    if not isinstance(data, dict):
        rep.error(
            path,
            f"compose top-level must be a mapping, "
            f"got {type(data).__name__}",
        )
        return
    services = data.get("services")
    if services is None:
        # Compose без services — валиден для override-файлов.
        return
    if not isinstance(services, dict):
        rep.error(path, "compose 'services' must be a mapping")
        return
    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        image = service.get("image")
        if image is None:
            continue
        if not isinstance(image, str):
            rep.error(
                path,
                f"service {service_name}: 'image' must be a string, "
                f"got {type(image).__name__}",
            )
            continue
        if "${" in image:
            rep.warning(
                path,
                f"service {service_name}: {image!r} uses env var; "
                f"ensure .env pins digest for paranoid mode",
            )
            continue
        _check_image_ref(image, path, f"service {service_name}", rep)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true",
                    help="warning'и становятся ошибками")
    ap.add_argument("paths", nargs="*", type=Path)
    ns = ap.parse_args()

    # `ns.paths` — отдельно от флага. `--strict` в списке путей не
    # появится, потому что его обработал argparse.
    if not ns.paths:
        print("usage: check-image-pinning.py [--strict] <path>...")
        return 2

    rep = Report(strict=ns.strict)
    for p in ns.paths:
        if not p.is_file():
            rep.error(p, "file not found")
            continue
        if p.suffix in (".yml", ".yaml") or p.name == "docker-compose.yml":
            _check_compose(p, rep)
        else:
            _check_dockerfile(p, rep)

    print(f"image-pinning: {rep.err} error(s), {rep.warn} warning(s)")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
