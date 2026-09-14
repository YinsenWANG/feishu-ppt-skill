"""Behavioral tests for approximate previews, independent of Feishu services."""
import base64
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "xml2svg.py"
spec = importlib.util.spec_from_file_location("preview", SCRIPT)
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
SVG = "{http://www.w3.org/2000/svg}"


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def render(self, content, namespace="", assets_dir=None):
        xml = self.folder / "example.xml"
        xml.write_text(f'<slide {namespace}><data>{content}</data></slide>', encoding="utf-8")
        issues = []
        result = preview.xml_to_svg(xml, assets_dir=assets_dir, diagnostics=issues)
        return ET.fromstring(result), issues

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str,args)], cwd=self.folder, text=True, capture_output=True)

    def test_namespace_equivalence_and_rich_text_preservation(self):
        body = ('<shape type="text" width="500" height="90"><content fontSize="20" color="#171717">'
                '<p>开头<span bold="true" color="rgb(255, 90, 95)">加粗<span italic="true">嵌套</span>尾</span>结尾 &amp; 完毕</p>'
                '<p textAlign="right">下一行<br/>换行后</p></content></shape>')
        outputs = []
        for ns in ('', 'xmlns="https://www.larkoffice.com/sml/2.0"'):
            tree, issues = self.render(body, ns)
            lines = tree.findall(f'.//{SVG}g[@data-preview-text="true"]/{SVG}text')
            texts = ["".join(line.itertext()) for line in lines]
            self.assertEqual(texts, ["开头加粗嵌套尾结尾 & 完毕", "下一行", "换行后"])
            self.assertEqual(lines[1].get("text-anchor"), "end")
            spans = lines[0].findall(f"{SVG}tspan")
            self.assertEqual(spans[1].get("font-weight"), "bold")
            self.assertEqual(spans[1].get("fill"), "#FF5A5F")
            self.assertEqual(spans[2].get("font-style"), "italic")
            self.assertEqual(issues, [])
            outputs.append(texts)
        xml = self.folder / "prefix.xml"
        xml.write_text('<s:slide xmlns:s="https://www.larkoffice.com/sml/2.0"><s:data>'+re.sub(r'(<\/?)([A-Za-z][\w]*)',r'\1s:\2',body)+'</s:data></s:slide>')
        tree = ET.fromstring(preview.xml_to_svg(xml, diagnostics=[]))
        self.assertEqual(["".join(e.itertext()) for e in tree.findall(f'.//{SVG}g[@data-preview-text="true"]/{SVG}text')], outputs[0])

    def test_wrapping_alignment_and_no_autofit(self):
        tree, issues = self.render('<shape type="text" topLeftX="10" topLeftY="20" width="40" height="100"><content fontSize="20" textAlign="center" verticalAlign="middle" autoFit="normal-auto-fit"><p>甲乙丙丁</p></content></shape>')
        lines = tree.findall(f'.//{SVG}g[@data-preview-text="true"]/{SVG}text')
        self.assertEqual(["".join(line.itertext()) for line in lines], ["甲乙","丙丁"])
        self.assertTrue(all(line.get("x") == "30" for line in lines))
        self.assertEqual(lines[0].find(f"{SVG}tspan").get("font-size"), "20")
        self.assertGreater(float(lines[0].get("y")), 37)
        self.assertEqual(issues, [])

    def test_table_retains_direct_and_rich_text(self):
        tree, _ = self.render('<table width="200"><colgroup><col width="200"/></colgroup><tr height="60"><td><content fontSize="14"><p>表格<span bold="true">内容</span>尾</p><p>第二行</p></content></td></tr></table>')
        lines = tree.findall(f'.//{SVG}g[@data-preview-text="true"]/{SVG}text')
        self.assertEqual(["".join(line.itertext()) for line in lines], ["表格内容尾","第二行"])

    def test_native_line_preserves_endpoints_defaults_and_paint_order(self):
        body = ('<line startX="120.5" startY="90" endX="35" endY="210" alpha="0.6"><border/></line>'
                '<shape type="ellipse" topLeftX="20" topLeftY="180" width="30" height="60"/>')
        for namespace in ('', 'xmlns="https://www.larkoffice.com/sml/2.0"'):
            with self.subTest(namespace=namespace):
                tree, issues = self.render(body, namespace)
                group = tree.find(f'{SVG}g[@data-preview-line="true"]')
                line = group.find(f'{SVG}line')
                self.assertEqual([float(line.get(k)) for k in ("x1", "y1", "x2", "y2")], [120.5, 90, 35, 210])
                self.assertEqual(line.get("stroke"), "#2B2F36")
                self.assertEqual(line.get("stroke-width"), "2")
                self.assertEqual(group.get("opacity"), "0.6")
                self.assertLess(list(tree).index(group), list(tree).index(tree.find(f'{SVG}ellipse')))
                self.assertEqual(issues, [])

    def test_arrowheads_follow_both_endpoints_in_all_directions(self):
        for end in ((150, 100), (50, 100), (100, 150), (100, 50), (140, 160), (40, 70)):
            with self.subTest(end=end):
                body = (f'<line type="line" startX="100" startY="100" endX="{end[0]}" endY="{end[1]}">'
                        '<border color="rgba(255, 90, 95, 1)" width="2"/>'
                        '<startArrow type="solid-triangle" widthScale="sm" heightScale="sm"/>'
                        '<endArrow type="solid-triangle" widthScale="lg" heightScale="lg"/></line>')
                tree, issues = self.render(body)
                arrows = {e.get("data-preview-arrow"): e for e in tree.findall(f'.//{SVG}polygon[@data-preview-arrow]')}
                self.assertEqual(set(arrows), {"start", "end"})
                lengths = {}
                for position, tip, direction in (("start", (100, 100), (100-end[0], 100-end[1])),
                                                  ("end", end, (end[0]-100, end[1]-100))):
                    points = [tuple(map(float, pair.split(","))) for pair in arrows[position].get("points").split()]
                    self.assertEqual(points[0], tip)
                    midpoint = tuple((points[1][i]+points[2][i])/2 for i in (0, 1))
                    back = (midpoint[0]-tip[0], midpoint[1]-tip[1])
                    self.assertLess(sum(back[i]*direction[i] for i in (0, 1)), 0)
                    self.assertAlmostEqual(back[0]*direction[1]-back[1]*direction[0], 0, delta=0.1)
                    lengths[position] = math.hypot(*back)
                    self.assertEqual(arrows[position].get("fill"), "#FF5A5F")
                self.assertGreater(lengths["end"], lengths["start"])
                self.assertEqual(issues, [])

    def test_basic_none_and_unsupported_arrowheads_are_explicit(self):
        tree, issues = self.render('<line startX="0" startY="0" endX="20" endY="30"><border/>'
                                  '<startArrow type="none"/><endArrow type="arrow"/></line>')
        arrow = tree.find(f'.//{SVG}path[@data-preview-arrow="end"]')
        self.assertIsNotNone(arrow)
        self.assertEqual(arrow.get("fill"), "none")
        self.assertEqual(issues, [])
        tree, issues = self.render('<line startX="0" startY="0" endX="20" endY="30"><border/>'
                                  '<endArrow type="empty-circle"/></line>')
        self.assertEqual([i["code"] for i in issues], ["unsupported_arrow"])
        self.assertIsNotNone(tree.find(f'.//{SVG}g[@data-preview-line="true"]/{SVG}line'))
        self.assertFalse([e for e in tree.iter() if e.get("data-preview-arrow")])

    def test_invalid_line_endpoints_are_not_silently_drawn(self):
        for attrs in ('startX="10" startY="20" endX="30"',
                      'startX="NaN" startY="20" endX="30" endY="40"',
                      'startX="10" startY="20" endX="inf" endY="40"',
                      'startX="10" startY="20" endX="10" endY="20"'):
            with self.subTest(attrs=attrs):
                tree, issues = self.render(f'<line {attrs}><border/></line>')
                self.assertTrue(any(i["code"] == "invalid_line_geometry" and i["severity"] == "error" for i in issues))
                self.assertIsNone(tree.find(f'.//{SVG}g[@data-preview-line="true"]'))

    def test_invalid_line_styles_and_zero_width(self):
        for children, attrs in (("", ""), ('<border width="-1"/>', ""),
                                ('<border width="NaN"/>', ""), ('<border width="1.5"/>', ""),
                                ('<border/>', 'alpha="2"'), ('<border/>', 'alpha="NaN"')):
            with self.subTest(children=children, attrs=attrs):
                tree, issues = self.render(f'<line startX="10" startY="20" endX="30" endY="40" {attrs}>{children}</line>')
                self.assertTrue(any(i["severity"] == "error" for i in issues))
                self.assertIsNone(tree.find(f'.//{SVG}g[@data-preview-line="true"]'))
        tree, issues = self.render('<line startX="0" startY="0" endX="20" endY="30"><border width="0"/>'
                                  '<endArrow type="solid-triangle"/></line>')
        self.assertEqual(issues, [])
        self.assertEqual(tree.find(f'.//{SVG}g[@data-preview-line="true"]/{SVG}line').get("stroke-width"), "0")
        self.assertFalse([e for e in tree.iter() if e.get("data-preview-arrow")])

    def test_cycle_template_keeps_native_connectors_under_nodes(self):
        for page in (28,):
            with self.subTest(page=page):
                source = ROOT / "templates" / f"slide{page}.xml"
                data = preview.find(ET.parse(source).getroot(), "data")
                lines = preview.children(data, "line")
                self.assertEqual(len(lines), 4)
                shapes = preview.children(data, "shape")
                nodes = [e for e in shapes if e.get("type") in {"round-rect", "ellipse"}]
                self.assertTrue(all(list(data).index(line) < min(list(data).index(node) for node in nodes) for line in lines))
                self.assertFalse([e for e in shapes if e.get("type") == "rect" and float(e.get("height", 20)) <= 3])
                centers = [(float(e.get("topLeftX"))+float(e.get("width"))/2,
                            float(e.get("topLeftY"))+float(e.get("height"))/2) for e in nodes]
                endpoints = [tuple(float(e.get(k)) for k in preview.LINE_ENDPOINTS) for e in lines]
                outer = centers[1:]
                edges = []
                for coords in endpoints:
                    pair = []
                    for point in (coords[:2], coords[2:]):
                        closest = min(range(len(outer)), key=lambda i: math.dist(point, outer[i]))
                        pair.append(closest)
                        cx, cy = outer[closest]
                        self.assertGreater(((point[0]-cx)/55)**2+((point[1]-cy)/36)**2, 1)
                    edges.append(tuple(pair))
                self.assertEqual(set(edges), {(0, 1), (1, 2), (2, 3), (3, 0)})
                issues = []
                tree = ET.fromstring(preview.xml_to_svg(source, diagnostics=issues))
                self.assertEqual(issues, [])
                self.assertEqual(len(tree.findall(f'{SVG}g[@data-preview-line="true"]')), 4)
                self.assertEqual(len(tree.findall(f'.//{SVG}polygon[@data-preview-arrow="end"]')), 4)

    def test_all_five_library_charts_have_real_marks(self):
        chart_types, marks = [], []
        for page in range(21,25):
            diagnostics = []
            tree = ET.fromstring(preview.xml_to_svg(ROOT / "templates" / f"slide{page}.xml", diagnostics=diagnostics))
            self.assertFalse(any(issue["severity"] == "error" for issue in diagnostics))
            charts = tree.findall(f'.//{SVG}g[@data-preview-chart]')
            chart_types.extend(chart.get("data-preview-chart") for chart in charts)
            marks.extend(e.get("data-chart-mark") for e in tree.iter() if e.get("data-chart-mark"))
            if page == 21:
                bars = tree.findall(f'.//{SVG}rect[@data-chart-mark="bar"]')
                heights = [float(bar.get("height")) for bar in bars]
                self.assertEqual(heights, sorted(heights))
                self.assertAlmostEqual(heights[-1]/heights[0], 46/18, places=4)
        self.assertEqual(chart_types, ["column","line","pie","column","line"])
        self.assertEqual(marks.count("bar"), 10)
        self.assertEqual(marks.count("line"), 2)
        self.assertEqual(marks.count("point"), 12)
        self.assertEqual(marks.count("slice"), 4)

    def test_all_templates_parse_with_images_and_approximation_label(self):
        paths = list((ROOT / "templates").glob("*.xml"))
        self.assertEqual(len(paths), 51)
        for path in paths:
            with self.subTest(path=path.name):
                issues = []
                tree = ET.fromstring(preview.xml_to_svg(path,diagnostics=issues))
                self.assertEqual(tree.get("data-preview-approximate"), "true")
                self.assertIn("Approximate preview",tree.find(f"{SVG}title").text)
                self.assertTrue(tree.findall(f".//{SVG}image"))
                self.assertTrue(all(i["code"] == "chart_smoothing_approximation" for i in issues),issues)

    def test_missing_image_is_visible_and_an_error(self):
        tree, issues = self.render('<img src="@./missing.png" width="100" height="40"/>')
        self.assertEqual(issues[0]["code"], "missing_image")
        self.assertEqual(issues[0]["severity"], "error")
        self.assertIsNotNone(tree.find(f'.//{SVG}g[@data-preview-placeholder="true"]'))
        result = self.cli("--input",self.folder/"example.xml","--output-dir",self.folder/"svg","--json")
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode,1)
        self.assertFalse(report["passed"])
        self.assertEqual(report["summary"]["errors"],1)
        self.assertEqual(result.stderr,"")

    def test_xml_relative_images_override_assets(self):
        assets = self.folder / "assets"
        assets.mkdir()
        # Bytes need not be decoded by this test: the source chosen is the behavior under test.
        (assets / "picture.png").write_bytes(b"fallback")
        (self.folder / "picture.png").write_bytes(b"local")
        tree, issues = self.render('<img src="@./picture.png"/>', assets_dir=assets)
        self.assertEqual(issues,[])
        href = tree.find(f".//{SVG}image").get("href")
        self.assertEqual(base64.b64decode(href.split(",")[1]),b"local")
        (self.folder / "picture.png").unlink()
        tree, issues = self.render('<img src="@./picture.png"/>', assets_dir=assets)
        self.assertEqual(base64.b64decode(tree.find(f".//{SVG}image").get("href").split(",")[1]),b"fallback")

    def test_cli_cross_cwd_uses_installed_assets(self):
        output = self.folder / "other" / "svg"
        result = self.cli("--input",ROOT/"templates"/"slide21.xml","--output-dir",output,"--json")
        self.assertEqual(result.returncode,0,result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"],{"files":1,"errors":0,"warnings":0})
        self.assertTrue((output/"slide21.svg").is_file())
        self.assertEqual(result.stderr,"")

    def test_cli_directory_accepts_non_slide_names(self):
        source = self.folder / "input"
        source.mkdir()
        (source/"custom.xml").write_text('<slide><data/></slide>')
        result = self.cli("--dir",source,"--output-dir",self.folder/"svg","--json")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((self.folder/"svg"/"custom.svg").exists())

    def test_input_failures_are_json_and_nonzero(self):
        for source in (self.folder/"missing.xml",self.folder/"bad.xml"):
            if source.name == "bad.xml":
                source.write_text('<broken')
            result = self.cli("--input",source,"--json")
            self.assertEqual(result.returncode,1)
            self.assertFalse(json.loads(result.stdout)["passed"])
        result = self.cli("--dir",self.folder/"nonexistent","--json")
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)["summary"]["errors"],1)

    def test_unknown_element_shape_and_attribute_are_reported(self):
        _, issues = self.render('<shape type="rect" rotation="30"/><shape type="star"/><video src="movie.mp4"/>')
        self.assertEqual({issue["code"] for issue in issues},{"unsupported_attribute","unsupported_shape","unsupported_element"})

    def test_invalid_chart_data_is_not_drawn_as_valid(self):
        for values in ("1", "1,nan", "a,2"):
            tree, issues = self.render('<chart width="200" height="100"><chartPlotArea><chartPlot type="column"/></chartPlotArea><chartData><dim1><chartField>A,B</chartField></dim1><dim2><chartField>'+values+'</chartField></dim2></chartData></chart>')
            self.assertEqual(issues[0]["code"],"invalid_chart_data")
            self.assertEqual(issues[0]["severity"],"error")
            self.assertFalse(tree.findall(f'.//{SVG}rect[@data-chart-mark="bar"]'))

    def test_rgb_rgba_and_transparency(self):
        self.assertEqual(preview.rgba_to_hex("rgb(255, 90, 95)"),"#FF5A5F")
        self.assertEqual(preview.rgba_to_hex("rgba(0, 0, 0, 0)"),"#00000000")
        self.assertEqual(preview.rgba_to_hex("#ABCD"),"#ABCD")

    def test_invalid_geometry_and_unsupported_color_are_explicit(self):
        _, issues = self.render('<shape type="rect" topLeftX="NaN" width="-2"><fill><fillColor color="hsl(0,100%,50%)"/></fill></shape>')
        self.assertEqual({issue["code"] for issue in issues},{"invalid_numeric_attribute","unsupported_color"})
        self.assertEqual(sum(issue["severity"] == "error" for issue in issues),2)

    def test_single_slice_pie_and_negative_columns(self):
        for kind,values,expected in (("pie","100,0","slice"),("column","-5,10","bar")):
            tree, issues = self.render(f'<chart width="200" height="120"><chartPlotArea><chartPlot type="{kind}"/></chartPlotArea><chartData><dim1><chartField>A,B</chartField></dim1><dim2><chartField>{values}</chartField></dim2></chartData></chart>')
            self.assertEqual(issues,[])
            marks = [e for e in tree.iter() if e.get("data-chart-mark") == expected]
            self.assertEqual(len(marks),1 if kind == "pie" else 2)
            if kind == "pie":
                self.assertEqual(marks[0].tag,f"{SVG}circle")
            else:
                self.assertTrue(all(float(mark.get("height")) > 0 for mark in marks))


if __name__ == "__main__":
    unittest.main()
