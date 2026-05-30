"""日志中敏感 token 的展示格式。"""


def format_token_for_log(token: str) -> str:
    return token if token else "(empty)"
