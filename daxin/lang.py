"""Language packs for claim extraction: zh-Hans, zh-Hant, en, pt.

Each pack gives unit words, leading currency symbols, number words and the lexicons for promises and hand-offs.
An answer is read with the pack of its declared language; an unknown or empty language uses all packs together
(the behaviour of rules-0.1). Packs are deliberately small and literal: what they miss falls to 'pending human' (I3).
"""
from __future__ import annotations

import re

PACKS: dict[str, dict] = {
    "zh-Hans": {
        "units": {"笔": r"笔|次|宗", "天": r"天|日|个工作日|工作日", "元": r"元|块|圆|港元|人民币",
                  "%": r"%|％|个百分点", "月": r"个月|月", "年": r"年"},
        "lead": {"元": r"¥|￥|HK\$|HKD|RMB|CNY", "%": r"百分之"},
        "measure": r"个",
        "promise": [r"保证", r"一定(?:能|会|可以|不会)", r"绝对", r"肯定(?:能|会)", r"无风险", r"零风险", r"稳赚", r"保本保收益",
                    r"已为您(?:批准|通过)"],
        "handoff": [r"转人工", r"人工(?:客服|服务|坐席|座席)", r"客服(?:热线|电话)", r"联系(?:客户经理|网点)", r"柜台", r"拨打"],
    },
    "zh-Hant": {
        "units": {"笔": r"筆|次|宗", "天": r"天|日|個工作日|工作日", "元": r"元|塊|圓|港元|港幣|人民幣|澳門元|澳門幣",
                  "%": r"%|％|個百分點", "月": r"個月|月", "年": r"年"},
        "lead": {"元": r"HK\$|HKD|MOP\$?|RMB|CNY|¥|￥", "%": r"百分之"},
        "measure": r"個",
        "promise": [r"保證", r"一定(?:能|會|可以|不會)", r"絕對", r"肯定(?:能|會)", r"無風險", r"零風險", r"穩賺", r"保本保收益",
                    r"已為您(?:批准|通過)", r"包賺"],
        "handoff": [r"轉人工", r"人工(?:客服|服務|坐席|座席)", r"客服(?:熱線|電話)", r"聯絡(?:客戶經理|分行)", r"聯繫(?:客戶經理|網點|分行)",
                    r"櫃檯", r"撥打", r"致電"],
    },
    "en": {
        "units": {"笔": r"purchases?|transactions?|times", "天": r"(?:calendar |business |working )?days?",
                  "元": r"yuan|dollars?|HKD|RMB|CNY|patacas?|MOP", "%": r"%|percent|per cent|percentage points?",
                  "月": r"months?", "年": r"years?"},
        "lead": {"元": r"HK\$|US\$|MOP\$|\$|¥|RMB|HKD|CNY"},
        "measure": r"",
        "words": {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                  "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
                  "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
                  "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90},
        "hundred": r"hundred",
        "promise": [r"guarantee[ds]?", r"risk[- ]free", r"definitely will", r"(?:can|will) never lose", r"no risk",
                    r"(?:has|have) been approved for you"],
        "handoff": [r"human agent", r"speak (?:to|with) (?:a|an|our) (?:agent|representative|officer)", r"customer service (?:hotline|line)",
                    r"call (?:our|the) hotline", r"visit (?:a|any|our) branch", r"relationship manager"],
    },
    "pt": {
        "units": {"笔": r"compras?|transa[cç](?:ão|ões)|vezes", "天": r"dias?(?: úteis| corridos)?",
                  "元": r"patacas?|d[oó]lares?|yuan|renminbi|MOP|HKD|RMB", "%": r"%|por cento|pontos percentuais",
                  "月": r"m[eê]s(?:es)?|meses", "年": r"anos?"},
        "lead": {"元": r"MOP\$?|HK\$|R\$|\$|¥|RMB|HKD"},
        "measure": r"",
        "words": {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
                  "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14,
                  "quinze": 15, "dezasseis": 16, "dezesseis": 16, "dezassete": 17, "dezessete": 17, "dezoito": 18,
                  "dezanove": 19, "dezenove": 19, "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60,
                  "setenta": 70, "oitenta": 80, "noventa": 90, "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
                  "trezentos": 300, "trezentas": 300, "quatrocentos": 400, "quinhentos": 500, "seiscentos": 600,
                  "setecentos": 700, "oitocentos": 800, "novecentos": 900},
        "promise": [r"garanti(?:do|da|mos|a)", r"sem (?:nenhum )?risco", r"nunca (?:vai|irá) perder", r"com certeza (?:vai|irá)",
                    r"já (?:foi|está) aprovad[oa]"],
        "handoff": [r"atendente", r"falar com (?:um|uma|o|a) (?:atendente|funcionári[oa]|gestor)", r"linha de apoio",
                    r"ligue para", r"dirija-se a (?:uma|qualquer) (?:sucursal|agência|balcão)", r"balcão"],
    },
}
ALIASES = {"zh": "zh-Hans", "zh-CN": "zh-Hans", "zh-Hans-CN": "zh-Hans", "zh-TW": "zh-Hant", "zh-HK": "zh-Hant", "zh-MO": "zh-Hant",
           "en-US": "en", "en-GB": "en", "en-HK": "en", "pt-PT": "pt", "pt-BR": "pt", "pt-MO": "pt"}
CODES = tuple(PACKS)


def packs(lang: str = "") -> list[dict]:
    code = ALIASES.get(lang, lang)
    return [PACKS[code]] if code in PACKS else list(PACKS.values())


def _alt(parts: list[str]) -> str:
    return "|".join(f"(?:{p})" for p in parts if p)


def unit_re(unit: str, lang: str = "") -> str:
    return _alt([p["units"].get(unit, "") for p in packs(lang)])


def lead_re(unit: str, lang: str = "") -> str:
    return _alt([p.get("lead", {}).get(unit, "") for p in packs(lang)])


def measure_re(lang: str = "") -> str:
    return _alt([p.get("measure", "") for p in packs(lang)])


def number_words(lang: str = "") -> dict[str, int]:
    out: dict[str, int] = {}
    for p in packs(lang):
        out.update(p.get("words", {}))
    return out


def lexicon(kind: str, lang: str = "") -> re.Pattern:
    return re.compile(_alt([w for p in packs(lang) for w in p[kind]]), re.I)
