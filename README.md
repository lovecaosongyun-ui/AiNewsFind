# 每日 AI 资讯生成智能体

## 免责声明
1. 本项目**仅用于个人学习**，严禁用于任何商业用途或非法活动
2. 使用本项目前，必须遵守目标网站的robots.txt协议和服务条款
3. 使用者需自行承担因违反法律法规或网站规定而产生的一切法律责任
4. 项目作者不对任何使用本项目导致的法律纠纷承担责任


一个面向中文简报场景的 AI 资讯日报项目。系统通过 Web 控制台配置数据源、筛选条件和生成参数，自动抓取国内外 AI 资讯，完成筛选、去重、分类、摘要，并输出 Word、Markdown 和统计文件。

## 当前能力

- 默认接入 Qwen API 做中文摘要、英文翻译和分类；未配置 `DASHSCOPE_API_KEY` 时自动降级为规则摘要。
- 内置国内外 AI 资讯源、投融资资讯源和论文源，采用 RSS 与网页抓取混合模式。
- 输出 5 大模块：AI应用、AI模型、AI安全、AI投融资、最新研究论文。
- Word 文档支持标题、分节、图片、表格和原文链接。
- 同步生成 Markdown 和抓取统计 TXT，便于二次编辑和排查数据源质量。
- Web 控制台支持保存配置、管理站点、查看进度和下载生成结果。

## 目录结构

```text
AiNewsFind/
├─ ai_news_agent/              # 抓取、过滤、摘要、生成文档的核心代码
├─ config/
│  ├─ default_config.yaml       # 默认配置
│  └─ saved_web_config.yaml     # Web 控制台保存的配置
├─ logs/                       # 运行日志目录
├─ output/                     # 生成文档输出目录
├─ web_ui/                     # FastAPI Web 控制台
├─ run_web_ui.py               # Web 控制台启动入口
├─ run_scheduler.py            # 定时任务入口
├─ run_daily_news.py           # 底层流水线脚本入口
└─ requirements.txt
```

## 安装依赖

```powershell
pip install -r requirements.txt
```

## 配置 Qwen API

项目从环境变量 `DASHSCOPE_API_KEY` 读取百炼 API Key。可以写入 `.env`，也可以在当前终端设置：

```powershell
$env:DASHSCOPE_API_KEY="你的百炼APIKey"
```

未配置 API Key 时，系统会自动使用规则摘要模式，仍可生成日报。

## Web 控制台

启动本地控制台：

```powershell
python run_web_ui.py
```

打开：

```text
http://127.0.0.1:8001
```

控制台支持：

- 配置开始日期和结束日期；填写固定日期范围时优先按日期范围抓取。
- 未填写日期范围时，按“回退抓取时长”抓取最近资讯。
- 配置每站抓取上限、候选分析上限、每个模块最多入选数量。
- 配置摘要字数范围、质量评分阈值，以及是否启用 Qwen。
- 动态新增、删除、启用、停用和排序数据源。
- 保存配置并生成日报。
- 下载 Word、Markdown、统计 TXT 和日志文件。

Web 控制台生成的文件固定写入当前项目的 `output/`，日志写入当前项目的 `logs/`。保存配置时路径使用相对路径，避免项目移动或复制后继续指向旧目录。

## 定时运行

定时任务使用 `config/default_config.yaml` 中的 `schedule.daily_time`，默认是 `09:00`。

```powershell
python run_scheduler.py
```

## 配置说明

默认配置在 [config/default_config.yaml](./config/default_config.yaml)，Web 控制台保存后的配置在 [config/saved_web_config.yaml](./config/saved_web_config.yaml)。

- `runtime`：输出路径、日志路径、并发数、抓取时效窗口、文件名格式等。
- `summary`：摘要最少和最多字数。
- `quality`：资讯质量分最低阈值。
- `llm`：Qwen 模型名、温度、环境变量名等。
- `document`：标题、字体、字号、行距、分节顺序等。
- `filtering`：关键词、排除规则、分类关键词。
- `sources`：数据源地址、抓取类型、权重、选择器和过滤规则。

## 生成结果

成功生成后，`output/` 下会出现类似文件：

```text
每日AI资讯_20260428_1129.docx
每日AI资讯_20260428_1129.md
每日AI资讯_20260428_1129_stats.txt
```

日志文件默认输出到：

```text
logs/ai_news_agent.log
```

## 文档风格

默认采用偏内部简报的版式：

- 标题使用小标宋风格
- 模块标题使用黑体
- 正文使用仿宋
- 行距较规整，适合内部流转和二次编辑

如果本机未安装对应中文字体，Word 会自动回退到系统可用字体，文档仍可正常打开和编辑。

## 已知说明

- 当前版本优先保证可运行、可配置和可扩展，没有为每个资讯站点单独做深度反爬适配。
- 对于需要登录、强反爬或强 JS 渲染的网站，后续可以按站点追加更强的抓取逻辑。
- 外部站点偶发超时或断连时，系统会记录日志并继续处理其他数据源。
