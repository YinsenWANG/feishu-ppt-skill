# 环境、验收与报告

## 安装与能力检查

使用同一个 Python 环境安装 `requirements.txt`，然后运行 `scripts/preflight.py`。它检查 Python、依赖、主题和资源；只有加 `--check-cli` 时执行 CLI 的 `--version` / `--help`，不会登录、切换 profile 或调用写接口。它验证命令和参数存在，不证明线上行为或身份权限正确。若系统有多个 CLI 安装，用 `--cli /actual/path/to/lark-cli` 检查选定版本，并在后续操作中使用同一个可执行文件；不要假定不同 shell 的 PATH 一致。

## 官方 schema

旧版要求依赖别的 skill 中的 xml_lint.py，但该文件并非所有版本都有。本库接受官方 XSD，不捆绑未注明来源的副本。当前已核对 CLI 1.0.86 提供以下资源：

```bash
mkdir -p work
lark-cli skills read lark-slides/references/xml/slides_xml_schema_definition.xml > work/slides-schema.xsd
python3 scripts/preflight.py --schema work/slides-schema.xsd --json
python3 scripts/validate.py --dir templates --schema work/slides-schema.xsd --require-schema --json
```

CLI 若不提供该路径，用 `lark-cli skills list lark-slides` 查当前资源位置；获取失败不能把错误 JSON 当 XSD 使用。报告记录 schema 路径与 SHA-256，便于复现。正式 SML schema 以 presentation 为根；校验器在内存中为单页 slide 添加同命名空间的 presentation 容器和画布尺寸，不修改输入文件或原 schema。命名空间不匹配会明确失败。

XML 解析和 XSD 验证不是飞书渲染器；行高、自动缩放、图表标签截断仍需实际截图。

50 页实测中，饼图的长英文分类在本地 SVG 完整显示，飞书截图却自动加省略号。遇到这种情况，使用有说明的短标签（如 TS / JS）或扩大图表区域，并重新截图确认所有分类和百分比完整；不能仅凭数据回读正确判为视觉通过。流程图还要检查连线确实连接了节点、方向正确、层级没有遮住文字。原生 `line` 使用端点坐标，静态检查会报告缺失、非有限、越界和零长端点。

## 一个统一入口

```bash
python3 scripts/validate.py --input work/deck/my-slide.xml --json
python3 scripts/validate.py --dir work/deck --schema work/slides-schema.xsd --require-schema --json
python3 scripts/validate.py --dir work/deck --strict-warnings --json
```

每个输入必须是单页 `<slide>`。整份 `<presentation>` 快照先按实际页面 ID 提取待编辑页面，参见更新流程。目录模式检查该目录下全部 `*.xml`，不递归。把 schema、基线和其他 XML 放在独立目录；可重复使用 `--input` 明确选择文件。资源或主题有特殊位置时，使用 `--assets-dir` / `--tokens`。

报告的 summary 提供 files/errors/warnings；results 每项包含 file 和 issues，issue 含 level/code/message/element/stage。JSON 模式标准输出只有 JSON。错误始终使退出码非零；默认 warning 不阻断，schema 已执行时 status 为 needs_review，schema 未执行时仍为 incomplete；加 strict-warnings 后警告也阻断。

`schema.status=not_run` 表示只做了本地排版和主题检查，不代表完整静态验收。`render_verified` 与 `content_verified` 始终为 false，因为脚本无法证明已看过飞书截图或核实过数据。外部流程必须保留这些状态，不能只看退出码就宣布完成。

单独调用 review_layout.py / review_design.py 仍可用于定位问题，其报告遵循相同错误语义。

## 正式交付的五项验收

1. schema、布局、主题检查：error 清零，warning 有逐项复核结果。
2. 内容：没有未完成字段、Internal Template、版式标签和示例邮箱/数据；年份、页码、结论、图表与表格逐页核对。
3. 渲染：看真实飞书截图，确认字体、换行、图表、图片和空文本框。SVG 仅作为近似辅助预览。
4. 回读：核对线上页数、顺序、标题、图片和本次必要修改，保存新的回读 XML 与版本信息供下次比较。
5. 视觉：按 [theme.md](theme.md) 的默认规则或用户指定的视觉方向查看每个目标页面，记录具体问题及处理结果；技术结果与设计判断分别记录。

## 视觉复核：整页、细节与原稿

“0 error / 0 warning”只说明自动检查结果，不证明设计已经完成。视觉复核依照任务指定风格进行；未指定时采用纯色、无光晕和投影的扁平版式，不能靠叠加装饰补足层次。

- **缩小看整页，再并排看同类页**：第一眼的重点明确，主图和正文的面积与信息量相称；没有空卡撑版面、大片无作用的留白或整页等权重灰块。标题、页脚和同级内容的尺度保持一致。
- **原尺寸看细节**：检查同列边界、文字基线、组内间距、图标笔画与实际视觉重量；分组已有浅底与间距时，检查描边是否多余，去掉后确认组别仍然清楚。放大图表读数，确认绘图区足够大、单位靠近数字、原生标签没有截断或重叠。删除容器后仍须检查标题与解释是否靠近。
- **对照原稿与材料**：事实、来源、备注和限定不丢失；记录实际改善，例如“说明移近组名”“统一轮廓图标”“扩大绘图区”。仅换色或加粗不能替代这项判断。真实图片不额外包仿 macOS 标题栏、控制圆点或模拟界面框，除非用户要求该场景。

发现问题后只重看受影响页面及必要的同类页面；整稿任务最终查看全部目标页。未执行真实飞书渲染时，将记录标为本地近似预览复核，不据此宣布线上渲染通过。

交付前后对比时，按页面记录实际变化与对应版本，核对图片确实来自标注的版本。没有改动的页面标明“本页未调整”；不要只换统一的“本轮”标题，让相同图片看起来像已经重做。整稿重制应给出全部目标页的具体改动和实际图，不能以少数样稿代替完整交付。

## 图表近似预览的范围

柱状图、横向条形图与折线图支持数值轴整数 min/max；横向条形图将数值轴沿水平方向绘制，保留零或负值基线。柱状图和条形图支持全局、系列及逐柱纯色覆盖、像素柱宽、组内间距比例与柱外数值标签。数据标签支持默认值、整数 `format="0"` 和一位小数 `format="0.0"`；轴标签仍仅支持默认值或整数格式，以及水平 `angle="0"`。分类轴范围、系列级标签覆盖、堆积条形图和其他不支持的组合仍会告警。单系列同时指定柱宽与间距时，保持均匀分类中心，间距效果属于近似。

文本内容的四向内边距参与近似宽高与对齐计算；表格未显式指定时使用官方默认的 8px。字体度量、自动缩放、表格及图表的最终布局仍以飞书实际截图为准。

横向条形图的中心白字标签即使符合 schema，也可能在实际飞书截图中消失。发现这种情况恢复外侧深色读数，不用本地预览支持来推断线上效果；保留截图作为渲染限制记录。

饼图标签的原生自动排布尚未完整复刻。实测飞书会在标签四项布尔全部 false 时恢复默认百分比，也可能忽略透明标签颜色；不能据此隐藏重复标签。本地隐藏会发出 `native_label_visibility_unverified`。优先使用清楚的短分类与原生外侧标签，实际截图确认小比例读数不重叠、不截断；旁侧文字只补充必要的说明。

## 常见模板警告如何复核

| 警告 | 含义与复核方式 |
| --- | --- |
| text_overflow_wrap | 静态模型按字号和行距估算总高，可能超过模板文本框；normal-auto-fit、真实字形和行距行为会影响结果。查看完整标题、尾行和相邻元素，必要时精简或增大文本区域。 |
| accent_overuse | 同页实际使用的强调色超过当前主题建议。多指标卡、时间线和饼图可能有合理的语义分色；确认颜色有对应含义、没有抢占主要信息。图表候选色板中未使用的色不计入。 |
| font_hierarchy_too_many | 字号种类超过主题建议。核对是否确有标题、数字、卡片正文、标签和页脚等角色；合并没有意义的近似字号。 |
| chart_smoothing_approximation（预览器） | SVG 用直线连接代替飞书平滑曲线。数值与数据点仍保留；曲线细节以飞书截图为准。 |

这些说明帮助复核，不自动豁免所有同类警告。更换文字和数据后仍重新检查；保留实际的 incomplete / needs_review 等状态，真实截图未查看时不能把预览检查升级成渲染验收。

## 验证本库

```bash
python3 -m unittest discover -s tests -v
python3 scripts/template_fields.py index --check
python3 scripts/validate.py --dir templates --json
python3 scripts/xml2svg.py --dir templates --output-dir work/preview
```

CI 运行离线回归与模板检查；外部 schema、线上渲染和视觉复核是独立阶段。保留静态估算警告，不为消除警告而改变正确的数据、降低可读性或打乱已有版式。
