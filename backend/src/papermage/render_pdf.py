#!/usr/bin/env python3
"""
Render a PDF as a self-contained HTML file using papermage's semantic extraction.

Approach:
  - Each page is rendered as a background image (72 DPI)
  - Detected figure regions are re-rasterized at high DPI and overlaid in place
  - All text tokens are positioned as transparent <span> elements for selection/search
  - Semantic structure (sections, paragraphs, equations, captions) is preserved as
    data attributes for potential JS interaction
"""

import argparse
import base64
import io
import sys
from pathlib import Path

from PIL import Image

from papermage.recipes import CoreRecipe
from papermage.rasterizers.rasterizer import PDF2ImageRasterizer


def img_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def crop_box(img: Image.Image, l: float, t: float, w: float, h: float) -> Image.Image:
    pw, ph = img.size
    return img.crop((int(l * pw), int(t * ph), int((l + w) * pw), int((t + h) * ph)))


def render(pdf_path: str, output_path: str, display_width: int = 900, figure_dpi: int = 216):
    print("Parsing PDF with CoreRecipe...", file=sys.stderr)
    recipe = CoreRecipe()
    doc = recipe.run(pdf_path)

    # Re-rasterize at high DPI for figure crops
    print(f"Re-rasterizing for figures at {figure_dpi} DPI...", file=sys.stderr)
    rasterizer = PDF2ImageRasterizer()
    hi_res_pages = list(rasterizer.rasterize(pdf_path, dpi=figure_dpi))

    # Build per-page lookup tables for each semantic layer
    def boxes_on_page(entities, page_idx):
        result = []
        for ent in entities:
            for box in ent.boxes:
                if box.page == page_idx:
                    result.append((ent, box))
        return result

    pages_html = []

    for page_idx, page_img_entity in enumerate(doc.images):
        page_img = page_img_entity.pilimage
        page_w, page_h = page_img.size
        aspect = page_h / page_w
        display_h = int(display_width * aspect)

        hi_res_img = hi_res_pages[page_idx].pilimage

        elements = []

        # 1. Background: full page rasterization
        bg_b64 = img_to_b64(page_img)
        elements.append(
            f'<img class="page-bg" src="data:image/png;base64,{bg_b64}" '
            f'style="position:absolute;top:0;left:0;width:100%;height:100%;display:block;pointer-events:none;">'
        )

        # 2. Figure overlays: hi-res crop replaces the background region
        for fig, box in boxes_on_page(doc.figures, page_idx):
            fig_img = crop_box(hi_res_img, box.l, box.t, box.w, box.h)
            fig_b64 = img_to_b64(fig_img)
            pct = lambda v: f"{v * 100:.4f}%"
            elements.append(
                f'<img class="figure" src="data:image/png;base64,{fig_b64}" '
                f'title="Figure" '
                f'style="position:absolute;left:{pct(box.l)};top:{pct(box.t)};'
                f'width:{pct(box.w)};height:{pct(box.h)};'
                f'z-index:2;box-sizing:border-box;">'
            )

        # 3. Semantic region overlays (invisible, but hoverable / data-tagged)
        semantic_layers = [
            ("equation", doc.equations),
            ("caption", doc.captions),
            ("section", doc.sections),
            ("paragraph", doc.paragraphs),
            ("bibliography", doc.bibliographies),
            ('sentences', doc.sentences),
        ]
        for kind, entities in semantic_layers:
            for ent, box in boxes_on_page(entities, page_idx):
                snippet = (ent.text or "")[:120].replace('"', "&quot;")
                pct = lambda v: f"{v * 100:.4f}%"
                elements.append(
                    f'<div class="sem-{kind}" data-kind="{kind}" title="{snippet}" '
                    f'style="position:absolute;left:{pct(box.l)};top:{pct(box.t)};'
                    f'width:{pct(box.w)};height:{pct(box.h)};z-index:3;'
                    f'box-sizing:border-box;cursor:default;"></div>'
                )

        # 4. Text token spans: transparent but selectable/searchable
        for token, box in boxes_on_page(doc.tokens, page_idx):
            font_px = box.h * display_h
            pct = lambda v: f"{v * 100:.4f}%"
            text = (token.text or "").replace("<", "&lt;").replace(">", "&gt;")
            elements.append(
                f'<span style="position:absolute;left:{pct(box.l)};top:{pct(box.t)};'
                f'width:{pct(box.w)};height:{pct(box.h)};'
                f'font-size:{font_px:.1f}px;line-height:1;'
                f'color:transparent;white-space:nowrap;overflow:hidden;'
                f'user-select:text;cursor:text;z-index:4;">'
                f'{text}</span>'
            )

        pages_html.append(
            f'\n<div class="page" data-page="{page_idx + 1}" '
            f'style="position:relative;width:{display_width}px;height:{display_h}px;'
            f'margin:24px auto;box-shadow:0 4px 20px rgba(0,0,0,0.4);background:white;">'
            + "".join(elements)
            + "\n</div>"
        )
        print(f"  Page {page_idx + 1}/{len(doc.images)} done", file=sys.stderr)

    title = Path(pdf_path).stem
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #525659;
    padding: 20px 0 40px;
    font-family: sans-serif;
  }}
  .toolbar {{
    position: sticky;
    top: 0;
    z-index: 100;
    background: #323639;
    color: #ddd;
    padding: 8px 20px;
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 13px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4);
  }}
  .toolbar input {{
    padding: 4px 8px;
    border-radius: 4px;
    border: none;
    background: #555;
    color: white;
    width: 220px;
  }}
  label {{ display: flex; align-items: center; gap: 6px; cursor: pointer; }}
  .page {{ overflow: hidden; }}
  .page-bg {{ user-select: none; }}

  /* Highlight modes toggled by toolbar checkboxes */
  body.show-figures .figure {{
    outline: 2px solid #f0a500;
    outline-offset: -2px;
  }}
  body.show-equations .sem-equation {{
    background: rgba(100, 180, 255, 0.18);
    outline: 1px solid rgba(100, 180, 255, 0.5);
  }}
  body.show-sections .sem-section {{
    background: rgba(100, 220, 100, 0.15);
    outline: 1px dashed rgba(80, 180, 80, 0.6);
  }}
  body.show-captions .sem-caption {{
    background: rgba(255, 140, 0, 0.12);
    outline: 1px dashed rgba(255, 140, 0, 0.5);
  }}
  body.show-bibliographies .sem-bibliography {{
    background: rgba(200, 100, 200, 0.12);
    outline: 1px dashed rgba(180, 80, 180, 0.5);
  }}
</style>
</head>
<body>
<div class="toolbar">
  <strong>{title}</strong>
  <input type="search" id="search" placeholder="Search text… (Ctrl+F works too)">
  <label><input type="checkbox" id="chk-figures" checked> Figures</label>
  <label><input type="checkbox" id="chk-equations"> Equations</label>
  <label><input type="checkbox" id="chk-sections"> Sections</label>
  <label><input type="checkbox" id="chk-captions"> Captions</label>
  <label><input type="checkbox" id="chk-bibliographies"> References</label>
</div>
{"".join(pages_html)}
<script>
  // Highlight toggles
  const toggles = {{
    'chk-figures':       'show-figures',
    'chk-equations':     'show-equations',
    'chk-sections':      'show-sections',
    'chk-captions':      'show-captions',
    'chk-bibliographies':'show-bibliographies',
  }};
  Object.entries(toggles).forEach(([id, cls]) => {{
    const el = document.getElementById(id);
    if (el.checked) document.body.classList.add(cls);
    el.addEventListener('change', () => {{
      document.body.classList.toggle(cls, el.checked);
    }});
  }});
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nWrote {output_path}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Input PDF path")
    parser.add_argument("-o", "--output", help="Output HTML path (default: <stem>.html)")
    parser.add_argument("--width", type=int, default=900, help="Display width in px (default: 900)")
    parser.add_argument("--figure-dpi", type=int, default=216, help="DPI for figure crops (default: 216)")
    args = parser.parse_args()

    out = args.output or (Path(args.pdf).stem + ".html")
    render(args.pdf, out, display_width=args.width, figure_dpi=args.figure_dpi)
