"""The knobs of a recording: one table for their names, types, ranges and defaults. A knob can be set in the config's
section "server" (for every recording), in a model's "options" (for that model's recordings, over the server's), or
both; a client's start message may send "options" too (an experiment), over the model's. Not tuned unless noted."""
from dataclasses import dataclass
from typing import Callable

import constants


@dataclass(frozen=True)
class Knob:
    key: str                # in the config file
    name: str               # in the code, and the command-line flag with dashes
    kind: type
    ok: Callable
    default: object         # None: none (the code says what that means)
    server: bool            # may be set in the section "server"
    option: bool            # may be set in a model's or a client's "options"
    help: str


KNOBS = [
    Knob("pieceSeconds", "piece_seconds", float, lambda v: 5 <= v <= constants.MODEL_MAX_SECONDS, 20.0, True, True,
         "the wanted length of a piece; a recording is cut, after the stop, into pieces as close to it as possible and "
         f"equal, none longer than {constants.MODEL_MAX_SECONDS} s"),
    Knob("cutSearchSeconds", "cut_search_seconds", float, lambda v: 0 < v <= 10, 3.0, True, True,
         "how far from its equal point a cut may move to the quietest moment"),
    Knob("thresholdDb", "threshold_db", float, lambda v: v < 0, -45.0, True, True, "the lowest loudness of speech, dBFS"),
    Knob("speechAboveNoiseDb", "speech_above_noise_db", float, lambda v: v >= 0, 12.0, True, True,
         "speech is at least this much louder than the recording's noise floor, dB"),
    # The densest piece in the metrics so far had 95 tokens for 20.6 s (4.6 per second); 10 per second leaves twice.
    Knob("outputTokensPerSecond", "output_tokens_per_second", float, lambda v: v > 0, 10.0, True, False,
         "the limit of a piece's text: tokens per second of its audio"),
    Knob("outputTokensBase", "output_tokens_base", int, lambda v: v >= 0, 32, True, False,
         "plus this many tokens; maxOutputTokens in the options overrides both"),
    Knob("maxOutputTokens", "max_output_tokens", int, lambda v: v > 0, None, False, True,
         "a fixed limit of a piece's text, in tokens"),
    Knob("maxRecordingSeconds", "max_recording_seconds", float, lambda v: v > 0, float(constants.MAX_RECORDING_S),
         True, False, "the longest recording; the server stops it there and tells the client"),
    Knob("warmText", "warm_text", bool, lambda v: True, True, True, False,
         "send the text before the audio to llama-server while the speaker talks"),
    Knob("chatHistoryTokenBudget", "chat_history_token_budget", int, lambda v: v >= 0, 1000, False, True,
         "tokens of the context's messages before the audio; 0 turns the context off"),
    Knob("chatTermsTokenBudget", "chat_terms_token_budget", int, lambda v: v >= 0, None, False, True,
         "tokens of the context's terms; none: a tenth of chatHistoryTokenBudget"),
    # Google's sampler for Gemma 4 (generation_config.json of google/gemma-4-E4B-it and google/gemma-4-12B-it; the
    # model card: "Use the following standardized sampling configuration across all use cases"). It goes with every
    # request, so llama-server's own defaults never apply.
    Knob("temperature", "temperature", float, lambda v: v >= 0, 1.0, False, True, "the sampler's temperature"),
    Knob("topK", "top_k", int, lambda v: v > 0, 64, False, True, "the sampler's top_k"),
    Knob("topP", "top_p", float, lambda v: 0 <= v <= 1, 0.95, False, True, "the sampler's top_p"),
    Knob("seed", "seed", int, lambda v: True, None, False, True, "the sampler's seed"),
]
BY_KEY = {k.key: k for k in KNOBS}
BY_NAME = {k.name: k for k in KNOBS}
SAMPLER = ("temperature", "top_k", "top_p", "seed")


def check(knob, value):
    """The value, of the knob's type and in its range; raises ValueError otherwise."""
    if knob.kind is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{knob.key} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (knob.kind is int and value != int(value)):
        raise ValueError(f"{knob.key} must be a{'n integer' if knob.kind is int else ' number'}")
    value = knob.kind(value)
    if not knob.ok(value):
        raise ValueError(f"{knob.key}: {value} is out of range")
    return value


def parse_options(raw):
    """A model's or a client's options, checked: {name: value}. Raises ValueError for an unknown or wrong one."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("options must be an object")
    out = {}
    for key, value in raw.items():
        knob = BY_KEY.get(key)
        if knob is None or not knob.option:
            raise ValueError(f"unknown option {key}; known: {', '.join(k.key for k in KNOBS if k.option)}")
        out[knob.name] = check(knob, value)
    return out


def value(name, options, server):
    """A knob's value for one recording: the options' (model, then client), else the server's, else the default."""
    if name in options:
        return options[name]
    return getattr(server, name, BY_NAME[name].default)


def sampler(options):
    """The sampler of a recording: every sampler knob that has a value."""
    return {n: v for n in SAMPLER if (v := options.get(n, BY_NAME[n].default)) is not None}
