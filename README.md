# ISBN 转中图分类号工具

一个基于 Flask 的本地 Web 工具。输入 ISBN 后，程序查询国家图书馆 OPAC，提取书名、作者、出版社、出版年、中图分类号和主题词，并尝试使用本地分类数据生成中文分类路径。

> [!IMPORTANT]
> 中图分类号来自国家图书馆书目记录；分类路径由本地第三方分类数据另行解析。两者的数据来源和准确度不同，复杂的复分、仿分或组合分类号可能只能显示一级大类，详见“已知限制”。

## 功能

- 支持 ISBN-10、ISBN-13 校验、标准化及 ISBN-10 转 ISBN-13。
- 支持单条查询，返回书名、作者、出版信息、中图分类号、主题词和内容提要。
- 支持 CSV、XLSX、TXT 批量查询，单次最多 30 条。
- 支持 NDJSON 流式进度反馈和 Excel 结果导出。
- 自动复用国图动态会话，减少批量任务中的重复初始化请求。
- 对连接错误和临时 HTTP 错误自动重试；动态会话失效时刷新后再查询一次。
- 使用 SQLite 缓存成功和未收录结果，降低重复请求频率。
- 同一批次的重复 ISBN 只查询一次，但仍按原行数返回结果。
- 连续 3 次真实上游请求失败后暂停本批次后续网络查询，避免持续触发访问限制。

## 运行环境

- Python 3.9 或更高版本
- macOS、Linux 或 Windows
- 可访问 `opac.nlc.cn` 的网络环境

## 本地部署

```bash
git clone https://github.com/Hugo-Liz/ISBN-to-CLC-Query.git
cd ISBN-to-CLC-Query

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

python -m flask --app app run --host 127.0.0.1 --port 5000
```

Windows PowerShell 激活虚拟环境：

```powershell
.venv\Scripts\Activate.ps1
```

启动后访问 [http://127.0.0.1:5000](http://127.0.0.1:5000)。该命令启动的是 Flask 本地开发服务器，适合个人电脑使用，不建议直接作为公网生产服务。

## 批量文件格式

支持以下文件：

| 格式 | 读取规则 |
|---|---|
| CSV / Excel | 优先读取列名包含 `ISBN` 或“条码”的列，否则读取第一列 |
| TXT | 每行一个 ISBN |

项目页面提供标准 Excel 模板。程序会忽略空单元格、`NaN` 和重复表头，并处理 Excel 数字单元格可能产生的 `.0` 后缀。

当前接口虽然允许选择 `.xls` 扩展名，但读取引擎是 Openpyxl，不支持旧式二进制 XLS 文件；请先另存为 `.xlsx`。

批量查询时：

- 仅真实网络请求会等待，默认随机等待 2～4 秒。
- 本地缓存命中、同批重复 ISBN 和输入校验失败不会等待。
- 同批重复记录不会被删除，导出结果仍保持对应的记录数量。
- 连续 3 次真实上游请求失败后，剩余未查询的唯一 ISBN 会标记为本批次暂停。

## 查询缓存

缓存数据库默认位于：

```text
data/query_cache.sqlite3
```

| 缓存内容 | 默认有效期 |
|---|---:|
| 查询成功 | 90 天 |
| 国图未收录 | 24 小时 |

`data/` 已加入 `.gitignore`，不会上传查询缓存。可以通过环境变量修改数据库位置：

```bash
export ISBN_CLC_CACHE_PATH=/absolute/path/query_cache.sqlite3
```

如需清空缓存，可在项目目录执行：

```bash
python -c "from query_cache import get_default_cache; get_default_cache().clear()"
```

## 网络与代理

当前国图请求客户端不继承终端中的 `HTTP_PROXY`、`HTTPS_PROXY` 等环境变量，避免代理出口导致国图返回 HTTP 403。

如果使用 Clash Verge 等系统代理工具，建议为 `opac.nlc.cn` 配置直连规则。浏览器可以打开国图页面，不一定代表 Python 进程走的是同一条网络路径；发生 403、连接超时或无法获取动态会话时，应分别检查系统代理、TUN 模式和域名规则。

## 稳定性机制

```text
ISBN 校验
  → 查询 SQLite 缓存
  → 获取或复用国图动态会话
  → 带退避的自动重试
  → 解析书目 HTML
  → 写入正向或未收录缓存
  → 解析本地分类路径
```

- 连接、读取及部分临时 HTTP 错误最多自动重试 2 次。
- 重试采用退避等待，并遵守服务端的 `Retry-After`。
- 遇到 HTTP 403、429、5xx、超时及页面结构异常时返回可区分的错误信息。
- 动态会话页面失效或响应无法识别时，刷新会话后仅额外查询一次。
- 批量任务复用一个 `requests.Session` 和一个动态会话 URL。

这些机制只能降低失败概率，无法保证第三方 OPAC 始终可用。请控制批量规模和使用频率。

## 已知限制

### 分类路径

当前分类路径依赖 `chinese-library-classification` 的基本类目数据，并使用逐级截短方式寻找最接近的类目。该方法可以正确处理许多直接列出的分类号，但尚不能完整解释以下组合规则：

- 范围类目，例如 `I3/7`、`K833/837`。
- 世界地区、中国地区和民族复分。
- 仿照其他类目继续细分的分类号。
- `=` 国际时代复分。
- `-` 总论复分及带括号的复分形式。

因此可能出现：

| 分类号 | 当前可能显示 | 尚需解析的含义 |
|---|---|---|
| `I524.45` | 文学 | 各国文学、捷克文学及小说类型 |
| `K835.635.72=43` | 历史、地理 | 荷兰美术人物及国际时代复分 |

这里影响的是“分类路径”展示，不代表国家图书馆返回的原始中图分类号错误。组合分类号解析器将在后续版本单独设计和实现。

### 国图 OPAC

国家图书馆 OPAC 不是本项目控制的正式开放 API。页面结构、访问策略或服务状态发生变化时，查询仍可能失败，本项目也不对第三方数据的完整性作保证。

## API

| 路由 | 方法 | 说明 |
|---|---|---|
| `/` | GET | Web 页面 |
| `/api/query` | POST | 单条 ISBN 查询 |
| `/api/batch` | POST | 上传文件并以 NDJSON 返回批量进度和结果 |
| `/api/export` | POST | 将结果导出为 Excel |

单条查询示例：

```bash
curl -H 'Content-Type: application/json' \
  -d '{"isbn":"9787020002207"}' \
  http://127.0.0.1:5000/api/query
```

## 测试

```bash
python -m unittest discover -s tests -v
```

当前测试覆盖：

- SQLite 成功、未收录及过期缓存。
- 动态会话 URL 提取和站外地址拒绝。
- 批量任务中的动态会话复用。
- 会话失效后的自动刷新。
- 缓存命中避免重复网络请求。
- 批量重复 ISBN 去重但保留结果行。
- 连续上游失败后的熔断行为。

## 项目结构

```text
ISBN-to-CLC-Query/
├── app.py                    # Flask 路由、批量流式处理和导出
├── nlc_query.py              # 国图会话、重试和 HTML 解析
├── query_cache.py            # SQLite 查询缓存
├── clc_parser.py             # 本地中图分类路径解析
├── isbn_utils.py             # ISBN 校验与转换
├── requirements.txt          # Python 依赖
├── templates/index.html      # 页面模板
├── static/                   # 前端脚本、样式和 Excel 模板
└── tests/                    # 自动测试
```

更详细的当前实现见 [`implementation_plan.md`](implementation_plan.md)，版本变更见 [`CHANGELOG.md`](CHANGELOG.md)。
