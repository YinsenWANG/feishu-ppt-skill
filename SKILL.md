---
name: feishu-ppt-skill
description: 使用本地 XML 模板创建或编辑飞书/Lark 幻灯片，支持内容替换、近似预览、排版与主题校验。适用于飞书演示文稿或明确要求套用本库的任务；默认提供 Cherry Studio 主题，不承担通用海报或本地 PowerPoint 文件生成。
license: MIT
metadata:
  version: "2.0.0"
  platforms: [macos, linux, windows]
  hermes:
    tags: [feishu, lark, slides, ppt, cherry-studio, 模板, 幻灯片]
---

# Feishu PPT Skill

用 51 页原生飞书 XML 模板制作可编辑的演示文稿。默认主题为 Cherry Studio；用户指定的品牌、页数、内容、已有设计和交付形式优先。用户只要求检查或修改少量内容时，按该范围处理。

## 选择工作路径

- **新建或新增页面**：按下方模板流程准备本地稿。
- **编辑现有飞书稿件**：先读 [references/cli-workflow.md](references/cli-workflow.md) 的更新流程，保留线上页面和元素 ID；不要拿模板覆盖整页。
- **只检查/预览 XML**：直接运行统一校验或预览，不需要飞书登录。
- **调整主题或特殊版式**：读 [references/theme.md](references/theme.md)。图表、表格等 SML 结构以当前 CLI 提供的官方 schema 为准。

脚本和资源路径相对于本 skill 的实际安装目录。以下命令从该目录运行；在别处运行时给脚本绝对路径，并明确工作文件和资源目录。

## 内容准备与模板选择

1. 从用户材料提炼每页要表达的观点、数据和来源。缺失的关键数据标为待补，不能把模板示例当事实。
2. 在 [templates/INDEX.md](templates/INDEX.md) 搜索内容场景，只读取选中的模板。参考图仅用于选版。
3. 按内容数量、关系和阅读顺序选版：流程用步骤页、平级指标用网格、对比用双栏或表格。模板是默认起点，允许按实际需求调整。保持同一文稿的标题、页眉页脚和对齐节奏一致；封底是否需要以及总页数由任务决定。
4. 使用字段工具准备工作副本。首次生成草稿：

   ```bash
   python3 scripts/template_fields.py prepare --template slide19 --output-dir work/deck --allow-draft
   ```

   多页或重复模板使用 `--name page01`、`--name page02` 区分。阅读生成的字段提示，填写绑定 JSON，然后按 [references/template-authoring.md](references/template-authoring.md) 生成完整稿。字段索引覆盖正文、表格、图表数据与图片；标题、页码、年份和内部标注也要检查。
5. 用 XML 解析器或字段工具修改，保留未改段落的实体转义和富文本结构；字段工具按整段替换，具体格式处理见其说明。删除不需要的整个文本框，不能只清空文字。内容过长时优先精简、拆页或换模板，再调整版式。

## 环境与统一验收

首次使用或环境变更时运行：

```bash
python3 scripts/preflight.py --json
# 需要飞书操作时再检查 CLI 命令能力（只执行 version/help）
python3 scripts/preflight.py --check-cli --json
```

需要 Python 3.10+ 及 `requirements.txt` 中依赖。schema 获取、报告语义和完整验收说明见 [references/validation.md](references/validation.md)。

```bash
# 本地检查：缺少官方 schema 时，报告明确标为未运行 schema
python3 scripts/validate.py --dir work/deck --json
# 完整静态检查：schema 路径来自当前 CLI，不能假定其他 skill 带 xml_lint.py
python3 scripts/validate.py --dir work/deck --schema work/slides-schema.xsd --require-schema --json
# 近似 SVG 预览，不会发布
python3 scripts/xml2svg.py --dir work/deck --output-dir work/preview --assets-dir work/deck
```

- **error**：修复后再继续。包括缺文件、非法 XML、缺本地图片、主题冲突等。
- **warning**：逐项复核并记录判断。文本尺寸与自动缩放是静态估算，不能用“0 error”代替实际查看。自动化需要警告阻断时加 `--strict-warnings`。
- **内容检查**：逐页核对正文、数字来源、图表分类与数值、表格行列、联系方式、未替换示例；字段稿不能冒充完成稿。
- **渲染检查**：SVG 是近似预览。可用飞书 `+screenshot --content` 预览本地 XML；创建/更新后回读并看真实截图，确认没有缺图、溢出、空白或内部标注。

## 创建、更新与交付

需要飞书写入时读 [references/cli-workflow.md](references/cli-workflow.md)，使用与目标资源一致的身份。CLI 能力由本机 `--help` 确认；当前文档核对版本为 1.0.86，不自动升级或切换 profile。

更新前保留上次线上回读基线，比较 baseline/working/remote。没有基线、缺 ID、双方改同一块或顺序冲突时，先读清线上状态并解决冲突。整页更新的旧 revision 可能覆盖后续编辑，不能把它视为通用乐观锁。

完成后交付演示文稿链接或用户要求的本地文件，并简述页数、检查结果和仍需处理的事项。没有执行线上操作或真实渲染时明确说明；不要声称“已发布”或“完全还原”。

异常处理按 [references/cli-workflow.md](references/cli-workflow.md) 的回读和有限重试策略，不盲目重复创建。
