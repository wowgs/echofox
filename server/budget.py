"""The token budgets of the context: an estimate of a text's tokens, and one rule for every budget.

The estimate counts the characters of a text by kind (Cyrillic, Latin, digit, whitespace, other) and weighs each kind
by the model's tokens per character of it. The weights are the model's, in its catalog entry ("tokenWeights"), fitted
against the model's own tokenizer by calibrate_tokens.py. The client has the same estimate (FocusSnapshot's
TokenEstimate), so that the screen is read up to the same budget. No model is needed: the adapters and the client
can count before llama-server runs.

The rule (take): greedy and not strict. The items are taken in their order (the messages newest first, the documents
as the adapter gives them, the terms of the documents and then of the messages from the newest) until the sum reaches the budget; the item that reaches it is
taken whole, and the taking stops there.
"""
import math

KINDS = ("cyrillic", "latin", "digit", "space", "other")
# For a model whose catalog entry has no weights: a token per 3.4 characters, of any kind, the plain ratio of the texts
# that fitted Gemma 4 E4B's weights (catalog.py); its |error| there was twice the fitted weights' (4.6 % median)
FALLBACK = dict.fromkeys(KINDS, 0.295)
# Whitespace is Unicode's White_Space property (PropList.txt), which is what Swift's isWhitespace of a scalar tests, so
# that the server and the client count the same characters as whitespace. Python's str.isspace() is not it: it also
# takes U+001C-U+001F (the information separators, whose bidirectional class is B or S).
WHITE_SPACE = frozenset(map(chr, [*range(0x09, 0x0E), 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029,
                                  0x202F, 0x205F, 0x3000]))
# The ceiling is taken of the sum less SLACK. A sum that is a whole number in decimal can come out a hair over it in
# binary, and the two sides add in different ways: Python's sum() compensates the rounding, the client's loop does not.
# For 30 Cyrillic letters, 5 Latin, 5 digits and 10 spaces with Gemma 4 E4B's weights, sum() gives 20.0 and the loop
# 20.000000000000004, a token more without the slack. The weights have three decimals, so a true sum that is not whole
# is at least 0.001 over a whole number.
SLACK = 1e-9


def kind(c):
    if "Ѐ" <= c <= "ӿ":
        return "cyrillic"
    if "a" <= c <= "z" or "A" <= c <= "Z":
        return "latin"
    if "0" <= c <= "9":
        return "digit"
    if c in WHITE_SPACE:
        return "space"
    return "other"


def counts(text):
    """The characters of the text by kind."""
    out = dict.fromkeys(KINDS, 0)
    for c in text:
        out[kind(c)] += 1
    return out


def count(text, weights):
    """The estimated tokens of the text, with the model's weights (tokens per character of each kind)."""
    return count_from(counts(text), weights or FALLBACK)


def count_from(by_kind, weights):
    return math.ceil(sum(weights.get(k, 0) * n for k, n in by_kind.items()) - SLACK)


def take(items, budget, cost):
    """The first items, greedily, until their cost reaches `budget`: the item that reaches it is the last one taken,
    whole. (items, used)."""
    kept, used = [], 0
    for item in items:
        if used >= budget:
            break
        kept.append(item)
        used += cost(item)
    return kept, used
