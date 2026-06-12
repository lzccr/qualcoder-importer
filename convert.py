#!/usr/bin/env python3
"""
codebook_to_qdc.py
------------------
Convert a Google Sheets qualitative codebook (exported as CSV) to a
QualCoder-importable .qdc XML file.

Expected CSV layout (first row = header):
    Category, Sub Category, Code, Definition

All three levels are optional per row:
  • Category only           → category description row
  • Category + Sub Category → sub-category description row
  • All three               → leaf code row
  • Sub Category + Code (no separate desc row) → sub-category created on the fly

UUIDs are generated fresh (uuid4) on every run.
Colors are randomized HSL values — saturated, mid-brightness, all unique.

Usage
-----
  python codebook_to_qdc.py input.csv [output.qdc] [--seed N]

  --seed N   fix the random seed for reproducible color output
"""

import argparse
import colorsys
import csv
import os
import random
import sys
import uuid
from xml.dom import minidom
from xml.etree import ElementTree as ET


# ── Color generation ─────────────────────────────────────────────────────────

def _rand_color(rng: random.Random) -> str:
    """Return a random hex color — saturated, medium brightness, never gray."""
    h = rng.random()                   # full hue wheel
    s = rng.uniform(0.55, 0.85)        # punchy saturation
    l = rng.uniform(0.38, 0.62)        # mid lightness (readable on white bg)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


# ── Data model ────────────────────────────────────────────────────────────────

class Node:
    __slots__ = ("name", "description", "codable", "color", "guid", "children")

    def __init__(self, name: str, description: str = "",
                 codable: bool = True, color: str = "") -> None:
        self.name        = name
        self.description = description
        self.codable     = codable
        self.color       = color
        self.guid        = str(uuid.uuid4())
        self.children: list["Node"] = []


# ── CSV → tree ────────────────────────────────────────────────────────────────

def parse_csv(path: str, rng: random.Random) -> list[Node]:
    """
    Parse the codebook CSV and return a list of top-level category nodes.

    Forward-fill rules (handles both merged-cell and repeated-value exports):
      • Category resets Sub Category whenever its value CHANGES.
      • Sub Category is forward-filled within the current category.
    """
    cats:       dict[str, Node]  = {}   # cat_name  → Node
    subs:       dict[tuple, Node]= {}   # (cat, sub) → Node
    cat_order:  list[str]        = []   # insertion order

    prev_cat = ""
    prev_sub = ""

    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            sys.exit(f"ERROR: {path!r} is empty or unreadable.")
        reader.fieldnames = [h.strip() for h in reader.fieldnames]

        for raw in reader:
            cat  = (raw.get("Category",     "") or "").strip()
            sub  = (raw.get("Sub Category", "") or "").strip()
            code = (raw.get("Code",         "") or "").strip()
            defn = (raw.get("Definition",   "") or "").strip()

            # ── Forward-fill Category ──────────────────────────────────────
            if cat:
                if cat != prev_cat:
                    prev_sub = ""        # new category → reset sub context
                prev_cat = cat
            else:
                cat = prev_cat

            if not cat:
                continue                # skip rows before the first category

            # ── Forward-fill Sub Category ──────────────────────────────────
            if sub:
                prev_sub = sub
            else:
                sub = prev_sub          # "" when no sub has appeared yet

            # ── Ensure category node exists ────────────────────────────────
            if cat not in cats:
                cats[cat] = Node(name=cat, codable=False)
                cat_order.append(cat)

            cat_node = cats[cat]

            # ── Row-type dispatch ──────────────────────────────────────────

            if not sub and not code:
                # (1) Category description row
                cat_node.description = defn
                continue

            if sub and not code:
                # (2) Sub-category description row
                key = (cat, sub)
                if key not in subs:
                    sub_node = Node(name=sub, codable=False)
                    subs[key] = sub_node
                    cat_node.children.append(sub_node)
                subs[(cat, sub)].description = defn
                continue

            if code:
                # (3) Leaf code row
                color = _rand_color(rng)
                leaf  = Node(name=code, description=defn,
                             codable=True, color=color)

                if sub:
                    key = (cat, sub)
                    if key not in subs:
                        # Sub-category appeared with no prior description row
                        sub_node = Node(name=sub, codable=False)
                        subs[key] = sub_node
                        cat_node.children.append(sub_node)
                    subs[key].children.append(leaf)
                else:
                    # Direct code under category (no sub-category)
                    cat_node.children.append(leaf)

    return [cats[c] for c in cat_order]


# ── Tree → XML ────────────────────────────────────────────────────────────────

def _node_to_xml(node: Node) -> ET.Element:
    attrs: dict[str, str] = {
        "guid":      node.guid,
        "name":      node.name,
        "isCodable": "true" if node.codable else "false",
    }
    if node.color:
        attrs["color"] = node.color

    el   = ET.Element("Code", attrib=attrs)
    desc = ET.SubElement(el, "Description")
    desc.text = node.description or ""

    for child in node.children:
        el.append(_node_to_xml(child))

    return el


def build_xml(roots: list[Node]) -> bytes:
    cb = ET.Element("CodeBook", attrib={
        "xmlns":              "urn:QDA-XML:codebook:1.0",
        "xsi:schemaLocation": "urn:QDA-XML:codebook:1.0 Codebook.xsd",
        "origin":             "QualCoder",
        "xmlns:xsi":          "http://www.w3.org/2001/XMLSchema-instance",
    })
    codes_el = ET.SubElement(cb, "Codes")
    for root_node in roots:
        codes_el.append(_node_to_xml(root_node))

    raw  = ET.tostring(cb, encoding="unicode")
    dom  = minidom.parseString(raw)
    # toprettyxml returns bytes when encoding is specified
    xml_bytes: bytes = dom.toprettyxml(indent="  ", encoding="utf-8")
    # Prepend UTF-8 BOM to match QualCoder's native export format
    if not xml_bytes.startswith(b"\xef\xbb\xbf"):
        xml_bytes = b"\xef\xbb\xbf" + xml_bytes
    return xml_bytes


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Convert a Google Sheets codebook CSV to QualCoder .qdc"
    )
    ap.add_argument("csv_path", metavar="CSV",
                    help="Input CSV file (exported from Google Sheets)")
    ap.add_argument("qdc_path", metavar="QDC", nargs="?",
                    help="Output .qdc path  (default: <csv_basename>.qdc)")
    ap.add_argument("--seed", type=int, default=None,
                    help="Random seed for reproducible colors (omit for random)")
    args = ap.parse_args()

    out_path = args.qdc_path or (os.path.splitext(args.csv_path)[0] + ".qdc")
    rng      = random.Random(args.seed)

    print(f"Parsing  {args.csv_path!r} …")
    roots = parse_csv(args.csv_path, rng)
    print(f"  {len(roots)} top-level categories:")
    total_subs  = 0
    total_codes = 0
    for r in roots:
        n_subs  = sum(1 for c in r.children if not c.codable)
        n_codes = (sum(1 for c in r.children if c.codable) +
                   sum(len(s.children) for s in r.children if not s.codable))
        total_subs  += n_subs
        total_codes += n_codes
        print(f"    {r.name!r:45s}  {n_subs:2d} sub-cat(s)  {n_codes:3d} code(s)")
    print(f"  Total: {total_subs} sub-categories, {total_codes} leaf codes")

    xml_bytes = build_xml(roots)
    with open(out_path, "wb") as fh:
        fh.write(xml_bytes)
    print(f"Written  {out_path!r}  ({len(xml_bytes):,} bytes)")


if __name__ == "__main__":
    main()
