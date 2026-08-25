# nlc_query.py
# 国家图书馆 OPAC 查询模块

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from query_cache import get_default_cache


BASE_URL = "http://opac.nlc.cn/F"
REQUEST_TIMEOUT = (6, 20)
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

NO_RESULT_MARKERS = (
    "没有符合检索条件的记录",
    "没有查到相关记录",
    "未找到相关记录",
    "no records were found",
    "no records match",
)


class NLCQueryError(ConnectionError):
    """国家图书馆查询的基础异常。"""


class NLCBlockedError(NLCQueryError):
    """请求被国图限制或拒绝。"""


class NLCResponseError(NLCQueryError):
    """国图返回了无法识别或不完整的响应。"""


def _get_headers():
    """返回稳定、精简的浏览器请求头。"""
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.7,en;q=0.6",
        "User-Agent": USER_AGENT,
    }


def _build_retry():
    return Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        allowed_methods=frozenset({"GET"}),
        status_forcelist=RETRY_STATUS_CODES,
        backoff_factor=0.8,
        respect_retry_after_header=True,
        raise_on_status=False,
    )


def _normalize_dynamic_url(candidate):
    """规范化国图动态会话地址，并拒绝站外地址。"""
    absolute = urljoin(BASE_URL, candidate)
    parsed = urlsplit(absolute)
    if parsed.hostname != "opac.nlc.cn":
        return None
    if not parsed.path.startswith("/F/") or parsed.path == "/F/":
        return None
    return urlunsplit((parsed.scheme or "http", parsed.netloc, parsed.path, "", ""))


def _extract_dynamic_url(html):
    """兼容绝对地址、相对地址、不同端口以及页面标签变化。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag, attribute in (("a", "href"), ("form", "action"), ("frame", "src")):
        for element in soup.find_all(tag):
            candidate = element.get(attribute)
            if not candidate or "/F/" not in candidate:
                continue
            normalized = _normalize_dynamic_url(candidate)
            if normalized:
                return normalized

    match = re.search(
        r"(?P<url>https?://opac\.nlc\.cn(?::\d+)?/F/[^\"'\s?<>&]+|"
        r"(?<![\w.-])/F/[^\"'\s?<>&]+)",
        html,
        flags=re.IGNORECASE,
    )
    if match:
        return _normalize_dynamic_url(match.group("url"))
    return None


def _parse_metadata(soup):
    """从国图详情页提取原始字段字典。"""
    data = {}
    previous_key = ""

    table = soup.find("table", attrs={"id": "td"})
    if not table:
        return None

    for row in table.find_all("tr"):
        cells = row.find_all("td", class_="td1")
        if len(cells) != 2:
            continue

        key = cells[0].get_text(strip=True).replace("\n", "").replace("\xa0", " ")
        value = cells[1].get_text(strip=True).replace("\n", "").replace("\xa0", " ")
        if not key and not value:
            continue

        if key:
            data[key] = value.strip()
            previous_key = key.strip()
        elif previous_key:
            previous_value = data.get(previous_key, "")
            data[previous_key] = "\n".join(
                part for part in (previous_value, value.strip()) if part
            )

    return data or None


def _is_no_result_page(soup):
    text = soup.get_text(" ", strip=True).lower()
    return any(marker in text for marker in NO_RESULT_MARKERS)


def _build_book_data(isbn, raw_data):
    publication = raw_data.get("出版项", "")
    publisher_match = re.search(r":\s*(.+),\s", publication)
    publisher = publisher_match.group(1) if publisher_match else ""

    pubdate_match = re.search(r",\s*(\d{4})", publication)
    pubdate = pubdate_match.group(1) if pubdate_match else ""

    title = raw_data.get("题名与责任", isbn)
    title = re.sub(r"\s*\[[\u4e00-\u9fa5]+\]\s*", " ", title)
    if "/" in title:
        title = title.split("/")[0]
    if "=" in title:
        title = title.split("=")[0]
    title = re.sub(r"\s+", " ", title).strip().rstrip(" :：,，;；")

    return {
        "title": title,
        "authors": raw_data.get("著者", ""),
        "publisher": publisher,
        "pubdate": pubdate,
        "clc_code": raw_data.get("中图分类号", ""),
        "isbn": isbn,
        "subject": raw_data.get("主题", ""),
        "summary": raw_data.get("内容提要", ""),
    }


class NLCClient:
    """可在一次任务内复用会话、动态 URL 和本地缓存的国图客户端。"""

    def __init__(self, session=None, cache=None, timeout=REQUEST_TIMEOUT):
        self.session = session or requests.Session()
        self._owns_session = session is None
        self.cache = get_default_cache() if cache is None else cache
        self.timeout = timeout
        self.dynamic_url = None
        self.last_cache_hit = False
        self.last_network_request = False

        # 国图应直连，避免继承终端或系统中的 HTTP(S) 代理而被拒绝。
        self.session.trust_env = False
        self.session.headers.update(_get_headers())

        if self._owns_session:
            adapter = HTTPAdapter(max_retries=_build_retry(), pool_connections=2, pool_maxsize=2)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self._owns_session:
            self.session.close()

    def _request(self, url, params=None):
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.exceptions.Timeout as exc:
            raise TimeoutError("国家图书馆查询超时，请稍后重试") from exc
        except requests.exceptions.ConnectionError as exc:
            raise NLCQueryError("无法连接到国家图书馆服务器") from exc
        except requests.exceptions.RequestException as exc:
            raise NLCQueryError(f"国家图书馆请求失败: {exc}") from exc

        if response.status_code in (403, 429):
            raise NLCBlockedError(
                f"国家图书馆暂时拒绝请求（HTTP {response.status_code}），请稍后重试"
            )
        if response.status_code >= 500:
            raise NLCQueryError(
                f"国家图书馆服务暂时不可用（HTTP {response.status_code}）"
            )
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise NLCQueryError(
                f"国家图书馆返回异常状态（HTTP {response.status_code}）"
            ) from exc

        response.encoding = "utf-8"
        return response

    def refresh_dynamic_url(self):
        response = self._request(BASE_URL)
        dynamic_url = _extract_dynamic_url(response.text)
        if not dynamic_url:
            raise NLCResponseError("无法从国家图书馆获取动态会话 URL")
        self.dynamic_url = dynamic_url
        return dynamic_url

    def _ensure_dynamic_url(self):
        return self.dynamic_url or self.refresh_dynamic_url()

    def _query_remote(self, isbn):
        params = {
            "func": "find-b",
            "find_code": "ISB",
            "request": isbn,
            "local_base": "NLC01",
            "filter_code_1": "WLN",
            "filter_request_1": "",
            "filter_code_2": "WYR",
            "filter_request_2": "",
            "filter_code_3": "WYR",
            "filter_request_3": "",
            "filter_code_4": "WFM",
            "filter_request_4": "",
            "filter_code_5": "WSL",
            "filter_request_5": "",
        }

        # 页面无法识别时刷新动态会话并仅重试一次。
        for attempt in range(2):
            response = self._request(self._ensure_dynamic_url(), params=params)
            soup = BeautifulSoup(response.text, "html.parser")
            raw_data = _parse_metadata(soup)
            if raw_data:
                return _build_book_data(isbn, raw_data)
            if _is_no_result_page(soup):
                return None

            self.dynamic_url = None
            if attempt == 0:
                continue

        raise NLCResponseError("国家图书馆返回了无法识别的查询页面")

    def query(self, isbn):
        self.last_cache_hit = False
        self.last_network_request = False

        if self.cache is not False:
            cache_hit, cached_value = self.cache.get(isbn)
            if cache_hit:
                self.last_cache_hit = True
                return cached_value

        self.last_network_request = True
        result = self._query_remote(isbn)

        if self.cache is not False:
            if result is None:
                self.cache.set_not_found(isbn)
            else:
                self.cache.set_success(isbn, result)
        return result


def _get_dynamic_url(session):
    """兼容旧调用方式；新代码应复用 ``NLCClient``。"""
    client = NLCClient(session=session, cache=False)
    return client.refresh_dynamic_url()


def query_isbn(isbn, client=None):
    """通过 ISBN 查询国图；传入 client 时会复用当前批次会话。"""
    if client is not None:
        return client.query(isbn)

    with NLCClient() as owned_client:
        return owned_client.query(isbn)
