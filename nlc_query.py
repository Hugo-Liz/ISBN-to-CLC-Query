# nlc_query.py
# 国家图书馆 OPAC 查询模块

import re
import random
import time
import requests
from bs4 import BeautifulSoup

# 国家图书馆 OPAC 基础地址
BASE_URL = "http://opac.nlc.cn/F"


def _generate_user_agent():
    """生成随机 User-Agent"""
    return (
        f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        f'(KHTML, like Gecko) Chrome/{random.randint(90, 130)}.0.0.0 '
        f'Safari/537.36 Edg/{random.randint(90, 130)}.0.0.0'
    )


def _get_headers():
    """获取请求头"""
    return {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Host': 'opac.nlc.cn',
        'Proxy-Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': _generate_user_agent()
    }


def _get_dynamic_url(session):
    """
    访问国图 OPAC 首页，获取带会话 ID 的动态 URL。
    国图的 URL 中包含动态会话标识，必须先获取才能发起查询。
    """
    session.headers.update(_get_headers())
    response = session.get(BASE_URL, timeout=15)
    response.encoding = 'utf-8'

    # 从响应中提取动态 URL（包含会话 ID）
    dynamic_url_match = re.search(r"http://opac\.nlc\.cn:80/F/[^\s?]*", response.text)
    if dynamic_url_match:
        return dynamic_url_match.group(0)
    else:
        raise ConnectionError("无法从国家图书馆获取动态会话 URL")


def _parse_metadata(soup):
    """
    从国图查询结果的 HTML 中解析元数据。
    返回原始字段字典。
    """
    data = {}
    prev_td1 = ''
    prev_td2 = ''

    # 查找结果表格
    table = soup.find("table", attrs={"id": "td"})
    if not table:
        return None

    tr_elements = table.find_all('tr')

    for tr in tr_elements:
        td_elements = tr.find_all('td', class_='td1')
        if len(td_elements) == 2:
            td1 = td_elements[0].get_text(strip=True).replace('\n', '').replace('\xa0', ' ')
            td2 = td_elements[1].get_text(strip=True).replace('\n', '').replace('\xa0', ' ')
            if td1 == '' and td2 == '':
                continue
            if td1:
                data[td1] = td2.strip()
            else:
                # 同一字段的续行内容
                data[prev_td1] = '\n'.join([prev_td2, td2]).strip()
            prev_td1 = td1.strip()
            prev_td2 = td2.strip()

    return data


def query_isbn(isbn):
    """
    通过 ISBN 查询国家图书馆 OPAC，获取图书元数据。

    参数:
        isbn: 标准化后的 ISBN 字符串（纯数字）

    返回:
        成功时返回字典，包含 title, authors, publisher, pubdate, clc_code, isbn 等字段。
        失败时返回 None。

    异常:
        ConnectionError: 网络连接问题
        TimeoutError: 请求超时
    """
    session = requests.Session()

    try:
        # 第一步：获取动态 URL
        dynamic_url = _get_dynamic_url(session)

        # 第二步：构建查询参数
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
            "filter_request_5": ""
        }

        # 第三步：发起查询
        response = session.get(dynamic_url, params=params, timeout=15)
        response.encoding = 'utf-8'

        soup = BeautifulSoup(response.text, "html.parser")
        raw_data = _parse_metadata(soup)

        if not raw_data:
            return None

        # 第四步：提取关键字段
        # 提取出版社
        publisher_match = re.search(r':\s*(.+),\s', raw_data.get("出版项", ""))
        publisher = publisher_match.group(1) if publisher_match else ""

        # 提取出版年份
        pubdate_match = re.search(r',\s*(\d{4})', raw_data.get("出版项", ""))
        pubdate = pubdate_match.group(1) if pubdate_match else ""

        # 提取中图分类号
        clc_code = raw_data.get("中图分类号", "")

        # 优化标题：保留完整的中文标题（含副标题），去除著者信息
        # 原始格式示例: "历史三调 [专著] : 作为事件、经历和神话的义和团 = History in three keys / (美)柯文著"
        title = raw_data.get("题名与责任", isbn)
        # 第一步：去掉 [专著] [普通图书] 等方括号标识
        title = re.sub(r'\s*\[[\u4e00-\u9fa5]+\]\s*', ' ', title)
        # 第二步：截取到 "/" （著者分隔符）之前的内容
        if '/' in title:
            title = title.split('/')[0]
        # 第三步：截取到 "=" （英文标题分隔符）之前的内容
        if '=' in title:
            title = title.split('=')[0]
        # 清理多余空格
        title = re.sub(r'\s+', ' ', title).strip()
        # 清理尾部的冒号、逗号等符号
        title = title.rstrip(' :：,，;；')

        return {
            "title": title,
            "authors": raw_data.get("著者", ""),
            "publisher": publisher,
            "pubdate": pubdate,
            "clc_code": clc_code,
            "isbn": isbn,
            "subject": raw_data.get("主题", ""),
            "summary": raw_data.get("内容提要", ""),
        }

    except requests.exceptions.Timeout:
        raise TimeoutError("国家图书馆查询超时，请稍后重试")
    except requests.exceptions.ConnectionError:
        raise ConnectionError("无法连接到国家图书馆服务器")
    finally:
        session.close()
