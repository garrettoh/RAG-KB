"""Focused text redaction, without network access or an exhaustive DLP claim.

Labels provide context for otherwise indistinguishable secrets. Address candidates
are validated rather than treating every dotted number or colon as an address.
"""

import ipaddress
import re


_EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}(?![\w-])")
_MAC = re.compile(r"(?<![\w:.-])(?:[0-9a-f]{2}(?P<sep>[:-])(?:[0-9a-f]{2}(?P=sep)){4}[0-9a-f]{2}|[0-9a-f]{4}(?:\.[0-9a-f]{4}){2})(?!\w|[:.-][0-9a-f])", re.I)
_BRACKET_IP = re.compile(r"\[(?P<ip>[0-9a-f:.]+(?:%[\w.-]+)?)\](?::\d{1,5})?", re.I)
_IPV6 = re.compile(r"(?<![\w:.])(?=[0-9a-f:.]*:)[0-9a-f:.]*:[0-9a-f:.]*(?:%[\w.-]+)?(?![\w:])", re.I)
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?!\w|\.\d)")
_URL_AUTH = re.compile(r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)(?!\[REDACTED_)[^\s/@<>`]+@", re.I)
_BEARER = re.compile(r"(?P<label>\bBearer[ \t]+)(?!\[REDACTED_)[A-Za-z0-9._~+/-]+=*", re.I)
_KEY_PREFIX = re.compile(
    r"(?<![\w-])(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}"
    r"|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    r"|xox[baprs]-[A-Za-z0-9-]{16,})(?![\w-])"
)

_PASSWORD_LABEL = r"(?:[a-z0-9]+_)*(?:password|passwd|pwd|passphrase)"
_API_LABEL = (
    r"(?:[a-z0-9]+_)*(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|"
    r"refresh[_ -]?token|client[_ -]?secret|private[_ -]?key|secret[_ -]?key|token|secret)"
)
_SERIAL_LABEL = r"(?:serial(?:[_ -]?(?:number|no))?|s/n)"
_ANY_LABEL = rf"(?:{_PASSWORD_LABEL}|{_API_LABEL}|{_SERIAL_LABEL})"
_QUERY_SECRET = re.compile(
    rf"(?P<prefix>[?&](?P<label>{_ANY_LABEL})=)(?P<value>[^&#\s\"'`<>\[\]]+)", re.I,
)
_LABELS = re.compile(
    rf"(?<![\w-])(?P<flag>--)?(?P<label>{_ANY_LABEL})"
    r"(?P<close>[\"']?)(?P<separator>[ \t]*[:=][ \t]*(?:\r?\n[ \t]+)?|[ \t]+)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    rf"(?:(?!,(?:{_ANY_LABEL})[ \t]*[:=])[^\s\"'`;\}}\)\]<>\[])+)",
    re.I,
)
_YAML_SECRET = re.compile(
    rf"^(?P<indent>[ \t]*)(?P<prefix>[\"']?(?P<label>{_PASSWORD_LABEL}|{_API_LABEL}|{_SERIAL_LABEL})"
    r"[\"']?[ \t]*:[ \t]*)[|>][+-]?[0-9]?(?:[ \t]+\#.*)?\r?\n$", re.I,
)
_YAML_PLAIN = re.compile(
    rf"^(?P<prefix>[ \t]*[\"']?(?P<label>{_ANY_LABEL})[\"']?[ \t]*:[ \t]+)"
    r"(?P<value>[^\s\"'\[\{\|>][^\s]*)(?P<following>[^\r\n]*)(?P<cr>\r?)$", re.I | re.M,
)
_PROCEDURE = re.compile(r"^(?:[#>`]|[-*]\s|\d+[.)]\s|(?:restart|run|verify|check|install|open|click|set|use|apply|connect|reset|change|rotate|create|delete|remove|enable|disable)\b)", re.I)
_SIGNOFF = re.compile(r"^(?:--\s*|(?:(?:kind|best|warm)\s+)?regards[,]?|(?:many\s+)?thanks[,]?|sincerely[,]?)$", re.I)
_MOBILE = re.compile(r"^[ \t]*Sent from my (?:iPhone|iPad|Android(?: device)?)[.!]?[ \t]*$", re.I)
_CONFIDENTIAL = re.compile(r"^(?:confidentiality (?:notice|disclaimer)\s*:|this (?:email|e-mail|message)(?: and (?:any |its )?attachments)? (?:is |are |contains ).*confidential)", re.I)


def _redact_ip(match: re.Match[str]) -> str:
    candidate = match.groupdict().get("ip") or match.group()
    # A full stop is sentence punctuation; zone identifiers are part of the value.
    trailing = ""
    if candidate.endswith("."):
        candidate, trailing = candidate[:-1], "."
    address = candidate.split("%", 1)[0]
    if ":" in address and "." in address and address.count(":") == 1:
        address = address.rsplit(":", 1)[0]  # IPv4:port
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return match.group()
    return "[REDACTED_IP]" + trailing


def _redact_label(match: re.Match[str]) -> str:
    # A bare prose mention is not an assignment or a command option.
    if not match["flag"] and not any(c in match["separator"] for c in ":="):
        return match.group()
    value = match["value"]
    quoted = value[0] in "\"'"
    content = value[1:-1] if quoted else value
    if not content or content.lower() in {"null", "none", "true", "false"} or content.startswith("[REDACTED_"):
        return match.group()
    before = match.string[:match.start()].rsplit("\n", 1)[-1]
    if (not match["flag"] and ":" in match["separator"] and content.startswith("#")
            and re.fullmatch(r"[ \t]*[\"']?", before)):
        return match.group()  # A YAML comment begins after whitespace, not inside a value.
    # Do not eat prose such as "password: reset it using the portal".
    following = match.string[match.end():]
    if (not quoted and not match["flag"] and ":" in match["separator"]
            and (_PROCEDURE.fullmatch(content) or content.lower() == "port")
            and re.match(r"[ \t]+(?:it|one|the|a|your|using|configuration)\b", following, re.I)):
        return match.group()
    replacement = f"[REDACTED_{_label_kind(match['label'])}]"
    if quoted:
        replacement = value[0] + replacement + value[-1]
    return match.group()[:match.start("value") - match.start()] + replacement


def _label_kind(label: str) -> str:
    if re.fullmatch(_PASSWORD_LABEL, label, re.I):
        return "PASSWORD"
    if re.fullmatch(_SERIAL_LABEL, label, re.I):
        return "SERIAL"
    return "API_KEY"


def _redact_query(match: re.Match[str]) -> str:
    # Query separators have meaning inside URLs; ordinary assignments can contain
    # literal '&', '#' and ',' as part of the credential.
    before = match.string[:match.start()].rsplit(None, 1)[-1:]
    if not before or not re.search(r"[a-z][a-z0-9+.-]*://[^\s]*$", before[0], re.I):
        return match.group()
    return match["prefix"] + f"[REDACTED_{_label_kind(match['label'])}]"


def _redact_yaml_secrets(text: str) -> str:
    """Consume indented literal/folded YAML scalars, retaining adjacent keys."""
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    index = 0
    while index < len(lines):
        match = _YAML_SECRET.match(lines[index])
        if match:
            end = index + 1
            while end < len(lines):
                line = lines[end]
                indent = len(line) - len(line.lstrip(" \t"))
                if line.strip() and indent <= len(match["indent"]):
                    break
                end += 1
            if end > index + 1:
                last = lines[end - 1]
                newline = "\r\n" if last.endswith("\r\n") else "\n" if last.endswith("\n") else ""
                result.append(match["indent"] + match["prefix"] + f"[REDACTED_{_label_kind(match['label'])}]" + newline)
                index = end
                continue
        result.append(lines[index])
        index += 1
    return "".join(result)


def _redact_yaml_plain(match: re.Match[str]) -> str:
    """Plain YAML atoms use different punctuation rules from shell/JSON values."""
    value, following = match["value"], match["following"]
    if value.startswith("#") or value.lower() in {"null", "none", "true", "false"}:
        return match.group()
    if ((_PROCEDURE.fullmatch(value) or value.lower() == "port")
            and re.match(r"[ \t]+(?:it|one|the|a|your|using|configuration)\b", following, re.I)):
        return match.group()
    # Preserve a prose clause such as "API key: abc; retry". In YAML, whitespace
    # followed by '#' starts a comment, whereas an embedded '#' belongs to value.
    punctuation = ";" if value.endswith(";") and following.strip() and not following.lstrip().startswith("#") else ""
    return match["prefix"] + f"[REDACTED_{_label_kind(match['label'])}]" + punctuation + following + match["cr"]


def _signature_line(line: str) -> bool:
    if _PROCEDURE.match(line) or len(line) > 100:
        return False
    if _EMAIL.search(line) or re.match(r"(?:https?://|(?:tel|phone|fax|mobile|email)\s*:|\+?\d)", line, re.I):
        return True
    words = line.split()
    return (len(words) <= 8 and not re.search(r"[.!?]$", line)
            and all(word[0].isupper() or word in {"of", "and", "for", "de", "van", "von", "&"} for word in words))


def _redact_footers(text: str) -> str:
    """Recognize short terminal contact blocks, never arbitrary signoff suffixes."""
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    fence: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        if fence is None and _MOBILE.fullmatch(stripped):
            result.append("[REDACTED_SIGNATURE]" + ending)
        elif fence is None and _CONFIDENTIAL.match(stripped):
            end = index + 1
            while end < len(lines) and lines[end].strip() and not _PROCEDURE.match(lines[end].strip()) and end - index < 10:
                end += 1
            last = lines[end - 1]
            suffix = "\r\n" if last.endswith("\r\n") else "\n" if last.endswith("\n") else ""
            result.append("[REDACTED_SIGNATURE]" + suffix)
            index = end
            continue
        elif fence is None and _SIGNOFF.fullmatch(stripped):
            tail = lines[index + 1:]
            content = [part.strip() for part in tail if part.strip()]
            if (0 < len(tail) <= 12 and any(_EMAIL.search(part) for part in content)
                    and all(_signature_line(part) for part in content)):
                suffix = "\r\n" if text.endswith("\r\n") else "\n" if text.endswith("\n") else ""
                result.append("[REDACTED_SIGNATURE]" + suffix)
                break
            result.append(line)
        else:
            result.append(line)
        index += 1
    return "".join(result)


def sanitize_text(text: str) -> str:
    """Redact recognized values while retaining markdown and instruction text.

    Stable type markers make repeated sanitization safe. Unlabeled arbitrary
    secrets, names, hostnames, obfuscated values and unusual signatures can remain.
    Raw originals require separate access controls and human review.
    """
    text = _redact_footers(text)
    text = _redact_yaml_secrets(text)
    text = _YAML_PLAIN.sub(_redact_yaml_plain, text)
    text = _URL_AUTH.sub(lambda match: match["scheme"] + "[REDACTED_CREDENTIALS]@", text)
    text = _BEARER.sub(lambda match: match["label"] + "[REDACTED_TOKEN]", text)
    text = _QUERY_SECRET.sub(_redact_query, text)
    text = _LABELS.sub(_redact_label, text)
    text = _KEY_PREFIX.sub("[REDACTED_API_KEY]", text)
    text = _MAC.sub("[REDACTED_MAC]", text)
    text = _BRACKET_IP.sub(_redact_ip, text)
    text = _IPV6.sub(_redact_ip, text)
    text = _IPV4.sub(_redact_ip, text)
    return _EMAIL.sub("[REDACTED_EMAIL]", text)
