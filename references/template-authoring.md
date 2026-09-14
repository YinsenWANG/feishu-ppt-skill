# 字段化模板准备

## 选版与索引

`templates/INDEX.md` 用于按内容场景选版；`templates/fields.json` 记录字段路径、示例值、角色提示和源 XML 指纹。使用工具处理文本、图表数据、表格和图片，不依赖字符串全局替换。文本字段按完整段落替换，保留 p 属性，但不保留该段内各 span 的样式；需精细保留富文本时改用 XML 编辑。字段路径不是线上 block ID，不能用于替换飞书已有文稿。

模板修改后重建并检查索引：

```bash
python3 scripts/template_fields.py index --templates-dir templates --output templates/fields.json
python3 scripts/template_fields.py index --check
```

修改源 XML 后旧指纹应被拒绝。不要手动修改指纹以绕过旧字段映射检查。

## 创建与填写

```bash
python3 scripts/template_fields.py prepare --template slide19 --output-dir work/draft --allow-draft
```

打开生成的 `bindings.draft.json`，按字段提示填写 values。默认品牌字段可保留；正文、数据、年份、页码、联系方式和模板标注逐项处理。若某个示例值经核实确实适用于新稿，可为该字段填写 `{"value": "实际值", "confirmed": true}`；确认只是内容编辑决策，不代表数据已由工具核实。缺失真实素材或数据时保持草稿状态并明确待补项，不编造内容。

准备工具要求未完成字段被处理后才生成完成稿；草稿输出必须显式带 allow-draft。为避免覆盖编辑中的文件，把完成稿输出到新的目录：

```bash
python3 scripts/template_fields.py prepare --template slide19 --bindings work/draft/bindings.draft.json --output-dir work/final
```

查看 prepare-report.json 的状态和未完成字段。需要同目录重跑时先保存人工修改，只有明确要替换这些生成文件才用 --force。所有仍需的本地图片必须存在，并随 XML 复制到工作目录。

## 同一文稿中的多页与重复模板

多页准备时给每页独立输出名称，支持同一个模板重复使用：

```bash
python3 scripts/template_fields.py prepare --template slide19 --name page01 --output-dir work/draft --allow-draft
python3 scripts/template_fields.py prepare --template slide19 --name page02 --output-dir work/draft --allow-draft
```

对应产物为 `page01.xml`、`page01.bindings.draft.json`、`page01.prepare-report.json`（page02 同理）。填写各自绑定，再带同一个 `--name` 输出到最终目录，避免跨页套错内容。共享图片内容相同时复用，同名但内容不同的图片另存，不覆盖另一页资产。

报告的 `complete` 只表示字段绑定完成，`xml_sha256` 对应本次生成文件；文件后续改变时必须重新校验，不能沿用旧报告声称已完成验收。

## 审阅规则

- 字段角色和容量提示是辅助，需要 Agent 按整页语义检查，不能把填满字段当成好内容。
- 图表分类数量与各数列长度一致；比例、单位、时间范围和来源需要核实。
- 表格逐行回读，避免 A 行内容进入 B 行；调整行数后核对总高和列宽。
- 删除内容时删除无用文本 shape；空框不是合格的占位。
- 模板编号用于选版，交付页码按实际文稿顺序重新编号。
- 正式提交前运行 validate，并查看真实飞书截图。草稿预览不能代替内容核验。
