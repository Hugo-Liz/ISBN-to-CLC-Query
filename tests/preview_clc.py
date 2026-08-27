"""本地页面验收夹具；所有书目明确为测试数据，不访问国图或修改查询缓存。

仅用于手动验收：python -m tests.preview_clc，访问127.0.0.1:5051。
"""

from unittest.mock import patch

from app import app


BOOKS = {
    "9787521779158": {"title": "【页面测试】捷克现代小说", "clc_code": "I524.45"},
    "9787020002207": {"title": "【页面测试】荷兰美术人物", "clc_code": "K835.635.72=43"},
    "9787506365437": {"title": "【页面测试】未支持尾缀", "clc_code": "I524.45=999"},
}


def preview_query(isbn, client=None):
    return BOOKS.get(isbn)


if __name__ == "__main__":
    with patch("app.query_isbn", side_effect=preview_query):
        app.run(host="127.0.0.1", port=5051, debug=False, use_reloader=False)
