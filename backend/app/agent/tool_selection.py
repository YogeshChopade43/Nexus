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


WHO_AM_I_NAME = re.compile(r"(^|[-_])(get[-_]?me|whoami|who[-_]am[-_]i|get[-_]?self|current[-_]?user)$", re.IGNORECASE)
# Who-am-I tools: by name, or a description that *starts* by saying it returns the signed-in user/account
# ("[GitHub] Get details of the authenticated GitHub user"), not one mentioning the user in passing.
WHO_AM_I_TEXT = re.compile(r"^\W*(\[[^\]]*\]\s*)?(get|retrieve|return|fetch|show)s?\b[^.]{0,40}?\b"
                           r"(authenticated|signed[- ]in|logged[- ]in|current) (\w+ )?(user|account)\b", re.IGNORECASE)


def rank_tools(query: str, tools: list[tuple[str, str]], limit: int, min_score: int = 0) -> list[str]:
    """Names of the ``limit`` tools whose name/description best match ``query`` (ties keep input order).

    ``min_score=1`` leaves out tools that share no word with the query."""
    wanted = _words(query)
    # Apps the request names ("github"): their tools outrank others that merely share a word with it.
    named = {name.partition("__")[0] for name, _ in tools if wanted & _words(name.partition("__")[0])}
    scored, who_am_i = [], []
    for index, (name, description) in enumerate(tools):
        server, _, tool = name.partition("__")
        # OpenAPI-generated servers name tools "API-post-search": the HTTP method says nothing about intent.
        tool = re.sub(r"^api[-_](get|post|put|patch|delete)[-_]", "", tool or name, flags=re.IGNORECASE)
        # Each app's who-am-I tool is always offered (only the named app's, if the request names one), on top of
        # the best matches, so "my ..." works in any wording or language instead of guessing a username.
        if (server in named or not named) and (WHO_AM_I_NAME.search(tool) or WHO_AM_I_TEXT.search(description)):
            who_am_i.append(name)
            continue
        score = 2 * len(wanted & _words(tool)) + len(wanted & _words(description)) + (5 if server in named else 0)
        if score >= min_score:
            scored.append((-score, index, name))
    return [name for _, _, name in sorted(scored)[:limit]] + who_am_i


if __name__ == "__main__":
    tools = [("notion__API-post-search", "Search by title"), ("github__list_issues", "List issues in a repository"),
             ("slack__send_message", "Send a message to a channel"), ("github__create_issue", "Create an issue")]
    assert rank_tools("create a GitHub issue about the login bug", tools, 2) == ["github__create_issue", "github__list_issues"]
    assert rank_tools("post in the #general channel", tools, 1) == ["slack__send_message"]
    assert rank_tools("hello", tools, 2) == ["notion__API-post-search", "github__list_issues"]  # no match: input order
    assert rank_tools("hello", tools, 2, min_score=1) == []
    print("tool selection self-check passed")

