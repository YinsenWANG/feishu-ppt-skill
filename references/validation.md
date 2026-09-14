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

报告的 summary 提供 files/errors/warnings；results 每项包含 file 和 issues，issue 含 level/code/message/element/stage。JSON 模式标准输出只有 JSON。错误始终使退出码非零；默认 warning 不阻断，但 status 为 needs_review；加 strict-warnings 后警告也阻断。

`schema.status=not_run` 表示只做了本地排版和主题检查，不代表完整静态验收。`render_verified` 与 `content_verified` 始终为 false，因为脚本无法证明已看过飞书截图或核实过数据。外部流程必须保留这些状态，不能只看退出码就宣布完成。

单独调用 review_layout.py / review_design.py 仍可用于定位问题，其报告遵循相同错误语义。

## 正式交付的五项验收

1. schema、布局、主题检查：error 清零，warning 有逐项复核结果。
2. 内容：没有未完成字段、Internal Template、版式标签和示例邮箱/数据；年份、页码、结论、图表与表格逐页核对。
3. 渲染：看真实飞书截图，确认字体、换行、图表、图片和空文本框。SVG 仅作为近似辅助预览。
4. 回读：核对线上页数、顺序、标题、图片和本次必要修改，保存新的回读 XML 与版本信息供下次比较。
5. 视觉：按主题中的精修标准查看每个目标页面，复查字重、信息主次、内容分组、留白与整稿节奏，记录具体问题及处理结果。

## 图表近似预览的范围

柱状图与折线图支持左侧数值 Y 轴整数 min/max；柱状图支持全局柱色、像素宽度、组内间距比例与柱外数值标签。轴和数据标签的数字格式仅支持默认值或整数 `format="0"`，轴标签支持水平 `angle="0"`。分类 X 轴范围、系列级覆盖和其他标签组合仍会告警；单系列同时指定柱宽与间距时，保持均匀分类中心，间距效果属于近似。

饼图标签的原生自动排布尚未完整复刻。实测飞书会在标签四项布尔全部 false 时恢复默认百分比，也可能忽略透明标签颜色；不能据此隐藏重复标签。本地隐藏会发出 `native_label_visibility_unverified`。优先使用清楚的短分类与原生外侧标签，实际截图确认小比例读数不重叠、不截断；旁侧文字只补充必要的说明。

## 常见模板警告如何复核

| 警告 | 含义与复核方式 |
| --- | --- |
| text_overflow_wrap | 静态模型按字号和行距估算总高，可能超过模板文本框；normal-auto-fit、真实字形和行距行为会影响结果。查看完整标题、尾行和相邻元素，必要时精简或增大文本区域。 |
| accent_overuse | 同页实际使用的强调色超过当前主题建议。多指标卡、时间线和饼图可能有合理的语义分色；确认颜色有对应含义、没有抢占主要信息。图表候选色板中未使用的色不计入。 |
| font_hierarchy_too_many | 字号种类超过主题建议。核对是否确有标题、数字、卡片正文、标签和页脚等角色；合并没有意义的近似字号。 |
| chart_smoothing_approximation（预览器） | SVG 用直线连接代替飞书平滑曲线。数值与数据点仍保留；曲线细节以飞书截图为准。 |

这些说明帮助重复复核，不自动豁免所有同类警告。更换文字和数据后仍重新检查；报告保留 needs_review，真实截图未查看时不能把预览检查升级成渲染验收。

## 验证本库

```bash
python3 -m unittest discover -s tests -v
python3 scripts/template_fields.py index --check
python3 scripts/validate.py --dir templates --json
python3 scripts/xml2svg.py --dir templates --output-dir work/preview
```

CI 运行离线回归与模板检查；外部 schema 和线上渲染是独立验证阶段，不把 CI 通过等同为线上验收。保留静态估算警告，避免为追求零警告而随意改坏正常版式。
