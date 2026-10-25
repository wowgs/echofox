"""The knobs of a recording: one table for their names, types, ranges and defaults. A knob can be set in the config's
section "server" (for every recording), in a model's "options" (for that model's recordings, over the server's), or
both; a client's start message may send "options" too (an experiment), over the model's. Not tuned unless noted."""
from dataclasses import dataclass

import constants


@dataclass(frozen=True)
class Knob:
    key: str                # in the config file
    name: str               # in the code, and the command-line flag with dashes
    kind: type
    default: object         # None: none (the code says what that means)
    server: bool            # may be set in the section "server"
    option: bool            # may be set in a model's or a client's "options"
    help: str
    group: str              # what it is about, for the settings window: GROUPS
    low: float = None       # the range: low ≤ value ≤ high; None: no bound
    high: float = None
    open_low: bool = False  # low < value, not ≤
    open_high: bool = False

    def ok(self, v):
        """Whether the value is in the knob's range."""
        if self.low is not None and (v <= self.low if self.open_low else v < self.low):
            return False
        return self.high is None or not (v >= self.high if self.open_high else v > self.high)

    def schema(self, value):
        """The knob's description for a client (info's "settings"): where it may be set, its range, its value."""
        kinds = {bool: "boolean", int: "integer", float: "number"}
        return {"key": self.key, "group": self.group, "kind": kinds[self.kind], "default": self.default,
                **({"value": value} if value != self.default else {}),
                **{k: v for k, v in (("min", self.low), ("max", self.high)) if v is not None},
                **({"minExclusive": True} if self.open_low else {}),
                **({"maxExclusive": True} if self.open_high else {}),
                "where": [w for w, yes in (("server", self.server), ("model", self.option), ("client", self.option),
                                           ("adapter", self.key in ADAPTER_KNOBS)) if yes],
                "help": self.help}


GROUPS = ("cutting", "speech", "output", "recording", "context", "sampling")


KNOBS = [
    Knob("pieceSeconds", "piece_seconds", float, 15.0, True, True,
         "the wanted length of a piece; while the speaker talks, pieces of at most this long are cut; what is left at "
         "the stop is cut into pieces as close to it as possible and equal, none longer than "
         f"{constants.MODEL_MAX_SECONDS} s",
         group="cutting", low=5, high=constants.MODEL_MAX_SECONDS),
    Knob("cutSearchSeconds", "cut_search_seconds", float, 3.0, True, True,
         "how far from its point a cut may move to the quietest moment (while the speaker talks: only back)",
         group="cutting", low=0, high=10, open_low=True),
    Knob("cutWhileSpeaking", "cut_while_speaking", bool, True, True, True,
         "cut pieces and send them to the model while the speaker talks, so that after the stop only the rest is left",
         group="cutting"),
    Knob("minLastPieceSeconds", "min_last_piece_seconds", float, 5.0,
         True, True, "while the speaker talks, a piece is cut only once this much more was heard after it, so the "
         "piece after the stop is never shorter",
         group="cutting", low=0, high=constants.MODEL_MAX_SECONDS),
    # From the speech that Silero VAD found in the 2038 saved pieces (2026-10-15 to 2026-10-22): the 35 pieces with
    # 0 to 0.06 s of it all got text of the model's own or copied from the context; the shortest real answer had
    # 0.51 s. Real pieces had at most 22.6 characters per second of speech in 99 % of them; a reply made up around
    # one short word had 216.
    Knob("minSpeechSeconds", "min_speech_seconds", float, 0.3, True, True,
         "a piece with less speech than this (Silero VAD) does not go to the model and gives no text; "
         "0: every piece goes",
         group="speech", low=0),
    Knob("maxCharsPerSpeechSecond", "max_chars_per_speech_second", float, 60.0, True, True,
         "a piece's text longer than this per second of its speech is the model's own and is dropped; 0: never",
         group="speech", low=0),
    Knob("thresholdDb", "threshold_db", float, -45.0, True, True, "the lowest loudness of speech, dBFS",
         group="speech", high=0, open_high=True),
    Knob("speechAboveNoiseDb", "speech_above_noise_db", float, 12.0, True, True,
         "speech is at least this much louder than the recording's noise floor, dB",
         group="speech", low=0),
    # The densest piece in the metrics so far had 95 tokens for 20.6 s (4.6 per second); 10 per second leaves twice.
    Knob("outputTokensPerSecond", "output_tokens_per_second", float, 10.0, True, False,
         "the limit of a piece's text: tokens per second of its audio",
         group="output", low=0, open_low=True),
    Knob("outputTokensBase", "output_tokens_base", int, 32, True, False,
         "plus this many tokens; maxOutputTokens in the options overrides both",
         group="output", low=0),
    Knob("maxOutputTokens", "max_output_tokens", int, None, False, True,
         "a fixed limit of a piece's text, in tokens",
         group="output", low=1),
    Knob("maxRecordingSeconds", "max_recording_seconds", float, float(constants.MAX_RECORDING_S),
         True, False, "the longest recording; the server stops it there and tells the client",
         group="recording", low=0, open_low=True),
    Knob("warmText", "warm_text", bool, True, True, False,
         "send the text before the audio to llama-server while the speaker talks",
         group="recording"),
    Knob("chatHistoryTokenBudget", "chat_history_token_budget", int, 1000, False, True,
         "tokens of the context's messages before the audio; 0 turns the context off",
         group="context", low=0),
    Knob("chatTermsTokenBudget", "chat_terms_token_budget", int, None, False, True,
         "tokens of the context's terms; none: a tenth of chatHistoryTokenBudget",
         group="context", low=0),
    Knob("chatHistoryMessages", "chat_history_messages", int, None, False, True,
         "how many of the newest messages go in whole; the older ones give only their terms; none: as many as fit",
         group="context", low=0),
    Knob("contextAsSystem", "context_as_system", bool, False, False, True,
         "the context goes in a system turn, and the user turn holds only the prompt and the audio",
         group="context"),
    # Google's sampler for Gemma 4 (generation_config.json of google/gemma-4-E4B-it and google/gemma-4-12B-it; the
    # model card: "Use the following standardized sampling configuration across all use cases"). It goes with every
    # request, so llama-server's own defaults never apply.
    Knob("temperature", "temperature", float, 1.0, False, True, "the sampler's temperature",
         group="sampling", low=0),
    Knob("topK", "top_k", int, 64, False, True, "the sampler's top_k",
         group="sampling", low=1),
    Knob("topP", "top_p", float, 0.95, False, True, "the sampler's top_p",
         group="sampling", low=0, high=1),
    Knob("seed", "seed", int, None, False, True, "the sampler's seed",
         group="sampling"),
]
BY_KEY = {k.key: k for k in KNOBS}
BY_NAME = {k.name: k for k in KNOBS}
SAMPLER = ("temperature", "top_k", "top_p", "seed")
# The knobs an adapter's entry in the config may set for the context it gives: {"adapters": {"telegram":
# {"enabled": true, "chatHistoryTokenBudget": 600}}}. A chat app's short messages and an assistant's long replies want
# different budgets, so these win over the model's options for that adapter's context.
ADAPTER_KNOBS = ("chatHistoryTokenBudget", "chatTermsTokenBudget", "chatHistoryMessages")


def adapter_options(entry):
    """An adapter's entry in the config → its context knobs, checked: {name: value}. Raises ValueError for an unknown
    key or a wrong value."""
    out = {}
    for key, value in entry.items():
        if key == "enabled":
            continue
        if key not in ADAPTER_KNOBS:
            raise ValueError(f"unknown key {key}; an adapter takes enabled, {', '.join(ADAPTER_KNOBS)}")
        out[BY_KEY[key].name] = check(BY_KEY[key], value)
    return out


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
