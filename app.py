# app.py
# Flask 主应用

import os
import io
import time
import json
import traceback
from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
import pandas as pd

from isbn_utils import validate_isbn
from nlc_query import query_isbn
from clc_parser import parse_clc

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 最大上传 16MB

# 上传文件临时目录
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 支持的上传文件格式
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls', 'txt'}


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _do_query(isbn_raw):
    """
    执行单条 ISBN 查询的核心逻辑。
    返回结果字典。
    """
    # 验证 ISBN
    isbn, error = validate_isbn(isbn_raw)
    if error:
        return {"success": False, "error": error, "isbn_input": isbn_raw}

    try:
        # 查询国图
        book_data = query_isbn(isbn)
        if not book_data:
            return {
                "success": False,
                "error": f"国家图书馆未收录此 ISBN: {isbn}",
                "isbn_input": isbn_raw
            }

        # 解析中图分类号
        clc_code = book_data.get("clc_code", "")
        clc_info = parse_clc(clc_code)

        return {
            "success": True,
            "isbn_input": isbn_raw,
            "isbn": isbn,
            "title": book_data.get("title", ""),
            "authors": book_data.get("authors", ""),
            "publisher": book_data.get("publisher", ""),
            "pubdate": book_data.get("pubdate", ""),
            "clc_code": clc_code,
            "clc_name": clc_info.get("name", ""),
            "clc_path": clc_info.get("path", []),
            "clc_path_str": clc_info.get("path_str", ""),
            "subject": book_data.get("subject", ""),
            "summary": book_data.get("summary", ""),
        }

    except (TimeoutError, ConnectionError) as e:
        return {"success": False, "error": str(e), "isbn_input": isbn_raw}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": f"查询出错: {str(e)}", "isbn_input": isbn_raw}


@app.route('/')
def index():
    """渲染主页面"""
    return render_template('index.html')


@app.route('/api/query', methods=['POST'])
def api_query():
    """单条 ISBN 查询接口"""
    data = request.get_json()
    if not data or 'isbn' not in data:
        return jsonify({"success": False, "error": "请提供 ISBN 号"}), 400

    isbn_raw = data['isbn'].strip()
    if not isbn_raw:
        return jsonify({"success": False, "error": "ISBN 不能为空"}), 400

    result = _do_query(isbn_raw)
    return jsonify(result)


@app.route('/api/batch', methods=['POST'])
def api_batch():
    """批量查询接口：接收上传文件"""
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "请上传文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "未选择文件"}), 400

    if not allowed_file(file.filename):
        return jsonify({
            "success": False,
            "error": f"不支持的文件格式。支持: {', '.join(ALLOWED_EXTENSIONS)}"
        }), 400

    try:
        # 读取文件中的 ISBN 列表
        isbn_list = _parse_upload_file(file)

        if not isbn_list:
            return jsonify({"success": False, "error": "文件中未找到有效的 ISBN"}), 400

        if len(isbn_list) > 30:
            return jsonify({
                "success": False,
                "error": f"单次最多查询 30 条，当前文件包含 {len(isbn_list)} 条"
            }), 400

        def generate():
            total = len(isbn_list)
            yield json.dumps({"type": "start", "total": total}, ensure_ascii=False) + "\n"

            results = []
            for i, isbn_raw in enumerate(isbn_list):
                yield json.dumps({
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "isbn": isbn_raw,
                    "message": f"正在查询第 {i + 1}/{total} 条: {isbn_raw}"
                }, ensure_ascii=False) + "\n"

                result = _do_query(isbn_raw)
                results.append(result)

                if i < len(isbn_list) - 1:
                    yield json.dumps({
                        "type": "wait",
                        "current": i + 1,
                        "total": total,
                        "message": f"已完成 {i + 1}/{total} 条，为防反爬机制封禁，正在安全等待中..."
                    }, ensure_ascii=False) + "\n"
                    time.sleep(3 + 2 * (i % 3) / 2.0)

            success_count = sum(1 for r in results if r.get("success"))
            yield json.dumps({
                "type": "done",
                "success": True,
                "total": total,
                "success_count": success_count,
                "fail_count": total - success_count,
                "results": results
            }, ensure_ascii=False) + "\n"

        response = Response(stream_with_context(generate()), mimetype='application/x-ndjson')
        response.headers['X-Accel-Buffering'] = 'no'
        response.headers['Cache-Control'] = 'no-cache'
        return response

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": f"处理文件时出错: {str(e)}"}), 500


@app.route('/api/export', methods=['POST'])
def api_export():
    """导出查询结果为 Excel 文件"""
    data = request.get_json()
    if not data or 'results' not in data:
        return jsonify({"success": False, "error": "无导出数据"}), 400

    results = data['results']

    # 构建 DataFrame
    rows = []
    for r in results:
        rows.append({
            "ISBN（输入）": r.get("isbn_input", ""),
            "ISBN-13": r.get("isbn", ""),
            "书名": r.get("title", ""),
            "作者": r.get("authors", ""),
            "出版社": r.get("publisher", ""),
            "出版年": r.get("pubdate", ""),
            "中图分类号": r.get("clc_code", ""),
            "分类名称": r.get("clc_name", ""),
            "完整分类路径": r.get("clc_path_str", ""),
            "主题": r.get("subject", ""),
            "查询状态": "成功" if r.get("success") else "失败",
            "错误信息": r.get("error", ""),
        })

    df = pd.DataFrame(rows)

    # 导出为 Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='查询结果')
    output.seek(0)

    # 生成时间戳
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'中图分类号查询结果_{timestamp}.xlsx'
    )


def _parse_upload_file(file):
    """
    解析上传的文件，提取 ISBN 列表。
    支持 CSV、Excel、TXT 格式。
    """
    filename = file.filename.lower()
    isbn_list = []

    if filename.endswith('.txt'):
        # TXT 文件：每行一个 ISBN
        content = file.read().decode('utf-8', errors='ignore')
        for line in content.strip().split('\n'):
            line = line.strip()
            if line:
                isbn_list.append(line)

    elif filename.endswith('.csv'):
        # CSV 文件：尝试读取第一列或名为 isbn 的列
        content = file.read().decode('utf-8', errors='ignore')
        df = pd.read_csv(io.StringIO(content), dtype=str)
        isbn_list = _extract_isbn_from_df(df)

    elif filename.endswith(('.xlsx', '.xls')):
        # Excel 文件
        df = pd.read_excel(file, engine='openpyxl', dtype=str)
        isbn_list = _extract_isbn_from_df(df)

    return isbn_list


def _extract_isbn_from_df(df):
    """从 DataFrame 中提取 ISBN 列"""
    isbn_list = []

    # 先找包含 isbn 或条码的列（不区分大小写）
    isbn_col = None
    for col in df.columns:
        col_up = str(col).strip().upper()
        if 'ISBN' in col_up or '条码' in col_up:
            isbn_col = col
            break

    if isbn_col is not None:
        isbn_list = [str(v).strip() for v in df[isbn_col].dropna().tolist()]
    elif len(df.columns) > 0:
        # 没有明确列名，取第一列
        first_col_name = str(df.columns[0]).strip()
        isbn_list = []
        if not first_col_name.startswith('Unnamed:'):
            isbn_list.append(first_col_name)
        isbn_list.extend([str(v).strip() for v in df.iloc[:, 0].dropna().tolist()])

    # 过滤空值和表头，同时去掉由 pandas dtype 隐式转换浮点数带来的 .0
    cleaned_list = []
    for isbn in isbn_list:
        if not isbn or isbn.lower() == 'isbn' or isbn.lower() == 'nan':
            continue
        if isbn.endswith('.0'):
            isbn = isbn[:-2]
        cleaned_list.append(isbn)

    return cleaned_list


if __name__ == '__main__':
    app.run(debug=True, port=5000)
