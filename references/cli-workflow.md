# 飞书 CLI 与已有稿件更新

以下命令已与 **lark-cli 1.0.86 的 --help** 核对。其他版本先运行 preflight --check-cli；本库不自动升级 CLI。先确认当前身份与目标资源，用户资源通常显式 `--as user`，不要替用户切 profile。

## 本地预览与新建

从工作目录执行，图片的 `@./` 路径按 CLI 当前工作目录解析。保持 XML 与准备工具复制的图片在同一目录。1.0.86 的文件参数要求当前目录内的相对路径，例如 `--slide @./page01.xml`；绝对路径会在参数校验阶段被拒绝。`--output` 等路径也按当前 CLI 的限制处理。

提交单页时，文件应直接从 `<slide>` 开始，不含 `<?xml ...?>` 声明。1.0.86 的 `+create --slide` 会在参数校验阶段拒绝该声明，即使文件通过 XML schema 校验；`template_fields.py prepare` 已按此格式输出。

```bash
# 直接渲染本地 XML；需要当前 CLI 的身份与渲染服务
lark-cli slides +screenshot --content @./slide01.xml --output-dir ./screenshots --as user
# 新建并导入；最多 10 页，按 --slide 的顺序
lark-cli slides +create --title "演示标题" --slide @./slide01.xml --slide @./slide19.xml --as user
# 已确认创建成功后再为同一演示文稿追加
lark-cli slides +add-slide --presentation "$PID" --slide @./slide51.xml --as user
# 保存原始回读，保留 ID
lark-cli slides +xml-get --presentation "$PID" --output ./baseline.xml --as user
lark-cli slides +screenshot --presentation "$PID" --slide-number 1 --as user
```

PID、SID、REV 来自实际成功响应或回读，不由模板编号推导。解析工具返回的业务错误和 `ok`，不能只靠进程成功码。创建/追加超时或部分失败时，先回读实际页数和页面 ID；确认缺页后再处理，不能盲目重试创建整个文稿。限流按返回提示做有界重试，连续失败或状态不明则停止写入并报告。

## 超过 10 页的稿件

先保存完整的有序页面清单及本地文件哈希。首次创建最多导入 10 页，记录响应中的 PID 和实际 SID，再逐页追加；每批结束回读，确认当前页数和已导入页面。保存每次调用的状态与响应，失败后按实际线上状态恢复，不能只根据循环执行到了哪一页判断成功。

本地图片自动上传只在**一次调用内**去重。逐页追加相同 Logo 会重复上传；为同一 PID 上传一次并复用返回的 file_token，或从已成功导入页面回读对应图片 token。按文件内容哈希记录映射，确认对应关系后仅替换提交副本的图片引用，保留可离线复现的本地原稿。不要假设旧文稿的 token 可用于新文稿。

全部写入后，按有序页面清单核对回读的正文、表格、图表分类与数值、图片数量和页序。新建导入会新增 ID，不能用依赖相同 ID 的三方比较代替首次导入核对。截图每批最多 10 页，完整检查所有页面；局部修复后重新截图对应页，并再核对全稿页数和顺序。

## 三方比较

- **baseline**：上次成功写入后，从线上回读保存的 XML，附 presentation ID、revision、身份和取得时间。
- **working**：从该基线复制后，在本地完成本次编辑的 XML。
- **remote**：写入前新回读的线上 XML。不要用模板源文件充当 baseline。

先将 `SKILL_ROOT` 设为本 skill 的实际安装目录，替换下方占位路径；三个 XML 路径仍相对于当前工作目录。

```bash
SKILL_ROOT="/实际安装目录/feishu-ppt-skill"
lark-cli slides +xml-get --presentation "$PID" --output ./remote.xml --as user
python3 "$SKILL_ROOT/scripts/compare_slides.py" --baseline baseline.xml --working working.xml --remote remote.xml --output compare-report.json
```

比较工具接受整份 `presentation` 或单页 `slide`，只输出报告，不生成合并 XML，也不会写飞书。它按页面和块 ID 识别独立修改、同块冲突、图片变化和顺序变化；没有 ID 或缺少基线会要求人工判断，不靠文件位置猜测身份。报告无冲突也不代表已经合并：把所需修改应用到最新 remote，保留其他编辑，再校验。

没有历史基线时，先回读最新线上稿作为本次起点，仅做可明确识别的修改。对基线到线上之间的图片上传和服务端规范化，不做“差异必然是用户改动”的判断；人工核对无法识别的变化。

## 整稿比较与单页编辑的衔接

`validate.py`、SVG 预览器和 `+update-slide --content` 接受单个 `<slide>`，不能把整份 `<presentation>` 直接作为页面提交。

整稿比较后，按真实 SID 从最新 remote.xml 提取目标 `<slide>`（保留命名空间和元素 ID），在这个单页上合并必要改动，保存为 merged-slide.xml，再对该文件校验和预览。也可以回读单页作为编辑起点：

```bash
lark-cli slides +xml-get --presentation "$PID" --slide-id "$SID" --output ./remote-slide.xml --as user
```

若这次回读的版本与刚比较的 remote 不同，重新比较，不能直接套用旧合并结果。对只改一页的任务，可从一开始就保存同一 SID 的单页 baseline/working/remote；整稿顺序变化仍需另外回读整稿核对。

线上回读也可能包含官方 XSD 不接受的输出属性。1.0.86 实测会给 `slide/style/fill` 添加内部 `id`，再次校验会失败。保留原始回读；只在提交副本去掉这个已确认的背景填充属性，并记录转换。保留 slide、shape、img、chart、table、td 等可编辑对象的 ID，不要批量删除所有 ID 或放宽整个 schema。遇到其他差异逐项查证。回读的备注可能没有字号，备注不参与画面的字体和主题统计。

## 选择更新方式

小范围变更优先块替换，parts 放 JSON 文件避免引号转义：

```bash
lark-cli slides +replace-slide --presentation "$PID" --slide-id "$SID" --parts @./parts.json --revision-id "$REV" --as user
```

parts 格式、块 ID 和 XML 结构按当前 CLI help/官方 skill 核对。1.0.86 的 replace-slide 帮助将具体 revision 描述为乐观锁；仍需处理冲突并回读，不声称本库验证过服务端并发语义。

确需整页重写时，输入必须包含应保留的全部内容：

```bash
lark-cli slides +update-slide --presentation "$PID" --slide-id "$SID" --content @./merged-slide.xml --revision-id "$REV" --as user
```

**整页更新的 revision 不等于通用乐观锁。** 1.0.86 帮助明确：指定旧 revision 会基于旧快照重建页面，丢弃更新的编辑。REV 必须来自写前最后一次回读；若版本变化，重新比较并合并。即使如此，读取与写入之间仍存在竞态。活跃协作时优先小范围块编辑；无法确认并发语义的整页替换不要自动执行。tid 参数若要用于并发锁，必须先查清当前 CLI/API 的协议，不能自行编造事务 ID 并声称已锁定。

写后再次回读和截图，确认必要修改以及原有图片、文本、顺序都被保留，保存新的 baseline。不要用整份演示文稿的历史回滚去修复一个局部问题而覆盖他人后续编辑；优先从历史提取所需内容，合并到当前稿。

## 故障处理

| 情况 | 处理 |
| --- | --- |
| 文件/图片找不到 | 检查工作目录与真实路径；本地校验先通过 |
| 命令或参数不存在 | 查本机 help/skills list；报告版本差异，不猜接口 |
| 返回成功但内容不符 | 回读文本、img 和页数；保留响应与版本信息 |
| 页面空白或渲染延迟 | 重读并少量重试截图；仍异常则报告，不无限重写 |
| 版本变化/并发冲突 | 停止使用旧稿，重新回读和三方比较 |
| 创建部分成功/超时 | 先确认实际已创建的文稿与页面，再决定补哪些页面 |
