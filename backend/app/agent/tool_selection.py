"""Pick the tools most relevant to a request, so the model isn't sent every tool of every server.

Plain word overlap between the request and each tool's name and description, with name words
counting double. Misses are recoverable: the agent also gets a ``nexus_find_tools`` tool.

ponytail: lexical scoring; switch to embeddings if tool sets grow to hundreds and picks get poor.
"""
from __future__ import annotations

import re

STOPWORDS = set("""
a an and are as at be by can could do does for from get give has have how i in into is it its me my
of on or our please show so that the their them then there these this to us was we what when where
which who why will with would you your all any some about tell find list
""".split())


def _words(text: str) -> set[str]:
    words = set()
    for word in re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()):
        if len(word) > 2 and word not in STOPWORDS:
            words.add(word[:-1] if word.endswith("s") and len(word) > 4 else word)  # issues -> issue
    return words


def rank_tools(query: str, tools: list[tuple[str, str]], limit: int, min_score: int = 0) -> list[str]:
    """Names of the ``limit`` tools whose name/description best match ``query`` (ties keep input order).

    ``min_score=1`` leaves out tools that share no word with the query."""
    wanted = _words(query)
    scored = []
    for index, (name, description) in enumerate(tools):
        server, _, tool = name.partition("__")
        # OpenAPI-generated servers name tools "API-post-search": the HTTP method says nothing about intent.
        tool = re.sub(r"^api[-_](get|post|put|patch|delete)[-_]", "", tool or name, flags=re.IGNORECASE)
        name_words = _words(tool)
        score = 2 * len(wanted & name_words) + len(wanted & _words(description)) + (1 if wanted & _words(server) else 0)
        if score >= min_score:
            scored.append((-score, index, name))
    return [name for _, _, name in sorted(scored)[:limit]]


if __name__ == "__main__":
    tools = [("notion__API-post-search", "Search by title"), ("github__list_issues", "List issues in a repository"),
             ("slack__send_message", "Send a message to a channel"), ("github__create_issue", "Create an issue")]
    assert rank_tools("create a GitHub issue about the login bug", tools, 2) == ["github__create_issue", "github__list_issues"]
    assert rank_tools("post in the #general channel", tools, 1) == ["slack__send_message"]
    assert rank_tools("hello", tools, 2) == ["notion__API-post-search", "github__list_issues"]  # no match: input order
    assert rank_tools("hello", tools, 2, min_score=1) == []
    print("tool selection self-check passed")
