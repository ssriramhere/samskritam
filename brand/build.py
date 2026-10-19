"""Build the Samskritam.ai logo files from font outlines.

Concept: the anusvāra bindu over सं is the same dot as the one in ".ai".
Fonts (SIL OFL 1.1): Tiro Devanagari Sanskrit for the mark, Hind SemiBold
for the wordmark. Outlines are converted to SVG paths, so no font loads.

    python brand/build.py <TiroDevanagariSanskrit-Regular.ttf> <Hind-SemiBold.ttf>
"""
import os
import sys

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDIGO, TURMERIC, INK, PAPER = "#333f99", "#e9a91f", "#171a2c", "#f3f3f6"
INDIGO_D, INK_D = "#9ea8ff", "#e8e9f2"


def shape(path, text):
    """Return [(glyph_name, x, y)] in font units, plus the font objects."""
    font = TTFont(path)
    hbf = hb.Font(hb.Face(hb.Blob.from_file_path(path)))
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hbf, buf, {})
    order, x, out = font.getGlyphOrder(), 0, []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        out.append((order[info.codepoint], x + pos.x_offset, pos.y_offset))
        x += pos.x_advance
    return font, out, x


def path_of(font, glyphs, scale, ox, oy, skip=()):
    """SVG path data for glyphs, flipped to SVG's y-down, placed at (ox, oy)
    where oy is the baseline."""
    gs = font.getGlyphSet()
    pen = SVGPathPen(gs)
    for name, x, y in glyphs:
        if name in skip:
            continue
        t = TransformPen(pen, (scale, 0, 0, -scale, ox + x * scale, oy - y * scale))
        gs[name].draw(t)
    return pen.getCommands()


def bounds_of(font, name, x, y):
    gs = font.getGlyphSet()
    bp = BoundsPen(gs)
    gs[name].draw(bp)
    x0, y0, x1, y1 = bp.bounds
    return x0 + x, y0 + y, x1 + x, y1 + y


def mark_parts(tiro):
    font, glyphs, adv = shape(tiro, "सं")
    bindu = next(g for g in glyphs if "nusvara" in g[0])
    bx0, by0, bx1, by1 = bounds_of(font, *bindu)
    sa = [g for g in glyphs if g is not bindu]
    sx0, sy0, sx1, sy1 = bounds_of(font, *sa[0])
    return font, sa, (bx0, by0, bx1, by1), (sx0, sy0, sx1, sy1), bindu[0]


def mark_svg(tiro, tile=True, size=512, ink=PAPER, bg=INDIGO, dot=TURMERIC,
             css=False):
    font, sa, bb, sb, bname = mark_parts(tiro)
    # Fit the whole cluster (Sa + bindu) into the tile with margins.
    x0, y0 = min(sb[0], bb[0]), min(sb[1], bb[1])
    x1, y1 = max(sb[2], bb[2]), max(sb[3], bb[3])
    pad = 0.17 if tile else 0.04
    scale = size * (1 - 2 * pad) / max(x1 - x0, y1 - y0)
    ox = (size - (x1 - x0) * scale) / 2 - x0 * scale
    oy = (size + (y1 - y0) * scale) / 2 + y0 * scale  # baseline
    d = path_of(font, sa, scale, ox, oy)
    cx = ox + (bb[0] + bb[2]) / 2 * scale
    cy = oy - (bb[1] + bb[3]) / 2 * scale
    r = (bb[2] - bb[0]) / 2 * scale * 1.12  # a touch larger: it carries the idea
    fill_ink = 'class="ink"' if css else f'fill="{ink}"'
    fill_dot = 'class="bindu"' if css else f'fill="{dot}"'
    body = []
    if tile:
        body.append(f'<rect width="{size}" height="{size}" rx="{size * .22:.1f}" fill="{bg}"/>')
    body.append(f'<path {fill_ink} d="{d}"/>')
    body.append(f'<circle {fill_dot} cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
            f'role="img" aria-label="Samskritam.ai">{"".join(body)}</svg>'), r / size


def wordmark_svg(tiro, hind, ink=INK, accent=INDIGO, dot=TURMERIC, css=False):
    """Horizontal logo: mark (no tile) + 'Samskritam' + bindu + 'ai'."""
    h = 120  # cap-height box the wordmark is fitted to
    hfont, sam, sam_adv = shape(hind, "Samskritam")
    _, ai, ai_adv = shape(hind, "ai")
    upem = hfont["head"].unitsPerEm
    scale = h / (upem * 0.70)
    base = 150
    mark, rel = mark_svg(tiro, tile=False, size=200, css=css, ink=accent, dot=dot)
    inner = mark.split(">", 1)[1].rsplit("</svg>", 1)[0]
    x_text = 200 + 34
    d_sam = path_of(hfont, sam, scale, x_text, base)
    dot_r = rel * 200 * 0.82
    dot_cx = x_text + sam_adv * scale + dot_r + 7
    x_ai = dot_cx + dot_r + 6
    d_ai = path_of(hfont, ai, scale, x_ai, base)
    width = x_ai + ai_adv * scale + 6
    fill_ink = 'class="word"' if css else f'fill="{ink}"'
    fill_dot = 'class="bindu"' if css else f'fill="{dot}"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} 200" '
            f'role="img" aria-label="Samskritam.ai">{inner}'
            f'<path {fill_ink} d="{d_sam}"/>'
            f'<circle {fill_dot} cx="{dot_cx:.1f}" cy="{base - dot_r:.1f}" r="{dot_r:.1f}"/>'
            f'<path {fill_ink} d="{d_ai}"/></svg>')


def main():
    tiro, hind = sys.argv[1], sys.argv[2]
    out = os.path.join(ROOT, "brand")
    web = os.path.join(ROOT, "web")
    files = {
        os.path.join(out, "mark.svg"): mark_svg(tiro)[0],
        os.path.join(web, "favicon.svg"): mark_svg(tiro)[0],
        os.path.join(out, "mark-plain.svg"): mark_svg(tiro, tile=False, ink=INDIGO)[0],
        os.path.join(out, "logo.svg"): wordmark_svg(tiro, hind),
        os.path.join(out, "logo-dark.svg"): wordmark_svg(tiro, hind, ink=INK_D, accent=INDIGO_D),
        os.path.join(out, "logo-css.svg"): wordmark_svg(tiro, hind, css=True),
    }
    for p, s in files.items():
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)
        print(p, len(s))


if __name__ == "__main__":
    main()
