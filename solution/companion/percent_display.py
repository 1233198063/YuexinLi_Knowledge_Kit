"""Conflicts presentation only: pad plain percentage spellings without rounding.

Owner: isolated format experiment. Unsafe forms remain exactly as supplied;
source quotes and all financial selection/identity stay Parent-owned.
"""
import copy
from decimal import Decimal, InvalidOperation
import re


# Recognize exponent/sign forms as whole tokens to avoid formatting a suffix.
# Scientific notation and Unicode-minus forms are deliberately left unchanged.
_TOKEN = re.compile(
    r'(?<![\w.,$+\-\u2212\u2010-\u2015])'
    r'(?P<number>[+\-\u2212]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?)'
    r'(?P<space>[ \t]*)%(?!\w)')
_PLAIN = re.compile(r'[+\-]?(?:\d+(?:\.\d*)?|\.\d+)')


def format_percent_text(text):
    if not isinstance(text, str):
        return text

    def replace(match):
        original = match['number']
        if not _PLAIN.fullmatch(original):
            return match[0]
        if '.' in original:
            fractional_digits = len(original.rsplit('.', 1)[1])
            replacement = original + '0' * max(0, 2 - fractional_digits)
        else:
            replacement = original + '.00'
        try:
            before, after = Decimal(original), Decimal(replacement)
            if not before.is_finite() or not after.is_finite() or before != after:
                return match[0]
        except InvalidOperation:
            return match[0]
        return replacement + match['space'] + '%'

    return _TOKEN.sub(replace, text)


def format_conflicts(conflicts):
    result = copy.deepcopy(conflicts)
    for conflict in result:
        if isinstance(conflict.values, list):
            conflict.values = [format_percent_text(value) for value in conflict.values]
        conflict.resolution = format_percent_text(conflict.resolution)
    return result
