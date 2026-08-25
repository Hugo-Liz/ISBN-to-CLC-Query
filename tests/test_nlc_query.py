import unittest

import requests

from nlc_query import BASE_URL, NLCClient, _extract_dynamic_url


HOME_HTML = '<html><a href="/F/SESSION123">进入目录</a></html>'
DETAIL_HTML = """
<html><table id="td">
  <tr><td class="td1">题名与责任</td><td class="td1">测试书 [专著] / 张三著</td></tr>
  <tr><td class="td1">著者</td><td class="td1">张三</td></tr>
  <tr><td class="td1">出版项</td><td class="td1">北京 : 测试出版社, 2024</td></tr>
  <tr><td class="td1">中图分类号</td><td class="td1">TP311</td></tr>
</table></html>
"""


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.encoding = None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}
        self.trust_env = True
        self.closed = False

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if not self.responses:
            raise AssertionError("测试响应队列已用完")
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, isbn):
        return self.values.get(isbn, (False, None))

    def set_success(self, isbn, result):
        self.values[isbn] = (True, result)

    def set_not_found(self, isbn):
        self.values[isbn] = (True, None)


class NLCQueryTest(unittest.TestCase):
    def test_extracts_absolute_and_relative_dynamic_urls(self):
        absolute = _extract_dynamic_url(
            '<a href="http://opac.nlc.cn:80/F/ABSOLUTE123?x=1">进入</a>'
        )
        relative = _extract_dynamic_url('<form action="/F/RELATIVE123"></form>')
        external = _extract_dynamic_url('<a href="https://example.com/F/BAD">进入</a>')

        self.assertEqual(absolute, "http://opac.nlc.cn:80/F/ABSOLUTE123")
        self.assertEqual(relative, "http://opac.nlc.cn/F/RELATIVE123")
        self.assertIsNone(external)

    def test_reuses_dynamic_session_for_multiple_isbns(self):
        session = FakeSession([
            FakeResponse(HOME_HTML),
            FakeResponse(DETAIL_HTML),
            FakeResponse(DETAIL_HTML),
        ])
        client = NLCClient(session=session, cache=False)

        first = client.query("9787020002207")
        second = client.query("9787506365437")

        self.assertEqual(first["clc_code"], "TP311")
        self.assertEqual(second["title"], "测试书")
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sum(call["url"] == BASE_URL for call in session.calls), 1)

    def test_cache_avoids_second_network_query(self):
        session = FakeSession([FakeResponse(HOME_HTML), FakeResponse(DETAIL_HTML)])
        client = NLCClient(session=session, cache=MemoryCache())

        first = client.query("9787020002207")
        second = client.query("9787020002207")

        self.assertEqual(first, second)
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(client.last_cache_hit)
        self.assertFalse(client.last_network_request)

    def test_refreshes_dynamic_session_after_unrecognized_page(self):
        session = FakeSession([
            FakeResponse('<a href="/F/OLDSESSION">进入</a>'),
            FakeResponse("<html>临时会话失效</html>"),
            FakeResponse('<a href="/F/NEWSESSION">进入</a>'),
            FakeResponse(DETAIL_HTML),
        ])
        client = NLCClient(session=session, cache=False)

        result = client.query("9787020002207")

        self.assertEqual(result["title"], "测试书")
        self.assertEqual(len(session.calls), 4)
        self.assertEqual(session.calls[-1]["url"], "http://opac.nlc.cn/F/NEWSESSION")


if __name__ == "__main__":
    unittest.main()
