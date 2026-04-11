# ISBN 查询中图分类号 Web 工具

## 背景

通过 ISBN 号关联查询中图分类号（CLC），并将分类号解析为完整的中文层级分类路径。工具形态为 Web 应用，使用 Python Flask 后端 + 前端页面实现。

## 核心技术方案

### 数据流

```mermaid
graph LR
    A[用户输入 ISBN] --> B[Flask 后端]
    B --> C[请求国家图书馆 OPAC]
    C --> D[解析 HTML 提取中图分类号]
    D --> E[chinese-library-classification 库解析层级]
    E --> F[返回结果给前端展示]
```

### 1. ISBN → 中图分类号（数据源：国家图书馆 OPAC）

参考 [NLCISBNPlugin](https://github.com/DoiiarX/NLCISBNPlugin) 和 [EbookDataGeter](https://github.com/Hellohistory/EbookDataGeter) 的成熟实现，核心步骤：

1. **获取动态 URL**：先访问 `http://opac.nlc.cn/F`，从响应中提取带会话 ID 的动态 URL
2. **发起 ISBN 检索**：向动态 URL 发送查询请求，参数 `func=find-b, find_code=ISB, request={isbn}`
3. **解析 HTML 结果**：从返回的 HTML 表格（`table#td`）中提取 `中图分类号` 字段

### 2. 中图分类号 → 中文分类层级

使用现成的 Python 库 `chinese-library-classification`：
- `pip install chinese-library-classification`
- 通过 `num2info(code)` 获取分类信息（名称、层级、上下级关系）
- 通过 `num2upper(code)` 获取所有上级分类，构建完整路径

> [!IMPORTANT]
> 该库的数据覆盖度需要实际验证。如果覆盖不足，备选方案是内置一份中图分类号字典（22个一级大类 + 常用二三级分类），自行实现解析。

---

## 功能需求

| 功能 | 说明 |
|------|------|
| 单条查询 | 输入单个 ISBN，展示书名、中图分类号、完整分类路径等 |
| 批量查询 | 上传 CSV/Excel/TXT 文件（含 ISBN 列），批量查询 |
| 结果导出 | 将批量查询结果导出为 CSV/Excel 文件 |
| ISBN 校验 | 支持 ISBN-10 和 ISBN-13，自动转换和校验 |
| 错误处理 | 查询失败时给出明确提示（ISBN无效、国图无数据、网络超时等） |

---

## 项目文件结构

```
Query_of_Chinese_Library_Classification_Number/
├── app.py                  # Flask 应用主入口
├── requirements.txt        # Python 依赖
├── nlc_query.py            # 国家图书馆 OPAC 查询模块
├── clc_parser.py           # 中图分类号解析模块
├── isbn_utils.py           # ISBN 校验与转换工具
├── static/
│   ├── style.css           # 前端样式
│   └── app.js              # 前端交互逻辑
├── templates/
│   └── index.html          # 主页面模板
├── uploads/                # 上传文件临时目录（运行时创建）
└── GEMINI.md               # 已有的规则文件
```

---

## 各模块详细设计

### 1. `isbn_utils.py` — ISBN 校验工具

- `canonical(isbn)`: 标准化 ISBN，去除多余字符
- `is_isbn10(isbn)` / `is_isbn13(isbn)`: 校验有效性
- `to_isbn13(isbn10)`: ISBN-10 转 ISBN-13
- 参考 NLCISBNPlugin 中已有的成熟实现

### 2. `nlc_query.py` — 国图 OPAC 查询模块

- `get_session()`: 创建 requests.Session，获取动态 URL
- `query_isbn(isbn)`: 通过 ISBN 查询国图，返回原始元数据字典
- 包含随机 User-Agent、请求间隔等反反爬策略
- 返回数据结构：
```python
{
    "title": "书名",
    "authors": "作者",
    "publisher": "出版社",
    "pubdate": "出版年",
    "clc_code": "TP311.12",  # 中图分类号
    "isbn": "9787111544937"
}
```

### 3. `clc_parser.py` — 中图分类号解析模块

- `parse_clc(code)`: 输入分类号，输出完整层级路径
- 优先使用 `chinese-library-classification` 库
- 如果库查不到，回退到内置的一级大类字典
- 返回数据结构：
```python
{
    "code": "TP311.12",
    "name": "数据结构",
    "path": ["工业技术", "自动化技术、计算机技术", "计算技术、计算机技术", "程序设计、软件工程", "数据结构"],
    "path_str": "工业技术 > 自动化技术、计算机技术 > ... > 数据结构"
}
```

### 4. `app.py` — Flask 主应用

**API 路由：**

| 路由 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 渲染主页面 |
| `/api/query` | POST | 单条 ISBN 查询 |
| `/api/batch` | POST | 批量查询（接收上传文件） |
| `/api/export` | POST | 导出查询结果为 CSV/Excel |

### 5. 前端页面（`index.html` + `style.css` + `app.js`）

- **设计风格**：现代深色主题，毛玻璃效果，渐变色调
- **单条查询区**：ISBN 输入框 + 查询按钮，结果卡片式展示
- **批量查询区**：文件拖拽上传 + 结果表格展示 + 导出按钮
- **响应式布局**：适配桌面和移动端

---

## 依赖清单 (`requirements.txt`)

```
flask
requests
beautifulsoup4
chinese-library-classification
openpyxl
pandas
```

> [!NOTE]
> - `openpyxl` 用于读写 Excel 文件
> - `pandas` 用于处理批量数据和导出

---

## User Review Required

> [!WARNING]
> **关于国家图书馆 OPAC 的稳定性**：国图 OPAC 不是公开 API，存在以下风险：
> 1. 高频请求可能导致 IP 被封
> 2. 页面结构变化可能导致解析失败
> 3. 批量查询时需要控制请求频率（建议每次请求间隔 1-2 秒）
>
> 对于批量查询，会加入请求间隔控制，并在前端展示查询进度。

> [!IMPORTANT]
> **`chinese-library-classification` 库的数据覆盖度**尚未验证。开发时会先测试该库，如果覆盖不足，将内置一份完整的分类号字典作为补充方案。

---

## 验证计划

### 自动测试
- 使用已知 ISBN 测试单条查询（如 `9787111544937` → 深入理解计算机系统）
- 准备测试文件验证批量上传和导出功能
- 验证 ISBN-10 和 ISBN-13 的校验与转换

### 手动验证
- 启动 Flask 开发服务器，在浏览器中完整测试查询流程
- 验证文件上传（CSV、Excel、TXT 格式）
- 验证导出文件的内容正确性
- 检查前端在不同窗口尺寸下的响应式表现
