#!/usr/bin/env python3
"""Deck generator: outline JSON in, ``.pptx`` out, geometry lint (issue 02).

The default value of ``deck.generator_path``: the ``deck`` command calls
this script with the outline JSON and the deliverable path, and this
script never edits an existing ``.pptx`` (a deck is always regenerated
from the outline; a hand-edited deck is drift) and never generates raster
images (every visual is native shapes and text).

Subcommands:

- ``lint <outline.json>``
  Runs the geometry lint only: builds the slide layout and prints one
  ``FAIL`` line per overflow or overlap, then ``lint: N fail line(s)``.
  Exit 1 on any FAIL, 0 on a clean layout.

- ``render <outline.json> <out.pptx>``
  Lints first; any FAIL writes nothing and exits 1 (the command fixes
  the outline and retries, at most three passes). A clean layout writes
  the ``.pptx``. Needs ``python-pptx``; when it is missing the script
  exits 2 with the install hint and writes nothing.

Geometry model: every slide is 13.333 by 7.5 inches. The layout builder
assigns each text run and visual a box (x, y, w, h in inches) and the
lint estimates rendered text height (characters per line from box width
and font size, 1.35 line spacing) and fails when it exceeds the box, or
when two boxes overlap by more than a small tolerance. The lint works on
the same boxes in both modes, so ``lint`` and ``render`` agree.

Exit codes: 0 ok, 1 lint failure or unreadable input, 2 usage or
``python-pptx`` missing (the message includes the install hint), 4
self-test failure.

Usage::

    python scripts/deck_render.py lint <outline.json>
    python scripts/deck_render.py render <outline.json> <out.pptx>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REFERENCES_DIR = PLUGIN_ROOT / "references"
if str(REFERENCES_DIR) not in sys.path:
    sys.path.insert(0, str(REFERENCES_DIR))

import deck_helpers  # noqa: E402  (path set above; single source for visual rules)

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_SELFTEST = 4

try:
    from pptx import Presentation  # type: ignore[import-not-found]
    from pptx.util import Inches, Pt  # type: ignore[import-not-found]

    HAVE_PPTX = True
    PPTX_IMPORT_ERROR: Exception | None = None
except Exception as _exc:  # pragma: no cover - depends on local env
    HAVE_PPTX = False
    PPTX_IMPORT_ERROR = _exc

PPTX_INSTALL_HINT = (
    "python-pptx is required to render a deck; install it with "
    "`pip install python-pptx` (the geometry lint works without it)"
)

#: Slide geometry in inches (16:9).
SLIDE_W = 13.333
SLIDE_H = 7.5
MARGIN = 0.5
TITLE_BOX = (MARGIN, 0.4, SLIDE_W - 2 * MARGIN, 1.0)
BODY_TOP = 1.7
BODY_BOTTOM = 6.9

#: Text estimation constants (inches, points).
CHAR_WIDTH_FACTOR = 0.48   # average glyph width as a share of font size
LINE_SPACING = 1.32        # rendered line height as a share of font size
BOX_PADDING_IN = 0.16

#: Two boxes overlapping by more than this area (sq in) fail the lint.
OVERLAP_TOLERANCE_SQIN = 0.05

BODY_FONT = 16
TITLE_FONT = 28
SMALL_FONT = 12

PLACEHOLDER_PREFIX = "Visual placeholder"


# ---------------------------------------------------------------------------
# layout (pure data; identical for lint and render)
# ---------------------------------------------------------------------------


def _box(x: float, y: float, w: float, h: float, kind: str = "text", text: str = "", font: int = BODY_FONT) -> dict:
    return {"x": x, "y": y, "w": w, "h": h, "kind": kind, "text": text, "font": font}


def _estimate_height(text: str, width: float, font_pt: int) -> float:
    """Estimated rendered height of a paragraph block in inches."""
    chars_per_line = max(8, int(width / (CHAR_WIDTH_FACTOR * font_pt / 72)))
    paragraphs = [p for p in text.split("\n") if p.strip()] or [""]
    lines = sum(max(1, math.ceil(len(p) / chars_per_line)) for p in paragraphs)
    return lines * font_pt * LINE_SPACING / 72 + BOX_PADDING_IN


def _text_box(text: str, x: float, y: float, w: float, h: float, font: int) -> dict:
    return _box(x, y, w, h, "text", text=str(text), font=font)


def _bullets_text(values: list) -> str:
    return "\n".join(str(item) for item in values)


def _grid_positions(count: int, columns: int, top: float, height: float, gap: float = 0.25) -> list[tuple[float, float, float, float]]:
    """Grid boxes for ``count`` cells in ``columns`` columns across the body."""
    usable_w = SLIDE_W - 2 * MARGIN
    cell_w = (usable_w - gap * (columns - 1)) / columns
    rows = max(1, math.ceil(count / columns))
    cell_h = min(height / rows - gap, 2.2)
    positions = []
    for index in range(count):
        col = index % columns
        row = index // columns
        x = MARGIN + col * (cell_w + gap)
        y = top + row * (cell_h + gap)
        positions.append((x, y, cell_w, max(cell_h, 0.8)))
    return positions


def _visual_boxes(spec, slide_id: str) -> tuple[list[dict], list[str]]:
    """Boxes for one visual spec; a bad spec yields one labeled placeholder box."""
    ok, reason = deck_helpers.validate_visual(spec)
    if not ok:
        label = "?"
        if isinstance(spec, dict):
            label = str(spec.get("kind") or "unknown")
        return [
            _box(
                MARGIN + 1.0, BODY_TOP + 0.4, SLIDE_W - 2 * MARGIN - 2.0, 3.4,
                "shape",
                text=f"{PLACEHOLDER_PREFIX}: {label} ({reason})",
                font=SMALL_FONT,
            )
        ], []
    problems: list[str] = []
    boxes: list[dict] = []
    kind = spec.get("kind")
    top, height = BODY_TOP + 0.2, BODY_BOTTOM - BODY_TOP - 0.6
    body_w = SLIDE_W - 2 * MARGIN

    if kind == "bar":
        values = spec["values"]
        labels = spec["labels"]
        area_w, area_h = body_w, height * 0.7
        max_value = max(abs(v) for v in values) or 1
        slot_w = area_w / len(values)
        for index, value in enumerate(values):
            bar_h = max(0.15, abs(value) / max_value * area_h)
            boxes.append(_box(
                MARGIN + index * slot_w + slot_w * 0.2, top + (area_h - bar_h),
                slot_w * 0.6, bar_h, "shape",
                text="", font=SMALL_FONT,
            ))
            boxes.append(_text_box(str(labels[index]), MARGIN + index * slot_w, top + area_h + 0.05, slot_w, 0.4, SMALL_FONT))
    elif kind == "pie":
        slices = spec["slices"]
        positions = _grid_positions(len(slices), 2, top, height)
        for index, slice_item in enumerate(slices):
            x, y, w, h = positions[index]
            boxes.append(_text_box(f"{slice_item['label']}: {slice_item['value']}", x, y, w, h, SMALL_FONT))
    elif kind in ("line", "mountain"):
        labels = spec.get("labels") or []
        slot_w = body_w / max(1, len(labels))
        for index, label in enumerate(labels):
            boxes.append(_text_box(str(label), MARGIN + index * slot_w, top + height - 0.45, slot_w, 0.4, SMALL_FONT))
        boxes.append(_box(MARGIN, top, body_w, height - 0.6, "shape", text="", font=SMALL_FONT))
    elif kind == "matrix2x2":
        quadrants = spec["quadrants"]
        for index, quadrant in enumerate(quadrants):
            x = MARGIN + (index % 2) * (body_w / 2 + 0.05)
            y = top + (index // 2) * (height / 2 + 0.05)
            boxes.append(_text_box(str(quadrant.get("title", "")), x, y, body_w / 2 - 0.1, height / 2 - 0.1, SMALL_FONT))
    elif kind in ("funnel", "pyramid"):
        stages = spec.get("stages") or spec.get("levels") or []
        band_h = min(0.8, height / len(stages))
        for index, stage in enumerate(stages):
            boxes.append(_text_box(str(stage.get("label", "")), MARGIN + 1.5, top + index * band_h, body_w - 3.0, band_h, SMALL_FONT))
    elif kind == "timeline":
        milestones = spec["milestones"]
        slot_w = body_w / len(milestones)
        for index, milestone in enumerate(milestones):
            boxes.append(_text_box(str(milestone.get("label", "")), MARGIN + index * slot_w, top, slot_w, 0.5, SMALL_FONT))
            if milestone.get("text"):
                boxes.append(_text_box(str(milestone["text"]), MARGIN + index * slot_w, top + 0.6, slot_w, 1.2, SMALL_FONT))
    elif kind in ("process", "chevron", "cycle", "journey"):
        steps = spec.get("steps") or spec.get("stages") or []
        slot_w = body_w / len(steps)
        for index, step in enumerate(steps):
            boxes.append(_text_box(str(step.get("label", "")), MARGIN + index * slot_w, top, slot_w, 1.0, SMALL_FONT))
    elif kind == "venn":
        sets = spec["sets"]
        slot_w = body_w / len(sets)
        for index, set_item in enumerate(sets):
            boxes.append(_text_box(str(set_item.get("label", "")), MARGIN + index * slot_w, top + 0.4, slot_w, height - 1.0, SMALL_FONT))
    elif kind == "hierarchy":
        root = spec["root"]
        boxes.append(_text_box(str(root.get("label", "")), MARGIN + body_w / 4, top, body_w / 2, 0.7, SMALL_FONT))
        children = root.get("children") or []
        if children:
            child_w = body_w / len(children)
            for index, child in enumerate(children):
                label = child.get("label") if isinstance(child, dict) else str(child)
                boxes.append(_text_box(str(label), MARGIN + index * child_w, top + 1.1, child_w, 0.8, SMALL_FONT))
    elif kind == "quadrant_plot":
        points = spec["points"]
        for point in points:
            label = str(point.get("label") or "")
            boxes.append(_text_box(label, MARGIN + 0.2, top + 0.2, 1.6, 0.4, SMALL_FONT))
    elif kind == "comparison":
        columns = spec["columns"]
        for index, column in enumerate(columns):
            x = MARGIN + index * (body_w / 2 + 0.05)
            points = column.get("points") or []
            text = str(column.get("title", "")) + ("\n" + "\n".join(str(p) for p in points) if points else "")
            boxes.append(_text_box(text, x, top, body_w / 2 - 0.1, height, SMALL_FONT))
    elif kind == "grid":
        cells = spec["cells"]
        columns = int(spec.get("columns") or 2)
        for index, (x, y, w, h) in enumerate(_grid_positions(len(cells), columns, top, height)):
            cell = cells[index]
            text = str(cell.get("title") or "") + ("\n" + str(cell.get("text")) if cell.get("text") else "")
            boxes.append(_text_box(text, x, y, w, h, SMALL_FONT))
    elif kind == "swimlane":
        lanes = spec["lanes"]
        periods = spec.get("periods") or []
        lane_h = height / len(lanes)
        for index, lane in enumerate(lanes):
            boxes.append(_text_box(str(lane.get("label", "")), MARGIN, top + index * lane_h, 2.0, lane_h, SMALL_FONT))
            steps = lane.get("steps") or []
            step_w = (body_w - 2.2) / max(1, len(periods) or 1)
            for step_index, step in enumerate(steps):
                x = MARGIN + 2.2 + step_index * step_w
                y = top + index * lane_h
                label = step.get("label") if isinstance(step, dict) else str(step)
                boxes.append(_text_box(str(label), x, y, step_w, lane_h - 0.1, SMALL_FONT))
    elif kind in ("network", "decision-flow"):
        nodes = spec["nodes"]
        slot_w = body_w / len(nodes)
        for index, node in enumerate(nodes):
            boxes.append(_text_box(str(node.get("label") or node.get("id", "")), MARGIN + index * slot_w, top + 0.5, slot_w, 0.8, SMALL_FONT))

    return boxes, problems


def build_layout(slide: dict, slide_index: int) -> tuple[list[dict], list[str]]:
    """Boxes for one outline slide plus any structural problems found."""
    problems: list[str] = []
    kind = slide.get("kind") or "content"
    title = str(slide.get("title") or "")
    boxes: list[dict] = []
    x, y, w, h = TITLE_BOX
    if kind == "cover":
        boxes.append(_text_box(title, MARGIN, 2.4, SLIDE_W - 2 * MARGIN, 1.6, 36))
        subtitle = " ".join(
            str(part)
            for part in (slide.get("subtitle"), slide.get("audience"), slide.get("date"))
            if part
        )
        if subtitle:
            boxes.append(_text_box(subtitle, MARGIN, 4.2, SLIDE_W - 2 * MARGIN, 0.6, BODY_FONT))
        return boxes, problems
    if kind == "end":
        boxes.append(_text_box(title or "Thank you", MARGIN, 3.2, SLIDE_W - 2 * MARGIN, 1.0, 32))
        return boxes, problems

    boxes.append(_text_box(title, x, y, w, h, TITLE_FONT))
    body_top, body_h = BODY_TOP, BODY_BOTTOM - BODY_TOP

    if kind == "agenda":
        items = slide.get("items") or []
        if items:
            boxes.append(_text_box(_bullets_text(items), x, body_top, w, body_h, BODY_FONT))
    elif kind in ("exec-summary", "bullets", "finding", "recommendations", "appendix"):
        bullets = slide.get("bullets") or []
        if bullets:
            boxes.append(_text_box(_bullets_text(bullets), x, body_top, w, body_h, BODY_FONT))
        if kind == "finding":
            note = str(slide.get("note") or "")
            if note:
                boxes.append(_text_box(note, x, BODY_BOTTOM, w, 0.45, SMALL_FONT))
    elif kind in ("content", "question"):
        text = str(slide.get("text") or "")
        if text:
            font = BODY_FONT if kind == "content" else 22
            boxes.append(_text_box(text, x, body_top + (0.6 if kind == "question" else 0), w, body_h - 0.6, font))
    elif kind == "stats":
        stats = slide.get("stats") or []
        for index, (bx, by, bw, bh) in enumerate(_grid_positions(len(stats), min(3, max(1, len(stats))), body_top, body_h)):
            entry = stats[index]
            boxes.append(_text_box(str(entry.get("value", "")), bx, by, bw, bh / 2, 30))
            boxes.append(_text_box(str(entry.get("label", "")), bx, by + bh / 2, bw, bh / 2, SMALL_FONT))
    elif kind == "three-col":
        columns = slide.get("columns") or []
        slot_w = w / max(1, len(columns)) if columns else w
        for index, column in enumerate(columns):
            text = str(column.get("title", "")) + "\n" + str(column.get("text") or "")
            boxes.append(_text_box(text, x + index * slot_w, body_top, slot_w - 0.2, body_h, BODY_FONT))
    elif kind == "quote":
        quote = str(slide.get("quote") or "")
        attribution = str(slide.get("attribution") or "")
        if quote:
            boxes.append(_text_box(f'"{quote}"', x + 0.5, body_top, w - 1.0, body_h - 0.8, 22))
        if attribution:
            boxes.append(_text_box(attribution, x + 0.5, BODY_BOTTOM - 0.5, w - 1.0, 0.45, SMALL_FONT))
    elif kind == "diagram":
        visual_boxes, visual_problems = _visual_boxes(slide.get("visual"), str(slide.get("id") or kind))
        boxes.extend(visual_boxes)
        problems.extend(visual_problems)
        caption = str(slide.get("caption") or "")
        if caption:
            boxes.append(_text_box(caption, x, BODY_BOTTOM, w, 0.45, SMALL_FONT))

    return boxes, problems


def lint_layout(slide_layouts: list[tuple[str, list[dict], list[str]]]) -> list[str]:
    """Geometry lint over ``(slide_id, boxes, problems)`` triples."""
    failures: list[str] = []
    for slide_id, boxes, problems in slide_layouts:
        for problem in problems:
            failures.append(f"FAIL spec {slide_id}: {problem}")
        for box in boxes:
            text = box.get("text") or ""
            if not text.strip():
                continue
            needed = _estimate_height(text, box["w"], box["font"])
            if needed > box["h"] + 0.02:
                failures.append(
                    f"FAIL overflow {slide_id}: box {box['w']:.2f}x{box['h']:.2f}in at font {box['font']}pt "
                    f"needs {needed:.2f}in for {len(text)} characters"
                )
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                overlap_w = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
                overlap_h = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
                if overlap_w > 0.01 and overlap_h > 0.01 and overlap_w * overlap_h > OVERLAP_TOLERANCE_SQIN:
                    failures.append(
                        f"FAIL overlap {slide_id}: boxes at ({a['x']:.2f},{a['y']:.2f}) and "
                        f"({b['x']:.2f},{b['y']:.2f}) overlap by {overlap_w * overlap_h:.2f} sq in"
                    )
    return failures


def lint_outline_file(outline_path: str) -> tuple[list[str], dict]:
    """Build the layout for every slide and run the geometry lint."""
    try:
        outline = json.loads(Path(outline_path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"FAIL input: cannot read outline: {exc}"], {}
    slides = outline.get("slides") if isinstance(outline, dict) else None
    if not isinstance(slides, list) or not slides:
        return ["FAIL input: outline must be a mapping with a non-empty slides list"], outline
    layouts = []
    for index, slide in enumerate(slides):
        slide_id = str(slide.get("id") or f"slide-{index}")
        boxes, problems = build_layout(slide if isinstance(slide, dict) else {}, index)
        layouts.append((slide_id, boxes, problems))
    return lint_layout(layouts), outline


# ---------------------------------------------------------------------------
# render (python-pptx; same layout boxes as the lint)
# ---------------------------------------------------------------------------


def _require_pptx() -> int:
    if HAVE_PPTX:
        return EXIT_OK
    print(f"deck_render: {PPTX_INSTALL_HINT}", file=sys.stderr)
    if PPTX_IMPORT_ERROR is not None:
        print(f"deck_render: import error was: {PPTX_IMPORT_ERROR}", file=sys.stderr)
    return EXIT_USAGE


def _add_text(slide, box: dict) -> None:
    left, top, width, height = Inches(box["x"]), Inches(box["y"]), Inches(box["w"]), Inches(box["h"])
    shape = slide.shapes.add_textbox(left, top, width, height)
    frame = shape.text_frame
    frame.word_wrap = True
    first = True
    for paragraph in (box.get("text") or "").split("\n"):
        para = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        para.text = paragraph


def _add_shape(slide, box: dict) -> None:
    left, top, width, height = Inches(box["x"]), Inches(box["y"]), Inches(box["w"]), Inches(box["h"])
    shape = slide.shapes.add_shape(1, left, top, width, height)  # 1 = rectangle
    shape.shadow.inherit = False
    text = str(box.get("text") or "")
    if text:
        frame = shape.text_frame
        frame.word_wrap = True
        frame.paragraphs[0].text = text
    else:
        shape.text_frame.paragraphs[0].text = ""


def render_outline(outline: dict, out_path: Path) -> list[str]:
    """Write the ``.pptx``; returns [] on success (lint failures block earlier)."""
    if not HAVE_PPTX:
        return [PPTX_INSTALL_HINT]
    presentation = Presentation()
    presentation.slide_width = Inches(SLIDE_W)
    presentation.slide_height = Inches(SLIDE_H)
    blank = presentation.slide_layouts[6]
    for index, slide_spec in enumerate(outline.get("slides") or []):
        slide = presentation.slides.add_slide(blank)
        boxes, _problems = build_layout(slide_spec if isinstance(slide_spec, dict) else {}, index)
        for box in boxes:
            if box.get("kind") == "shape":
                _add_shape(slide, box)
            else:
                _add_text(slide, box)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(str(out_path))
    return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_lint(args: dict[str, str]) -> int:
    outline_file = args.get("positional") or ""
    if not outline_file:
        print("deck_render: lint needs <outline.json>", file=sys.stderr)
        return EXIT_USAGE
    failures, _outline = lint_outline_file(outline_file)
    for line in failures:
        print(line)
    if not failures:
        print("lint: layout is clean (no overflow, no overlap)")
        return EXIT_OK
    print(f"lint: {len(failures)} fail line(s)")
    return EXIT_FAIL


def _cmd_render(args: dict[str, str]) -> int:
    outline_file = args.get("positional") or ""
    out_file = args.get("out") or ""
    if not outline_file or not out_file:
        print("deck_render: render needs <outline.json> <out.pptx>", file=sys.stderr)
        return EXIT_USAGE
    code = _require_pptx()
    if code != EXIT_OK:
        return code
    failures, outline = lint_outline_file(outline_file)
    if failures:
        for line in failures:
            print(line)
        print(f"lint: {len(failures)} fail line(s); nothing written")
        return EXIT_FAIL
    written = render_outline(outline, Path(out_file).expanduser())
    if written:
        for line in written:
            print(line, file=sys.stderr)
        return EXIT_FAIL
    print(f"render: wrote {out_file}")
    return EXIT_OK


def _parse_args(argv: list[str]) -> tuple[str, dict[str, str]] | None:
    """Parse ``lint <outline>`` / ``render <outline> <out>``; None on bad usage."""
    if not argv:
        return None
    command = argv[0]
    rest = argv[1:]
    parsed: dict[str, str] = {"positional": "", "out": ""}
    positionals: list[str] = []
    index = 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("--"):
            return None
        positionals.append(token)
        index += 1
    if command == "lint" and positionals:
        parsed["positional"] = positionals[0]
    elif command == "render" and len(positionals) == 2:
        parsed["positional"], parsed["out"] = positionals
    elif not positionals:
        pass
    else:
        return None
    return command, parsed


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; -h prints the full doc
        return EXIT_OK
    if args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_USAGE
    parsed = _parse_args(args)
    if parsed is None:
        print("deck_render: usage: lint <outline.json> | render <outline.json> <out.pptx>", file=sys.stderr)
        return EXIT_USAGE
    command, flags = parsed
    if command == "lint":
        return _cmd_lint(flags)
    if command == "render":
        return _cmd_render(flags)
    print(f"deck_render: unknown subcommand {command!r}", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
