# ISBN 转中图分类号工具 (ISBN to CLC Code Tool)

这是一个基于 Python Flask 编写的 Web 应用，能够通过输入图书的 ISBN 号自动查询国家图书馆 OPAC，获取对应的**中图分类号**（Chinese Library Classification, CLC）并精准解析出分类的**层级路径**与**主题**。

## ✨ 特性

- **精准查询**：对接国家图书馆 OPAC，获取权威书籍数据。
- **层级解析**：自动将分类号转换成类似 `历史、地理 > 中国史 > 地方史志` 的完整层级路径。内置常见分类号映射，遇到细分分类（如 `K256.707`）能够智能截断向上匹配。
- **批量查询**：支持 `CSV`、`Excel`、`TXT` 文件批量上传查询（单次限制最多 30 条以防封禁），附带安全请求间隔机制。
- **一键导出**：支持将批量查询结果（含书名、作者、出版社、出版年、完整分类路径、主题）导出为 Excel 表格。
- **现代 UI**：响应式毛玻璃拟态界面、炫酷深色设计，平滑过渡动画。
- **ISBN 自动校验**：兼容并自动格式化 ISBN-10 与 ISBN-13。

## 🛠 技术栈

- **后端**：Python (Flask), Regex, Requests, BeautifulSoup, Pandas, Openpyxl
- **分词/分类解析库**：`chinese-library-classification`
- **前端**：HTML, Vanilla CSS (深色主题 / 毛玻璃效果), Vanilla JS

## 🚀 本地运行

1. 克隆代码并进入项目目录：
   ```bash
   git clone <你的仓库地址>
   cd Query_of_Chinese_Library_Classification_Number
   ```

2. 安装依赖包：
   ```bash
   pip install -r requirements.txt
   ```

3. 启动服务：
   ```bash
   python app.py
   ```

4. 打开浏览器访问：[http://127.0.0.1:5000](http://127.0.0.1:5000)

## ⚠️ 注意事项

由于该工具核心依赖爬取国家图书馆的数据查询，过于频繁的批量请求会导致 IP 被短暂封禁。系统内部已对批量查询的频率做了 `time.sleep` 的随机延时限制。请合理使用。
