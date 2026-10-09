"""Command line: `eade --help`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator, Sequence

from . import __version__
from .core.decision import Candidate, Engine
from .core.features import FeatureCatalog
from .core.rules import describe
from .io import knowledge_json


def _catalog(path: str | None) -> FeatureCatalog | None:
    if not path:
        return None
    return FeatureCatalog.from_list(json.loads(Path(path).read_text(encoding="utf-8")))


def _read_candidates(path: str) -> Iterator[Candidate]:
    stream = sys.stdin if path == "-" else open(path, encoding="utf-8")
    with stream:
        for n, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                yield Candidate(id=str(d["id"]), target_class=d["class"], features=d.get("features", {}),
                                classic_accepted=d.get("classic_accepted"), context=d.get("context", {}),
                                geometry=d.get("geometry"), meta=d.get("meta", {}))
            except (json.JSONDecodeError, KeyError) as e:
                raise SystemExit(f"{path}:{n}: invalid candidate ({e})")


def cmd_show(args: argparse.Namespace) -> int:
    v = knowledge_json.load(args.file, keep_status=True)
    catalog = _catalog(args.catalog)
    cfg = v.config
    print(f"v{v.number}  {v.label}  [{v.status.value}]")
    print(f"fingerprint  {v.fingerprint()}")
    print(f"thresholds   reject <= {cfg.reject_threshold:g} < review < {cfg.accept_threshold:g} <= accept")
    print(f"weights      classic {cfg.classic_weight:g} · rules {cfg.rules_weight:g} · similarity "
          f"{cfg.similarity_weight:g}" + "".join(f" · {r.name} {r.weight:g}" for r in cfg.ramps))
    print(f"signatures   {len(v.signatures)}   profiles {len(v.profiles)}   rules {len(v.rules)}")
    for r in v.rules:
        state = "" if r.active else "  (inactive)"
        extra = f" -> {r.result_class}" if r.result_class else ""
        print(f"\n  [{r.priority:>3}] {r.code}  {r.effect.value}{extra}  w={r.weight:g}"
              f"{'  BLOCKING' if r.blocking else ''}{state}")
        print(f"        IF {describe(r.condition, catalog)}")
        if catalog is not None:
            for p in r.check(catalog):
                print(f"        ! {p}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    v = knowledge_json.load(args.file)
    if args.number is not None:
        v = v.evolve(number=args.number)
    knowledge_json.save(v, args.output)
    print(f"imported v{v.number} ({len(v.rules)} rules, {len(v.signatures)} signatures) as a DRAFT -> {args.output}")
    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    print(knowledge_json.load(args.file, keep_status=True).fingerprint())
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    version = knowledge_json.load(args.knowledge, keep_status=True)
    catalog = _catalog(args.catalog) or FeatureCatalog()
    engine = Engine(version, catalog)
    out = sys.stdout if args.output == "-" else open(args.output, "w", encoding="utf-8")
    counts: dict[str, int] = {}
    with out:
        for result in engine.decide_all(_read_candidates(args.candidates)):
            counts[result.decision.value] = counts.get(result.decision.value, 0) + 1
            out.write(json.dumps(result.explanation(), ensure_ascii=False) + "\n")
    print(" · ".join(f"{k.lower()} {v}" for k, v in sorted(counts.items())) or "no candidates", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eade", description="EADE adaptive detection engine")
    p.add_argument("--version", action="version", version=f"eade {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    k = sub.add_parser("knowledge", help="inspect and convert knowledge versions")
    ks = k.add_subparsers(dest="action", required=True)
    s = ks.add_parser("show", help="summarise a version and its rules")
    s.add_argument("file")
    s.add_argument("--catalog", help="feature catalog JSON, to use labels and check rules")
    s.set_defaults(func=cmd_show)
    i = ks.add_parser("import", help="import a version (native or eade-version/1) as a draft")
    i.add_argument("file")
    i.add_argument("-o", "--output", required=True)
    i.add_argument("--number", type=int, help="renumber the imported draft")
    i.set_defaults(func=cmd_import)
    f = ks.add_parser("fingerprint", help="print the version fingerprint")
    f.add_argument("file")
    f.set_defaults(func=cmd_fingerprint)

    d = sub.add_parser("decide", help="decide on candidates (JSON lines in, explanations out)")
    d.add_argument("--knowledge", required=True)
    d.add_argument("--catalog")
    d.add_argument("--candidates", default="-", help="JSON lines file, '-' for stdin")
    d.add_argument("-o", "--output", default="-")
    d.set_defaults(func=cmd_decide)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as e:
        print(f"eade: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
