"""轻量中文分词：英文按单词，中文按二元组。

不引入 jieba，是因为二元组对课程名词（动态规划、分治法、贪心算法）
已经够用，而且零依赖、可解释。
"""

import re

_STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "及", "或", "有", "对", "中", "等",
    "这", "那", "个", "我们", "你们", "他们", "我", "你", "他", "她", "它",
    "什么", "怎么", "如何", "为什么", "可以", "一个", "以及", "或者", "因为",
    "所以", "但是", "如果", "这个", "那个", "的是", "么是", "是什",
}

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+(?:-[a-zA-Z0-9_]+)*|[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for part in _TOKEN_RE.findall(text.lower()):
        if part.isascii():
            if part in _STOPWORDS:
                continue
            # 保留 0-1、c语言 这类带连字符的标识符，也拆出片段做兜底。
            if len(part) > 1 or part.isdigit():
                tokens.append(part)
            if "-" in part:
                tokens.extend(p for p in part.split("-") if p and p not in _STOPWORDS)
            continue
        if len(part) == 1:
            if part not in _STOPWORDS:
                tokens.append(part)
            continue
        for i in range(len(part) - 1):
            bigram = part[i : i + 2]
            if bigram not in _STOPWORDS:
                tokens.append(bigram)
    return tokens
