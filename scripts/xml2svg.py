#!/usr/bin/env python3
"""Render SML slides as self-contained, approximate SVG previews.

Relative images (@./foo.png or foo.png) resolve against the XML directory first,
then --assets-dir (default: this installed skill's assets directory). Absolute
paths are used as-is. URLs and Feishu tokens are not fetched. Text metrics,
auto-fit, font substitution and exact chart layout require Feishu screenshots.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import re
import sys
import unicodedata
from pathlib import Path
from xml.etree import ElementTree as ET

W, H = 960, 540
SKILL_ROOT = Path(__file__).resolve().parent.parent
FONT = "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif"
APPROXIMATION = "Approximate preview: estimated text wrapping; no auto-fit or exact Feishu font/chart layout. Final acceptance requires Feishu screenshots."
GEOMETRY = {"topLeftX", "topLeftY", "width", "height"}
LINE_ENDPOINTS = ("startX", "startY", "endX", "endY")
TEXT_ATTRS = {"fontSize", "fontFamily", "color", "bold", "italic", "underline", "strikethrough", "textAlign", "verticalAlign", "lineSpacing", "wrap", "autoFit"}
COLOR_PATTERN = re.compile(r"rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)|#[0-9a-fA-F]{3,4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}")
# Unknown elements/attributes are reported; identity metadata is intentionally ignored.
SUPPORTED = {
    "slide": {"width", "height"}, "data": set(), "style": set(),
    "shape": GEOMETRY | {"type", "radius", "presetHandlers"},
    "line": set(LINE_ENDPOINTS) | {"type", "alpha"},
    "startArrow": {"type", "widthScale", "heightScale"},
    "endArrow": {"type", "widthScale", "heightScale"},
    "content": TEXT_ATTRS, "p": TEXT_ATTRS, "span": TEXT_ATTRS, "br": set(),
    "fill": set(), "fillColor": {"color"}, "border": {"color", "width"},
    "img": GEOMETRY | {"src"}, "table": GEOMETRY, "colgroup": set(),
    "col": {"width"}, "tr": {"height"}, "td": set(), "chart": GEOMETRY,
    "chartPlotArea": set(), "chartPlot": {"type"}, "chartExtra": set(),
    "chartSmooth": set(), "chartAxes": set(), "chartAxis": {"type", "position"},
    "chartGridLine": {"color", "width"}, "chartLabel": {"fontSize", "color"},
    "chartData": set(), "dim1": set(), "dim2": set(),
    "chartField": {"name", "valueType"}, "chartStyle": set(),
    "chartBackground": {"color"}, "chartBorder": {"color", "width"},
    "chartColorTheme": set(), "color": {"value"}, "chartLegend": {"position", "fontSize"},
}


def esc(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def children(elem, tag):
    return [] if elem is None else [child for child in elem if local_name(child.tag) == tag]


def find(elem, path):
    for name in path.split("/"):
        elem = next(iter(children(elem, name)), None)
        if elem is None:
            break
    return elem


def parse_float(value, default=0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def rgba_to_hex(color):
    """Accept CSS rgb/rgba, hex and transparent, preserving alpha."""
    color = (color or "").strip()
    match = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)", color)
    if match:
        result = "#" + "".join(f"{min(255,int(match[i])):02X}" for i in (1, 2, 3))
        alpha = parse_float(match[4], 1)
        return result + (f"{round(max(0,min(1,alpha))*255):02X}" if alpha < 1 else "")
    if re.fullmatch(r"#[0-9a-fA-F]{3,4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}", color):
        return color
    return {"transparent": "#00000000", "white": "#FFFFFF", "black": "#000000", "none": "none"}.get(color, "#000000")


def geometry(elem):
    return tuple(parse_float(elem.get(key), default) for key, default in
                 (("topLeftX", 0), ("topLeftY", 0), ("width", 100), ("height", 20)))


def glyph_width(char, style):
    factor = 0 if unicodedata.combining(char) else (1 if unicodedata.east_asian_width(char) in "WF" else 0.55)
    if char.isspace():
        factor = 0.33
    return factor * parse_float(style.get("fontSize"), 14)


class Renderer:
    def __init__(self, xml_path, assets_dir=None, diagnostics=None):
        self.xml_path = Path(xml_path).resolve()
        self.base_dir = self.xml_path.parent
        self.assets_dir = Path(assets_dir).resolve() if assets_dir else SKILL_ROOT / "assets"
        self.issues = diagnostics if diagnostics is not None else []
        self.seen = set()

    def issue(self, code, message, elem=None, severity="warning"):
        element = local_name(elem.tag) if elem is not None else "slide"
        key = (code, message, element)
        if key not in self.seen:
            self.seen.add(key)
            self.issues.append({"severity": severity, "code": code, "element": element, "message": message})

    def audit(self, root):
        for elem in root.iter():
            tag = local_name(elem.tag)
            if tag not in SUPPORTED:
                self.issue("unsupported_element", f"<{tag}> has no SVG renderer; its appearance is omitted.", elem)
                continue
            for key, value in elem.attrib.items():
                if local_name(key) not in SUPPORTED[tag] | {"id", "name"}:
                    self.issue("unsupported_attribute", f"<{tag}> attribute {key}={value!r} is not rendered.", elem)
                if key == "color" or (tag == "color" and key == "value"):
                    if not COLOR_PATTERN.fullmatch(value.strip()) and value not in {"transparent", "white", "black", "none"}:
                        self.issue("unsupported_color", f"Color {value!r} is unsupported; preview uses black. Use hex, rgb or rgba.", elem)
                if key in GEOMETRY or key == "fontSize":
                    numeric = parse_float(value, None)
                    size = key in {"width", "height", "fontSize"}
                    border_width = tag in {"border", "chartBorder", "chartGridLine"} and key == "width"
                    invalid_size = size and (numeric is not None) and (numeric < 0 if border_width else numeric <= 0)
                    if numeric is None or invalid_size:
                        constraint = " nonnegative." if border_width else (" greater than zero." if size else ".")
                        self.issue("invalid_numeric_attribute", f"<{tag}> {key}={value!r} must be a finite number" + constraint, elem, "error")
            if tag in {"content", "p", "span"}:
                for key, allowed in {"textAlign": {"left", "center", "right"}, "verticalAlign": {"top", "middle", "bottom"}, "autoFit": {"normal-auto-fit", "none", "no-auto-fit"}}.items():
                    if key in elem.attrib and elem.get(key) not in allowed:
                        self.issue("unsupported_attribute_value", f"<{tag}> {key}={elem.get(key)!r} uses default preview behavior.", elem)
                if "lineSpacing" in elem.attrib and not re.fullmatch(r"(?:multiple|points):[\d.]+", elem.get("lineSpacing")):
                    self.issue("unsupported_line_spacing", f"lineSpacing={elem.get('lineSpacing')!r} uses 1.35 line spacing.", elem)
            if tag == "chartSmooth":
                self.issue("chart_smoothing_approximation", "Smooth curves use straight segments through the actual data points.", elem)
            if tag == "chartAxis" and (elem.get("type") not in {"x", "y"} or elem.get("position", "left") not in {"left", "bottom"}):
                self.issue("unsupported_chart_axis", "Only a bottom category axis and a left numeric axis are rendered.", elem)
            if tag == "chartLegend" and elem.get("position", "bottom") != "bottom":
                self.issue("legend_position_approximation", "Legend position is approximated at the bottom of the chart.", elem)

    def fill(self, elem, default="#FFFFFF"):
        color = find(elem, "fill/fillColor")
        return rgba_to_hex(color.get("color")) if color is not None else default

    def border(self, elem, child="border", default=""):
        border = find(elem, child)
        if border is None:
            return default
        return f' stroke="{esc(rgba_to_hex(border.get("color", "#000000")))}" stroke-width="{parse_float(border.get("width"),1):g}"'

    def placeholder(self, elem, label):
        x, y, w, h = geometry(elem)
        return (f'<g data-preview-placeholder="true"><rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
                f'fill="#FFF4F4" stroke="#C62828" stroke-dasharray="4 3"/>'
                f'<text x="{x+4:g}" y="{y+min(h-2,14):g}" font-size="10" fill="#A01010">{esc(label)}</text></g>')

    def collect_runs(self, elem, inherited):
        style = {**inherited, **elem.attrib}
        runs = [(elem.text, style)] if elem.text else []
        for child in elem:
            runs.extend([("\n", style)] if local_name(child.tag) == "br" else self.collect_runs(child, style))
            if child.tail:
                runs.append((child.tail, style))
        return runs

    def text(self, elem):
        x, y, w, h = geometry(elem)
        content = find(elem, "content")
        if content is None:
            return ""
        base = {"fontSize": "14", "fontFamily": "思源黑体", "color": "#171717", **content.attrib}
        blocks = []
        if children(content, "p"):
            if content.text and content.text.strip():
                blocks.append(([(content.text, base)], base))
            for child in content:
                blocks.append((self.collect_runs(child, base), {**base, **child.attrib}))
                if child.tail and child.tail.strip():
                    blocks.append(([(child.tail, base)], base))
        else:
            blocks = [(self.collect_runs(content, base), base)]
        lines = []
        for runs, style in blocks:
            current, width = [], 0
            for text, run_style in runs:
                for char in text.replace("\r\n", "\n").replace("\r", "\n"):
                    advance = glyph_width(char, run_style)
                    if char == "\n" or (style.get("wrap", "true") != "false" and current and width+advance > w):
                        lines.append((current, style))
                        current, width = [], 0
                    if char != "\n":
                        current.append((char, run_style))
                        width += advance
            lines.append((current, style))
        heights, sizes = [], []
        for line, style in lines:
            size = max([parse_float(s.get("fontSize"),14) for _,s in line] or [parse_float(style.get("fontSize"),14)])
            spacing = style.get("lineSpacing", "multiple:1.35")
            value = parse_float(spacing.split(":")[-1],1.35)
            heights.append(value if spacing.startswith("points:") else size*value)
            sizes.append(size)
        total_h = sum(heights)
        top = y + {"middle": (h-total_h)/2, "bottom": h-total_h}.get(base.get("verticalAlign"),0)
        parts = ['<g data-preview-text="true">']
        for index, (line, style) in enumerate(lines):
            align = style.get("textAlign", "left")
            anchor = {"left": "start", "center": "middle", "right": "end"}.get(align, "start")
            tx = {"left": x, "center": x+w/2, "right": x+w}.get(align,x)
            line_parts = [f'<text x="{tx:g}" y="{top+sizes[index]*0.85:g}" text-anchor="{anchor}" xml:space="preserve">']
            groups = []
            for char, run_style in line:
                if groups and groups[-1][1] == run_style:
                    groups[-1] = (groups[-1][0]+char,run_style)
                else:
                    groups.append((char,run_style))
            for text, run_style in groups:
                family = run_style.get("fontFamily", "思源黑体") + ", " + FONT
                decoration = " ".join(name for key,name in (("underline","underline"),("strikethrough","line-through")) if run_style.get(key) == "true") or "none"
                line_parts.append(f'<tspan font-family="{esc(family)}" font-size="{parse_float(run_style.get("fontSize"),14):g}" '
                             f'fill="{esc(rgba_to_hex(run_style.get("color")))}" font-weight="{"bold" if run_style.get("bold") == "true" else "normal"}" '
                             f'font-style="{"italic" if run_style.get("italic") == "true" else "normal"}" text-decoration="{decoration}">{esc(text)}</tspan>')
            parts.append("".join(line_parts+["</text>"]))
            top += heights[index]
        return "\n".join(parts+["</g>"])

    def shape(self, elem):
        x,y,w,h = geometry(elem)
        kind = elem.get("type")
        if kind == "text":
            return self.text(elem)
        attrs = f'fill="{self.fill(elem)}"{self.border(elem)}'
        if kind in {"rect","round-rect"}:
            radius = parse_float(elem.get("radius",elem.get("presetHandlers")),min(16,h/2)) if kind == "round-rect" else 0
            return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{max(0,min(radius,h/2,w/2)):g}" {attrs}/>'
        if kind == "ellipse":
            return f'<ellipse cx="{x+w/2:g}" cy="{y+h/2:g}" rx="{w/2:g}" ry="{h/2:g}" {attrs}/>'
        if kind == "diamond":
            return f'<polygon points="{x+w/2:g},{y:g} {x+w:g},{y+h/2:g} {x+w/2:g},{y+h:g} {x:g},{y+h/2:g}" {attrs}/>'
        self.issue("unsupported_shape",f"Shape type {kind!r} is not rendered.",elem)
        return self.placeholder(elem,f"Unsupported shape: {kind}")

    def line(self, elem):
        """Render native SML absolute endpoints, preserving document paint order."""
        if elem.get("type", "straight-connector1") not in {"line", "straight-connector1"}:
            self.issue("unsupported_line", f"Line type {elem.get('type')!r} is not rendered.", elem)
            return self.placeholder(elem, "Unsupported line")
        points = [parse_float(elem.get(key), None) for key in LINE_ENDPOINTS]
        if any(value is None for value in points):
            self.issue("invalid_line_geometry", "Line requires four finite startX/startY/endX/endY coordinates.", elem, "error")
            return self.placeholder(elem, "Invalid line endpoints")
        x1, y1, x2, y2 = points
        dx, dy = x2-x1, y2-y1
        length = math.hypot(dx, dy)
        if not math.isfinite(length) or length == 0:
            self.issue("invalid_line_geometry", "Line endpoints must define a finite, nonzero-length line.", elem, "error")
            return self.placeholder(elem, "Invalid line endpoints")
        border = find(elem, "border")
        if border is None:
            self.issue("missing_line_border", "Native SML line requires a border element.", elem, "error")
            return self.placeholder(elem, "Missing line border")
        width = parse_float(border.get("width"), 2.0 if border.get("width") is None else None)
        alpha = parse_float(elem.get("alpha"), 1 if elem.get("alpha") is None else None)
        if width is None or width < 0 or not width.is_integer() or alpha is None or not 0 <= alpha <= 1:
            self.issue("invalid_line_style", "Line border width must be a nonnegative integer; alpha must be between 0 and 1.", elem, "error")
            return self.placeholder(elem, "Invalid line style")
        color = esc(rgba_to_hex(border.get("color", "rgba(43, 47, 54, 1)")))
        parts = [f'<g data-preview-line="true" opacity="{alpha:g}">',
                 f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" fill="none" stroke="{color}" stroke-width="{width:g}"/>']
        for child, position, tip, direction in (("startArrow", "start", (x1, y1), (-dx/length, -dy/length)),
                                                 ("endArrow", "end", (x2, y2), (dx/length, dy/length))):
            arrow = find(elem, child)
            if arrow is not None:
                parts.append(self.line_arrow(arrow, position, tip, direction, width, color))
        return "\n".join(parts+["</g>"])

    def line_arrow(self, elem, position, tip, direction, width, color):
        """Approximate basic/filled triangle arrow sizes in the line's direction."""
        kind = elem.get("type", "none")
        if kind == "none":
            return ""
        if kind not in {"arrow", "solid-triangle"}:
            self.issue("unsupported_arrow", f"Arrow type {kind!r} is not rendered.", elem)
            return ""
        scales = {"sm": 3, "med": 4, "lg": 5}
        sizes = []
        for key in ("heightScale", "widthScale"):
            scale = elem.get(key, "med")
            if scale not in scales:
                self.issue("unsupported_attribute_value", f"<{local_name(elem.tag)}> {key}={scale!r} uses medium arrow size.", elem)
            sizes.append(scales.get(scale, scales["med"])*width)
        if width == 0:
            return ""
        arrow_length, arrow_width = sizes
        x, y = tip
        ux, uy = direction
        bx, by = x-ux*arrow_length, y-uy*arrow_length
        left = (bx-uy*arrow_width/2, by+ux*arrow_width/2)
        right = (bx+uy*arrow_width/2, by-ux*arrow_width/2)
        attrs = f'data-preview-arrow="{position}" stroke="{color}" stroke-width="{width:g}" stroke-linejoin="round"'
        if kind == "solid-triangle":
            return f'<polygon {attrs} points="{x:g},{y:g} {left[0]:g},{left[1]:g} {right[0]:g},{right[1]:g}" fill="{color}"/>'
        return f'<path {attrs} d="M {left[0]:g},{left[1]:g} L {x:g},{y:g} L {right[0]:g},{right[1]:g}" fill="none"/>'

    def image(self, elem):
        src = elem.get("src", "")
        path = Path(src[1:] if src.startswith("@") else src)
        candidates = [path] if path.is_absolute() else [self.base_dir/path,self.assets_dir/path]
        full = next((candidate for candidate in candidates if candidate.is_file()),None)
        if not src or "://" in src or full is None:
            self.issue("missing_image",f"Image {src!r} is unavailable; searched XML directory then {self.assets_dir}. Remote URLs/tokens are not fetched.",elem,"error")
            return self.placeholder(elem,"Missing image / 缺图")
        mime = {".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".gif":"image/gif",".webp":"image/webp",".svg":"image/svg+xml"}.get(full.suffix.lower())
        if mime is None:
            self.issue("unsupported_image",f"Image format {full.suffix!r} is unsupported; use PNG, JPEG, GIF, WebP or SVG.",elem,"error")
            return self.placeholder(elem,"Unsupported image format")
        try:
            encoded = base64.b64encode(full.read_bytes()).decode("ascii")
        except OSError as exc:
            self.issue("image_read_error",f"Cannot read image {src!r}: {exc}",elem,"error")
            return self.placeholder(elem,"Unreadable image")
        x,y,w,h = geometry(elem)
        return f'<image href="data:{mime};base64,{encoded}" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" preserveAspectRatio="xMidYMid meet"/>'

    def table(self, elem):
        x,y,w,_ = geometry(elem)
        widths = [parse_float(col.get("width"),100) for col in children(find(elem,"colgroup"),"col")]
        parts = []
        for row in children(elem,"tr"):
            height = parse_float(row.get("height"),40)
            cells, cx = children(row,"td"), x
            for index,cell in enumerate(cells):
                width = widths[index] if index < len(widths) else w/max(1,len(cells))
                border = self.border(cell,default=' stroke="#DDDDDD" stroke-width="0.5"')
                parts.append(f'<rect x="{cx:g}" y="{y:g}" width="{width:g}" height="{height:g}" fill="{self.fill(cell)}"{border}/>')
                content = find(cell,"content")
                if content is not None:
                    copy = ET.fromstring(ET.tostring(content))
                    copy.attrib.setdefault("fontSize","12")
                    copy.attrib.setdefault("verticalAlign","middle")
                    shape = ET.Element("shape",{"topLeftX":str(cx+6),"topLeftY":str(y),"width":str(max(1,width-12)),"height":str(height)})
                    shape.append(copy)
                    parts.append(self.text(shape))
                cx += width
            y += height
        return "\n".join(parts)

    def chart(self, elem):
        x,y,w,h = geometry(elem)
        plots = children(find(elem,"chartPlotArea"),"chartPlot")
        kind = plots[0].get("type") if plots else None
        if len(plots) != 1 or kind not in {"column","line","pie"}:
            self.issue("unsupported_chart","Only one column, line or pie plot per chart is supported; combined plots are not rendered.",elem)
            return self.placeholder(elem,f"Unsupported chart: {kind}")
        categories_fields = children(find(elem,"chartData/dim1"),"chartField")
        fields = children(find(elem,"chartData/dim2"),"chartField")
        try:
            if len(categories_fields) != 1 or not fields:
                raise ValueError("Chart requires one category field and at least one numeric series")
            categories = next(csv.reader(["".join(categories_fields[0].itertext())]))
            series = [(field.get("name",""),[float(v.strip()) for v in next(csv.reader(["".join(field.itertext())]))]) for field in fields]
            if not categories or any(len(values) != len(categories) for _,values in series):
                raise ValueError("Chart category and series lengths must match")
            if not all(math.isfinite(v) for _,values in series for v in values):
                raise ValueError("Chart values must be finite numbers")
            if kind == "pie" and (len(series) != 1 or min(series[0][1]) < 0 or sum(series[0][1]) <= 0):
                raise ValueError("Pie requires one nonnegative series with a positive total")
            if w < 80 or h < 60:
                raise ValueError("Chart box must be at least 80 × 60 for this preview")
        except (ValueError,StopIteration) as exc:
            self.issue("invalid_chart_data",str(exc),elem,"error")
            return self.placeholder(elem,"Invalid chart data")
        colors = [rgba_to_hex(c.get("value")) for c in children(find(elem,"chartStyle/chartColorTheme"),"color")]
        colors = colors or ["#FF5A5F","#589EF7","#2BC9D1","#A66BEA","#F6B73C"]
        parts = [f'<g data-preview-chart="{kind}" transform="translate({x:g} {y:g})">']
        background = find(elem,"chartStyle/chartBackground")
        bg = rgba_to_hex(background.get("color")) if background is not None else "none"
        border = self.border(find(elem,"chartStyle"),"chartBorder")
        parts.append(f'<rect width="{w:g}" height="{h:g}" fill="{bg}"{border}/>')
        legend = find(elem,"chartLegend")
        labels = categories if kind == "pie" else [name for name,_ in series]
        legend_size = parse_float(legend.get("fontSize"),11) if legend is not None else 11
        rows, row, row_width = [], [], 0
        if legend is not None:
            for index,label in enumerate(labels):
                iw = 22+sum(glyph_width(c,{"fontSize":str(legend_size)}) for c in label)
                if row and row_width+iw > w-12:
                    rows.append((row,row_width))
                    row,row_width = [],0
                row.append((index,label,iw))
                row_width += iw
            if row:
                rows.append((row,row_width))
        legend_h = len(rows)*(legend_size+9)
        if legend_h > h-50:
            self.issue("chart_legend_overflow", "Legend leaves insufficient plot space; enlarge the chart or shorten labels.", elem, "error")
            return self.placeholder(elem,"Chart legend exceeds box")
        if kind == "pie":
            radius = min(w/2-12,(h-legend_h)/2-10)
            cx,cy,total,angle = w/2,(h-legend_h)/2,sum(series[0][1]),-math.pi/2
            for index,value in enumerate(series[0][1]):
                sweep = value/total*2*math.pi
                if value == 0:
                    continue
                color = colors[index%len(colors)]
                title = f"{categories[index]}: {value:g} ({value/total:.1%})"
                if math.isclose(sweep,2*math.pi):
                    parts.append(f'<circle data-chart-mark="slice" cx="{cx:g}" cy="{cy:g}" r="{radius:g}" fill="{color}"><title>{esc(title)}</title></circle>')
                else:
                    start = (cx+radius*math.cos(angle),cy+radius*math.sin(angle))
                    end = (cx+radius*math.cos(angle+sweep),cy+radius*math.sin(angle+sweep))
                    parts.append(f'<path data-chart-mark="slice" d="M {cx:g},{cy:g} L {start[0]:g},{start[1]:g} A {radius:g},{radius:g} 0 {int(sweep>math.pi)} 1 {end[0]:g},{end[1]:g} Z" fill="{color}" stroke="#FFFFFF" stroke-width="1"><title>{esc(title)}</title></path>')
                mid = angle+sweep/2
                if value/total >= 0.06:
                    parts.append(f'<text x="{cx+radius*.67*math.cos(mid):g}" y="{cy+radius*.67*math.sin(mid)+4:g}" text-anchor="middle" font-size="12" fill="#171717">{value/total:.0%}</text>')
                angle += sweep
        else:
            left,top,pw,ph = 42,12,w-54,h-42-legend_h
            values = [value for _,numbers in series for value in numbers]
            low,high = min(0,min(values)),max(0,max(values))
            if low == high:
                high = low+1
            high += (high-low)*.08
            py = lambda value: top+ph*(high-value)/(high-low)
            axes = children(find(elem,"chartPlotArea/chartAxes"),"chartAxis")
            ya = next((axis for axis in axes if axis.get("type") == "y"),None)
            xa = next((axis for axis in axes if axis.get("type") == "x"),None)
            ylabel,xlabel = find(ya,"chartLabel"),find(xa,"chartLabel")
            yfs = parse_float(ylabel.get("fontSize"),10) if ylabel is not None else 10
            xfs = parse_float(xlabel.get("fontSize"),10) if xlabel is not None else 10
            yc = rgba_to_hex(ylabel.get("color","#696970")) if ylabel is not None else "#696970"
            xc = rgba_to_hex(xlabel.get("color","#696970")) if xlabel is not None else "#696970"
            grid = find(ya,"chartGridLine")
            gc = rgba_to_hex(grid.get("color")) if grid is not None else "#DDDDDD"
            gw = parse_float(grid.get("width"),.5) if grid is not None else .5
            for tick in range(5):
                value = low+(high-low)*tick/4
                yy = py(value)
                parts.append(f'<line x1="{left}" y1="{yy:g}" x2="{left+pw:g}" y2="{yy:g}" stroke="{gc}" stroke-width="{gw:g}"/>')
                parts.append(f'<text x="{left-6}" y="{yy+3:g}" text-anchor="end" font-size="{yfs:g}" fill="{yc}">{value:.3g}</text>')
            parts.append(f'<line x1="{left}" y1="{py(0):g}" x2="{left+pw:g}" y2="{py(0):g}" stroke="#999999"/>')
            step = pw/len(categories)
            xs = [left+step*(i+.5) for i in range(len(categories))]
            for index,label in enumerate(categories):
                parts.append(f'<text x="{xs[index]:g}" y="{top+ph+17:g}" text-anchor="middle" font-size="{xfs:g}" fill="{xc}">{esc(label)}</text>')
            for si,(name,numbers) in enumerate(series):
                color = colors[si%len(colors)]
                if kind == "column":
                    bw = step*.72/len(series)
                    for index,value in enumerate(numbers):
                        bx = xs[index]-step*.36+si*bw
                        parts.append(f'<rect data-chart-mark="bar" x="{bx:g}" y="{min(py(value),py(0)):g}" width="{bw*.92:g}" height="{abs(py(value)-py(0)):g}" fill="{color}"><title>{esc(name)} / {esc(categories[index])}: {value:g}</title></rect>')
                else:
                    points = " ".join(f"{xx:g},{py(value):g}" for xx,value in zip(xs,numbers))
                    parts.append(f'<polyline data-chart-mark="line" points="{points}" fill="none" stroke="{color}" stroke-width="2.5"/>')
                    for index,value in enumerate(numbers):
                        parts.append(f'<circle data-chart-mark="point" cx="{xs[index]:g}" cy="{py(value):g}" r="3.5" fill="{color}"><title>{esc(name)} / {esc(categories[index])}: {value:g}</title></circle>')
        for ri,(row,row_width) in enumerate(rows):
            lx,ly = max(6,(w-row_width)/2),h-legend_h+ri*(legend_size+9)+legend_size
            for index,label,iw in row:
                parts.append(f'<rect x="{lx:g}" y="{ly-8:g}" width="8" height="8" fill="{colors[index%len(colors)]}"/><text x="{lx+12:g}" y="{ly:g}" font-size="{legend_size:g}" fill="#48484E">{esc(label)}</text>')
                lx += iw
        return "\n".join(parts+["</g>"])

    def render(self):
        root = ET.parse(self.xml_path).getroot()
        if local_name(root.tag) != "slide" or find(root,"data") is None:
            raise ValueError("Expected a <slide> root with a <data> child")
        self.audit(root)
        width,height = parse_float(root.get("width"),W),parse_float(root.get("height"),H)
        if width <= 0 or height <= 0:
            raise ValueError("Slide dimensions must be positive")
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" viewBox="0 0 {width:g} {height:g}" data-preview-approximate="true">',
                 f'<title>{esc(self.xml_path.stem)} — 近似预览 / Approximate preview</title>',f'<desc>{esc(APPROXIMATION)}</desc>',
                 f'<rect width="{width:g}" height="{height:g}" fill="{self.fill(find(root,"style"))}"/>']
        for elem in find(root,"data"):
            method = {"shape":self.shape,"line":self.line,"img":self.image,"table":self.table,"chart":self.chart}.get(local_name(elem.tag))
            parts.append(method(elem) if method else self.placeholder(elem,f"Unsupported: {local_name(elem.tag)}"))
        parts.append(f'<text x="{width-8:g}" y="{height-3:g}" text-anchor="end" font-family="{FONT}" font-size="8" fill="#696970">近似预览 · 以飞书截图为准</text>')
        parts.append("<metadata>"+esc(json.dumps({"approximate":True,"issues":self.issues},ensure_ascii=False))+"</metadata>")
        return "\n".join(parts+["</svg>"])


def xml_to_svg(xml_path, out_path=None, *, assets_dir=None, diagnostics=None):
    """Compatible string-returning API; collect issues explicitly or emit to stderr."""
    renderer = Renderer(xml_path,assets_dir=assets_dir,diagnostics=diagnostics)
    svg = renderer.render()
    if out_path is not None:
        output = Path(out_path)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(svg,encoding="utf-8")
    if diagnostics is None:
        for issue in renderer.issues:
            print(f"{xml_path}: {issue['severity']}: {issue['code']}: {issue['message']}",file=sys.stderr)
    return svg


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input",type=Path,help="One SML XML slide")
    source.add_argument("--dir",type=Path,help="Directory of XML slides (non-recursive, any *.xml name)")
    parser.add_argument("--output-dir",type=Path,default=Path("preview-svg"),help="SVG output directory (default: ./preview-svg)")
    parser.add_argument("--assets-dir",type=Path,default=SKILL_ROOT/"assets",help="Fallback image root after the XML directory")
    parser.add_argument("--json",action="store_true",help="One JSON report on stdout, without mixed log output")
    args = parser.parse_args(argv)
    files = [args.input] if args.input else sorted(args.dir.glob("*.xml"))
    results = []
    if not files:
        results.append({"file":str(args.dir),"output":None,"issues":[{"severity":"error","code":"input_error","element":"slide","message":"Input directory does not exist or contains no XML files."}]})
    for xml_path in files:
        issues = []
        output = args.output_dir/(xml_path.stem+".svg")
        try:
            xml_to_svg(xml_path,output,assets_dir=args.assets_dir,diagnostics=issues)
        except (OSError,ET.ParseError,ValueError) as exc:
            issues.append({"severity":"error","code":"input_or_output_error","element":"slide","message":str(exc)})
            output = None
        results.append({"file":str(xml_path.resolve()),"output":str(output.resolve()) if output else None,"issues":issues})
    errors = sum(issue["severity"] == "error" for result in results for issue in result["issues"])
    warnings = sum(issue["severity"] == "warning" for result in results for issue in result["issues"])
    report = {"tool":"xml2svg","approximate":True,"passed":errors == 0,
              "summary":{"files":len(results),"errors":errors,"warnings":warnings},"results":results}
    if args.json:
        print(json.dumps(report,ensure_ascii=False,indent=2))
    else:
        for result in results:
            for issue in result["issues"]:
                print(f"{result['file']}: {issue['severity']}: {issue['code']}: {issue['message']}",file=sys.stderr)
        print(f"近似预览：{sum(result['output'] is not None for result in results)} SVG；{errors} errors, {warnings} warnings. Final visual acceptance requires Feishu screenshots.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
