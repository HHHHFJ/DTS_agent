from __future__ import annotations

import re
from dataclasses import dataclass


IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

KEYWORDS = {
    "alignas",
    "alignof",
    "and",
    "as",
    "auto",
    "bool",
    "break",
    "case",
    "catch",
    "char",
    "class",
    "const",
    "constexpr",
    "continue",
    "def",
    "delete",
    "do",
    "double",
    "else",
    "enum",
    "except",
    "explicit",
    "extern",
    "false",
    "float",
    "for",
    "from",
    "if",
    "import",
    "int",
    "lambda",
    "long",
    "namespace",
    "new",
    "noexcept",
    "none",
    "nullptr",
    "or",
    "private",
    "protected",
    "public",
    "raise",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "std",
    "struct",
    "switch",
    "template",
    "this",
    "throw",
    "true",
    "try",
    "typedef",
    "typename",
    "unsigned",
    "using",
    "void",
    "volatile",
    "while",
}

SEMANTIC_NAME_HINTS = {
    "access",
    "admin",
    "auth",
    "cap",
    "cmd",
    "command",
    "credential",
    "exec",
    "file",
    "input",
    "open",
    "passwd",
    "password",
    "path",
    "perm",
    "priv",
    "query",
    "role",
    "secret",
    "shell",
    "sql",
    "token",
    "url",
    "user",
}


@dataclass(frozen=True)
class CodeToken:
    value: str
    kind: str


def has_logical_code_change(old_code: str, new_code: str) -> bool:
    """Return False for whitespace/comment-only and identifier-only edits."""
    old_tokens = tokenize_code(old_code)
    new_tokens = tokenize_code(new_code)
    if not old_tokens and not new_tokens:
        return False
    if _token_values(old_tokens) == _token_values(new_tokens):
        return False
    if len(old_tokens) != len(new_tokens):
        return True

    for index, (old_token, new_token) in enumerate(zip(old_tokens, new_tokens, strict=True)):
        if old_token.value == new_token.value and old_token.kind == new_token.kind:
            continue
        if _is_ignorable_identifier_change(old_tokens, new_tokens, index):
            continue
        return True
    return False


def tokenize_code(code: str) -> list[CodeToken]:
    tokens: list[CodeToken] = []
    text = _strip_comments(code or "")
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in {'"', "'"}:
            value, index = _read_string(text, index)
            tokens.append(CodeToken(value, "string"))
            continue
        if char.isdigit():
            value, index = _read_number(text, index)
            tokens.append(CodeToken(value, "number"))
            continue
        match = IDENTIFIER_RE.match(text, index)
        if match:
            value = match.group(0)
            kind = "keyword" if value.lower() in KEYWORDS else "identifier"
            tokens.append(CodeToken(value, kind))
            index = match.end()
            continue
        two = text[index : index + 2]
        if two in {"::", "->", "==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=", "/=", "%="}:
            tokens.append(CodeToken(two, "operator"))
            index += 2
            continue
        tokens.append(CodeToken(char, "operator"))
        index += 1
    return tokens


def _strip_comments(code: str) -> str:
    result: list[str] = []
    index = 0
    in_line_comment = False
    in_block_comment = False
    quote: str | None = None
    escape = False

    while index < len(code):
        char = code[index]
        next_char = code[index + 1] if index + 1 < len(code) else ""
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                result.append(char)
            index += 1
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
            else:
                if char == "\n":
                    result.append(char)
                index += 1
            continue
        if quote:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            result.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue
        if char == "#":
            previous = code[index - 1] if index > 0 else "\n"
            if previous == "\n":
                in_line_comment = True
                index += 1
                continue
        result.append(char)
        index += 1
    return "".join(result)


def _read_string(text: str, start: int) -> tuple[str, int]:
    quote = text[start]
    index = start + 1
    escape = False
    while index < len(text):
        char = text[index]
        if escape:
            escape = False
        elif char == "\\":
            escape = True
        elif char == quote:
            index += 1
            break
        index += 1
    return text[start:index], index


def _read_number(text: str, start: int) -> tuple[str, int]:
    index = start + 1
    while index < len(text) and re.match(r"[A-Za-z0-9_.]", text[index]):
        index += 1
    return text[start:index], index


def _token_values(tokens: list[CodeToken]) -> list[tuple[str, str]]:
    return [(token.kind, token.value) for token in tokens]


def _is_ignorable_identifier_change(
    old_tokens: list[CodeToken],
    new_tokens: list[CodeToken],
    index: int,
) -> bool:
    old_token = old_tokens[index]
    new_token = new_tokens[index]
    if old_token.kind != "identifier" or new_token.kind != "identifier":
        return False
    if _identifier_style_key(old_token.value) == _identifier_style_key(new_token.value):
        return True
    if not _is_variable_position(old_tokens, index) or not _is_variable_position(new_tokens, index):
        return False
    if _has_semantic_hint(old_token.value) or _has_semantic_hint(new_token.value):
        return False
    return True


def _identifier_style_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).lower()


def _is_variable_position(tokens: list[CodeToken], index: int) -> bool:
    previous_value = tokens[index - 1].value if index > 0 else ""
    next_value = tokens[index + 1].value if index + 1 < len(tokens) else ""
    value = tokens[index].value
    if value.isupper():
        return False
    if previous_value in {"::", ".", "->"}:
        return False
    if next_value in {"::", "("}:
        return False
    return True


def _has_semantic_hint(value: str) -> bool:
    lowered = value.lower()
    return any(hint in lowered for hint in SEMANTIC_NAME_HINTS)
