"""Module 1: policy document -> DRAFT facts. The model proposes; code disposes (I3, I4, I5).

The model returns facts each with a verbatim quote. Code rejects any fact whose quote is not found verbatim in the source
(whitespace ignored) or whose number does not appear in its own quote. Accepted facts become UNCONFIRMED drafts: a human
must confirm (and only then freeze) them. Nothing here ever confirms or freezes anything.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional, Union

from pydantic import BaseModel, Field

from .extract import NUM, _num
from .llm import LLMClient, LLMError
from .models import Clause, Fact, Scope

LONG_AGO = date(2000, 1, 1)
MIN_QUOTE = 6
OPS = ("=", "<=", ">=")

SYSTEM = (
    "你是制度条款抽取助手。只从给定的制度原文中抽取可核对的数值型事实（金额、笔数、天数、比例、期限、利率等）。"
    "严格要求：1) 每条事实必须附 quote，quote 必须逐字摘自原文（不得改写、不得拼接、不得省略号），且必须包含该事实的数字；"
    "2) 不要推测原文没写的内容；3) 同一数字适用于不同产品、地区、渠道时分别列出；4) 原文写明“原为…现调整为…”时只抽现行值，旧值另列并在 condition 注明“旧版”；"
    "5) 只输出 JSON，不要任何其他文字。"
)
SCHEMA = ('输出格式：{"facts":[{"key":"英文小写点分键，如 fee_waiver.min_purchases","topic":"主题（中文）","value":数字,'
          '"op":"= 或 <= 或 >=","unit":"单位，如 笔/天/元/%/月/年","condition":"适用条件（没有则空字符串）",'
          '"product":"产品，原文未限定则 null","region":"地区，原文未限定则 null","channel":"渠道，原文未限定则 null",'
          '"effective_from":"YYYY-MM-DD，原文未写则 null","quote":"逐字摘自原文的句子"}]}')


class DraftFact(BaseModel):
    key: str
    topic: str = ""
    value: Union[float, str]
    op: str = "="
    unit: str = ""
    condition: str = ""
    scope: Scope = Field(default_factory=Scope)
    effective_from: Optional[date] = None
    quote: str
    quote_at: int = -1                       # offset of the quote in the source text
    warnings: list[str] = Field(default_factory=list)


class Rejected(BaseModel):
    raw: dict
    reason: str


class DraftResult(BaseModel):
    accepted: list[DraftFact] = Field(default_factory=list)
    rejected: list[Rejected] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _squash(s: str) -> tuple[str, list[int]]:
    """Text without whitespace, plus each kept character's index in the original."""
    out, idx = [], []
    for i, ch in enumerate(s):
        if not ch.isspace():
            out.append(ch); idx.append(i)
    return "".join(out), idx


def numbers_in(text: str) -> list[float]:
    out = []
    for m in re.finditer(NUM, (text or "").replace(",", "").replace("，", ""), re.I):
        v = _num(m.group(0))
        if v is not None:
            out.append(v)
    return out


def _num_or_none(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None
    return None


def _opt(v) -> Optional[str]:
    return v.strip() if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none", "无") else None


def validate(raw: dict, source: str) -> tuple[Optional[DraftFact], str]:
    """(fact, '') when the draft passes the checks, else (None, reason)."""
    if not isinstance(raw, dict):
        return None, "not_an_object"
    quote = raw.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        return None, "no_quote"
    sq, sidx = _squash(source)
    qq, _ = _squash(quote)
    if len(qq) < MIN_QUOTE:
        return None, "quote_too_short"
    at = sq.find(qq)
    if at < 0:
        return None, "quote_not_verbatim"
    key = raw.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)*", key.strip()):
        return None, "bad_key"
    op = raw.get("op") or "="
    if op not in OPS:
        return None, "bad_op"
    val = raw.get("value")
    num = _num_or_none(val)
    if num is None:
        return None, "bad_value"           # non-numeric facts are out of scope for the automatic path
    if not any(abs(num - n) < 1e-9 for n in numbers_in(quote)):
        return None, "number_not_in_quote"
    eff = None
    if _opt(raw.get("effective_from")):
        try:
            eff = date.fromisoformat(str(raw["effective_from"])[:10])
        except ValueError:
            return None, "bad_date"
    warns = []
    scope = Scope(product=_opt(raw.get("product")), channel=_opt(raw.get("channel")), region=_opt(raw.get("region")))
    for dim in ("product", "channel", "region"):
        v = getattr(scope, dim)
        if v and _squash(v)[0] not in qq:
            warns.append(f"{dim} “{v}” 不在引文中，需人工核对")
    if eff and not (str(eff.year) in sq and str(eff.day) in sq):
        warns.append("生效日期未在原文中找到，需人工核对")
    if not eff:
        warns.append("原文未给生效日期，确认前必须补")
    return DraftFact(key=key.strip(), topic=str(raw.get("topic") or ""), value=num, op=op, unit=str(raw.get("unit") or ""),
                     condition=str(raw.get("condition") or ""), scope=scope, effective_from=eff, quote=quote.strip(),
                     quote_at=sidx[at], warnings=warns), ""


def chunks(text: str, limit: int = 6000) -> list[str]:
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if cur and len(cur) + len(para) > limit:
            parts.append(cur); cur = ""
        cur += para + "\n\n"
    if cur.strip():
        parts.append(cur)
    return parts or [text]


def parse_json(s: str) -> dict:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-z]*\n?|```$", "", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        a, b = s.find("{"), s.rfind("}")
        if a >= 0 and b > a:
            return json.loads(s[a:b + 1])
        raise


def draft_facts(source: str, client: LLMClient) -> DraftResult:
    res, seen = DraftResult(), set()
    for part in chunks(source):
        msgs = [{"role": "system", "content": SYSTEM + SCHEMA}, {"role": "user", "content": "制度原文：\n" + part}]
        try:
            data = parse_json(client.chat(msgs, json_mode=True))
            items = data.get("facts", []) if isinstance(data, dict) else []
        except (LLMError, json.JSONDecodeError) as e:
            res.errors.append(f"{type(e).__name__}: {e}")
            continue
        for raw in items:
            f, why = validate(raw, source)       # always checked against the FULL source, not just the chunk
            if f is None:
                res.rejected.append(Rejected(raw=raw if isinstance(raw, dict) else {"value": str(raw)}, reason=why))
                continue
            sig = (f.key, f.value, f.op, f.unit, f.scope.model_dump_json(), f.condition)
            if sig not in seen:
                seen.add(sig); res.accepted.append(f)
    return res


def _slug(*parts) -> str:
    return re.sub(r"[^0-9A-Za-z一-鿿]+", "-", "-".join(str(p or "") for p in parts)).strip("-")


def to_clauses(res: DraftResult, source_ref: str, default_effective_from: date | None = None, version: str = "v1") -> list[Clause]:
    """Unconfirmed draft clauses. A fact with no date in the source needs `default_effective_from` chosen by a human; otherwise it is skipped.
    The clause text is the verbatim quote. Status is always 'draft'."""
    out = []
    for f in res.accepted:
        eff = f.effective_from or default_effective_from
        if eff is None:
            continue
        out.append(Clause(id=_slug(f.scope.product, f.scope.region, f.key, f.condition if f.condition else ""), version=version, topic=f.topic,
                          text=f.quote, scope=f.scope, facts=[Fact(key=f.key, value=f.value, op=f.op, unit=f.unit, condition=f.condition)],
                          effective_from=eff, status="draft", source_ref=f"{source_ref}｜引文位置 {f.quote_at}｜LLM草拟，待人工确认"))
    return out


# ---- measurement against a hand-made answer key (report only real numbers)
def _unit(u: str, lenient: bool = False) -> str:
    u = (u or "").replace("个", "").replace("％", "%").strip()
    return u.split("/")[0] if lenient else u            # lenient: '元/天' counts as '元' (the period is not what is being checked)


def _scope(v, lenient: bool = False):
    return re.sub(r"(地区|渠道)$", "", v).strip() if lenient and isinstance(v, str) else v


def evaluate(accepted: list[DraftFact], key: list[dict], lenient: bool = False) -> dict:
    """Match on value+unit and every scope field the key item states. Each key item and each draft is used at most once.
    Key items marked optional (e.g. a superseded old value) neither help nor hurt if found, and are not missed if absent."""
    def hit(f: DraftFact, k: dict) -> bool:
        if abs(float(k["value"]) - float(f.value)) > 1e-9 or _unit(k.get("unit", ""), lenient) != _unit(f.unit, lenient):
            return False
        return all(_scope(getattr(f.scope, d), lenient) == _scope(k.get(d), lenient) for d in ("product", "region", "channel") if d in k)

    used, tp, missed, opt_hit = set(), 0, [], 0
    for k in sorted(key, key=lambda k: bool(k.get("optional"))):     # required items claim drafts first
        j = next((i for i, f in enumerate(accepted) if i not in used and hit(f, k)), None)
        if k.get("optional"):
            if j is not None:
                used.add(j); opt_hit += 1
        elif j is None:
            missed.append(k)
        else:
            used.add(j); tp += 1
    required = [k for k in key if not k.get("optional")]
    extra = [f for i, f in enumerate(accepted) if i not in used]
    n_judged = tp + len(extra)
    prec = tp / n_judged if n_judged else 0.0
    rec = tp / len(required) if required else 0.0
    return {"n_key": len(required), "n_accepted": len(accepted), "optional_matched": opt_hit, "true_positive": tp,
            "precision": round(prec, 3), "recall": round(rec, 3), "missed": missed,
            "extra": [{"key": f.key, "value": f.value, "unit": f.unit, "scope": f.scope.model_dump(exclude_none=True), "quote": f.quote} for f in extra]}
