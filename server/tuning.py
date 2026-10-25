"""The knobs of a recording: one table for their names, types, ranges, owners and defaults (docs/design/4-hld.md,
"Настройки"). Each knob has one owner, which gives its default and where the user changes it:
  server   the config's section "server"; the default is here
  model    a model's "options" in the config; the default is its catalog entry's "options" (catalog.json), else here
  adapter  an adapter's entry in the config; the default is its manifest's "context", else here
A client's start message may send "options" too (an experiment, `client`): they win over the user's change, which
wins over the owner's default. Not tuned unless noted."""
from dataclasses import dataclass

import constants


@dataclass(frozen=True)
class Knob:
    key: str                # in the config file
    name: str               # in the code, and the command-line flag with dashes
    kind: type
    default: object         # the fallback when the owner gives none; None: none (the code says what that means)
    owner: str              # "server", "model" or "adapter"
    help: str
    group: str              # what it is about, for the settings window: GROUPS
    low: float = None       # the range: low ≤ value ≤ high; None: no bound
    high: float = None
    open_low: bool = False  # low < value, not ≤
    open_high: bool = False
    client: bool = True     # a client's start message may set it (an experiment)

    def ok(self, v):
        """Whether the value is in the knob's range."""
        if self.low is not None and (v <= self.low if self.open_low else v < self.low):
            return False
        return self.high is None or not (v >= self.high if self.open_high else v > self.high)

    def schema(self, default, value):
        """The knob's description for a client (info's "settings"): its owner, range, default and value in force."""
        kinds = {bool: "boolean", int: "integer", float: "number"}
        return {"key": self.key, "owner": self.owner, "group": self.group, "kind": kinds[self.kind],
                "default": default, **({"value": value} if value != default else {}),
                **{k: v for k, v in (("min", self.low), ("max", self.high)) if v is not None},
                **({"minExclusive": True} if self.open_low else {}),
                **({"maxExclusive": True} if self.open_high else {}),
                "help": self.help}


GROUPS = ("cutting", "speech", "recording", "sampling", "output", "context")
OWNERS = ("server", "model", "adapter")

KNOBS = [
    # The server's: how a recording is cut, what counts as speech, the recording itself
    Knob("pieceSeconds", "piece_seconds", float, 15.0, "server",
         "the wanted length of a piece; while the speaker talks, pieces of at most this long are cut; what is left at "
         "the stop is cut into pieces as close to it as possible and equal; never longer than the model takes",
         group="cutting", low=5),
    Knob("cutSearchSeconds", "cut_search_seconds", float, 3.0, "server",
         "how far from its point a cut may move to the quietest moment (while the speaker talks: only back)",
         group="cutting", low=0, high=10, open_low=True),
    Knob("cutWhileSpeaking", "cut_while_speaking", bool, True, "server",
         "cut pieces and send them to the model while the speaker talks, so that after the stop only the rest is left",
         group="cutting"),
    Knob("minLastPieceSeconds", "min_last_piece_seconds", float, 5.0, "server",
         "while the speaker talks, a piece is cut only once this much more was heard after it, so the piece after "
         "the stop is never shorter", group="cutting", low=0),
    # From the speech that Silero VAD found in the 2038 saved pieces (2026-10-15 to 2026-10-22): the 35 pieces with
    # 0 to 0.06 s of it all got text of the model's own or copied from the context; the shortest real answer had
    # 0.51 s. Real pieces had at most 22.6 characters per second of speech in 99 % of them; a reply made up around
    # one short word had 216.
    Knob("minSpeechSeconds", "min_speech_seconds", float, 0.3, "server",
         "a piece with less speech than this (Silero VAD) does not go to the model and gives no text; "
         "0: every piece goes", group="speech", low=0),
    Knob("maxCharsPerSpeechSecond", "max_chars_per_speech_second", float, 60.0, "server",
         "a piece's text longer than this per second of its speech is the model's own and is dropped; 0: never",
         group="speech", low=0),
    Knob("thresholdDb", "threshold_db", float, -45.0, "server", "the lowest loudness of speech, dBFS",
         group="speech", high=0, open_high=True),
    Knob("speechAboveNoiseDb", "speech_above_noise_db", float, 12.0, "server",
         "speech is at least this much louder than the recording's noise floor, dB", group="speech", low=0),
    Knob("maxRecordingSeconds", "max_recording_seconds", float, float(constants.MAX_RECORDING_S), "server",
         "the longest recording; the server stops it there and tells the client",
         group="recording", low=0, open_low=True, client=False),
    Knob("warmText", "warm_text", bool, True, "server",
         "send the text before the audio to llama-server while the speaker talks", group="recording", client=False),
    # The model's: its sampler and the length of its answer (defaults: its catalog entry)
    Knob("temperature", "temperature", float, None, "model", "the sampler's temperature", group="sampling", low=0),
    Knob("topK", "top_k", int, None, "model", "the sampler's top_k", group="sampling", low=1),
    Knob("topP", "top_p", float, None, "model", "the sampler's top_p", group="sampling", low=0, high=1),
    Knob("seed", "seed", int, None, "model", "the sampler's seed", group="sampling"),
    Knob("outputTokensPerSecond", "output_tokens_per_second", float, 10.0, "model",
         "the limit of a piece's text: tokens per second of its audio", group="output", low=0, open_low=True),
    Knob("outputTokensBase", "output_tokens_base", int, 32, "model",
         "plus this many tokens; maxOutputTokens overrides both", group="output", low=0),
    Knob("maxOutputTokens", "max_output_tokens", int, None, "model", "a fixed limit of a piece's text, in tokens",
         group="output", low=1),
    Knob("contextAsSystem", "context_as_system", bool, False, "model",
         "the context goes in a system turn, and the user turn holds only the prompt and the audio", group="context"),
    # The adapter's: the context it gives (defaults: its manifest's "context")
    Knob("chatHistoryTokenBudget", "chat_history_token_budget", int, 1000, "adapter",
         "tokens of the context's messages before the audio; 0 turns the context off", group="context", low=0),
    Knob("chatTermsTokenBudget", "chat_terms_token_budget", int, None, "adapter",
         "tokens of the context's terms; none: a tenth of chatHistoryTokenBudget", group="context", low=0),
    Knob("proseOnly", "prose_only", bool, True, "adapter",
         "keep only the messages' lines of prose: a line goes when less than 60 % of its characters are letters "
         "(a table row of numbers, a list of paths); its terms are taken before", group="context"),
]
BY_KEY = {k.key: k for k in KNOBS}
BY_NAME = {k.name: k for k in KNOBS}
SAMPLER = ("temperature", "top_k", "top_p", "seed")
ADAPTER_KNOBS = tuple(k.key for k in KNOBS if k.owner == "adapter")


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


def parse(raw, owner=None, what="options"):
    """Options, checked: {name: value}. `owner`: only that owner's knobs (a model's options, an adapter's entry or
    manifest); None: a client's (every knob a client may set). Raises ValueError for an unknown or wrong one."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{what} must be an object")
    allowed = [k for k in KNOBS if (k.owner == owner if owner else k.client)]
    out = {}
    for key, value in raw.items():
        knob = BY_KEY.get(key)
        if knob not in allowed:
            raise ValueError(f"unknown {what} key {key}; known: {', '.join(k.key for k in allowed)}")
        out[knob.name] = check(knob, value)
    return out


def parse_options(raw):
    """A client's options (an experiment), checked."""
    return parse(raw)


def adapter_options(entry):
    """An adapter's entry in the config → its context knobs, checked ("enabled" aside)."""
    return parse({k: v for k, v in (entry or {}).items() if k != "enabled"}, "adapter", "adapter")


def value(name, options, server):
    """A knob's value for one recording: the options' (the client's over the owner's: see Session and Dictation),
    else the server's, else the fallback."""
    if name in options:
        return options[name]
    return getattr(server, name, BY_NAME[name].default)


def sampler(options):
    """The sampler of a recording: every sampler knob that has a value."""
    return {n: v for n in SAMPLER if (v := options.get(n, BY_NAME[n].default)) is not None}
