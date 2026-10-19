"""Generate the Samskritam.ai mark: Devanagari सं set in Tiro Devanagari
Sanskrit (SIL OFL 1.1), with the anusvāra bindu drawn in the accent colour.
Outputs SVG paths so the logo needs no font at runtime."""
import json
import sys

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

FONT = sys.argv[1]
font = TTFont(FONT)
gs = font.getGlyphSet()
blob = hb.Blob.from_file_path(FONT)
hbfont = hb.Font(hb.Face(blob))
buf = hb.Buffer()
buf.add_str("सं")
buf.guess_segment_properties()
hb.shape(hbfont, buf, {})
order = font.getGlyphOrder()
x = 0
parts = []
for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
    name = order[info.codepoint]
    pen = SVGPathPen(gs)
    gs[name].draw(pen)
    bp = BoundsPen(gs); gs[name].draw(bp)
    parts.append({"glyph": name, "cluster": info.cluster, "dx": x + pos.x_offset,
                  "dy": pos.y_offset, "d": pen.getCommands(), "bounds": bp.bounds})
    x += pos.x_advance
print(json.dumps({"upem": font["head"].unitsPerEm, "advance": x, "parts": parts}))
