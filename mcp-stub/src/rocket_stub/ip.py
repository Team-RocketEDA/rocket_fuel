"""Minimal project IP library: ip/manifest.yaml.

Registration grants reuse, not verification: every new block starts UNVERIFIED and the
caller cannot supply a status or evidence. Only the runner may change that later.
"""

import re
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

MANIFEST = Path("ip/manifest.yaml")
ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
DOMAINS = {"digital", "analog", "photonic"}
PORT_KINDS = {"digital", "analog", "optical", "supply", "ground"}
DIRECTIONS = {"input", "output", "inout"}
VIEW_DIRS = ("design/", "ip/")


def load(project: Path) -> list[dict]:
    path = project / MANIFEST
    if not path.exists():
        return []
    return (YAML(typ="safe").load(path.read_text()) or {}).get("blocks", [])


def save(project: Path, blocks: list[dict]) -> None:
    path = project / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = YAML()
    yaml.default_flow_style = False
    buf = StringIO()
    yaml.dump({"schema": "rocketeda/ip-manifest/v0.1", "blocks": blocks}, buf)
    path.write_text(buf.getvalue())


def validate(project: Path, block: dict, existing: list[dict]) -> list[str]:
    errors = []
    if not ID_RE.match(block["id"]):
        errors.append("id must be dotted lowercase, e.g. rocket.analog.opamp_2stage")
    if any(b["id"] == block["id"] and b["version"] == block["version"] for b in existing):
        errors.append(f"{block['id']} {block['version']} is already registered; bump the version")
    if block["domain"] not in DOMAINS:
        errors.append(f"domain must be one of {sorted(DOMAINS)}")
    if not block["ports"]:
        errors.append("a block needs at least one port")
    for port in block["ports"]:
        if not port.get("name"):
            errors.append("every port needs a name")
        if port.get("kind") not in PORT_KINDS:
            errors.append(f"port {port.get('name')}: kind must be one of {sorted(PORT_KINDS)}")
        if port.get("direction") not in DIRECTIONS:
            errors.append(f"port {port.get('name')}: direction must be one of {sorted(DIRECTIONS)}")
    for param in block["parameters"]:
        lo, hi, default = param.get("min"), param.get("max"), param.get("default")
        if None in (lo, hi, default) or not lo <= default <= hi:
            errors.append(f"parameter {param.get('name')}: needs min <= default <= max")
    if not block["views"]:
        errors.append("a block needs at least one view (e.g. spice: design/opamp.cir)")
    for kind, rel in block["views"].items():
        if not rel.startswith(VIEW_DIRS) or ".." in Path(rel).parts or not (project / rel).is_file():
            errors.append(f"view {kind}: {rel} must be an existing file under design/ or ip/")
    return errors


def search(blocks: list[dict], query: str, domain: str = "", pdk: str = "") -> list[dict]:
    words = [w for w in re.split(r"\W+", query.lower()) if w]
    hits = []
    for block in blocks:
        if domain and block["domain"] != domain:
            continue
        if pdk and pdk not in block["pdks"]:
            continue
        text = f"{block['id']} {block['summary']} {block['domain']}".lower()
        score = sum(w in text for w in words)
        if score or not words:
            hits.append((score, block))
    hits.sort(key=lambda hit: -hit[0])
    return [{k: b[k] for k in ("id", "version", "domain", "summary", "pdks", "status")} for _, b in hits]
