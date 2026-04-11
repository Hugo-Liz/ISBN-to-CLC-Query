# isbn_utils.py
# ISBN 校验与转换工具模块

def canonical(isbnlike):
    """
    标准化 ISBN，保留数字和 X。
    去除连字符、空格等多余字符。
    """
    numb = [c for c in isbnlike if c in '0123456789Xx']
    if numb and numb[-1] == 'x':
        numb[-1] = 'X'
    isbn = ''.join(numb)
    # 筛除特殊情况
    if (isbn and len(isbn) not in (10, 13)
            or isbn in ('0000000000', '0000000000000', '000000000X')
            or isbn.find('X') not in (9, -1) or isbn.find('x') != -1):
        return ''
    return isbn


def check_digit10(first_nine_digits):
    """计算 ISBN-10 的校验位"""
    if len(first_nine_digits) != 9:
        return ''
    try:
        int(first_nine_digits)
    except ValueError:
        return ''
    val = sum((i + 2) * int(x) for i, x in enumerate(reversed(first_nine_digits)))
    remainder = int(val % 11)
    if remainder == 0:
        tenth_digit = 0
    else:
        tenth_digit = 11 - remainder
    return str(tenth_digit) if tenth_digit != 10 else 'X'


def check_digit13(first_twelve_digits):
    """计算 ISBN-13 的校验位"""
    if len(first_twelve_digits) != 12:
        return ''
    try:
        int(first_twelve_digits)
    except ValueError:
        return ''
    val = sum((i % 2 * 2 + 1) * int(x) for i, x in enumerate(first_twelve_digits))
    thirteenth_digit = 10 - int(val % 10)
    return str(thirteenth_digit) if thirteenth_digit != 10 else '0'


def is_isbn10(isbn10):
    """验证 ISBN-10 格式是否有效"""
    isbn10 = canonical(isbn10)
    if len(isbn10) != 10:
        return False
    return bool(check_digit10(isbn10[:-1]) == isbn10[-1])


def is_isbn13(isbn13):
    """验证 ISBN-13 格式是否有效"""
    isbn13 = canonical(isbn13)
    if len(isbn13) != 13:
        return False
    if isbn13[0:3] not in ('978', '979'):
        return False
    return bool(check_digit13(isbn13[:-1]) == isbn13[-1])


def to_isbn13(isbn10):
    """将 ISBN-10 转换为 ISBN-13"""
    isbn10 = canonical(isbn10)
    if len(isbn10) == 13 and is_isbn13(isbn10):
        return isbn10
    if not is_isbn10(isbn10):
        return ''
    isbn13 = '978' + isbn10[:-1]
    check = check_digit13(isbn13)
    return isbn13 + check if check else ''


def validate_isbn(isbn_input):
    """
    验证并标准化 ISBN 输入。
    返回 (标准化后的ISBN-13, 错误信息)。
    如果有效，错误信息为 None；如果无效，ISBN 为 None。
    """
    isbn = canonical(isbn_input.strip())
    if not isbn:
        return None, f"无效的 ISBN 格式: {isbn_input}"

    if len(isbn) == 10:
        if not is_isbn10(isbn):
            return None, f"ISBN-10 校验失败: {isbn_input}"
        isbn13 = to_isbn13(isbn)
        return isbn13, None
    elif len(isbn) == 13:
        if not is_isbn13(isbn):
            return None, f"ISBN-13 校验失败: {isbn_input}"
        return isbn, None
    else:
        return None, f"ISBN 长度不正确: {isbn_input}"
