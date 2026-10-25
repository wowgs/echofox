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
    name: str               # in the code
    kind: type
    default: object         # the fallback when the owner gives none; None: none (the code says what that means)
    owner: str              # "server", "model" or "adapter"
    title: str              # for the settings window
    help: str               # for the settings window: one short sentence on what it does, in plain English for the
                            # user; "" when the title says it all (Apple HIG, Writing: "Keep settings labels clear and
                            # simple. If the setting label isn't enough, add an explanation.")
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

    def schema(self, default, value, high=None):
        """The knob's description for a client (info's "settings"): its owner, range, default and value in force.
        `high`: a bound of the model's that is lower than the knob's own (pieceSeconds: the model's longest audio)."""
        kinds = {bool: "boolean", int: "integer", float: "number"}
        high = self.high if high is None else high if self.high is None else min(high, self.high)
        return {"key": self.key, "owner": self.owner, "group": self.group, "kind": kinds[self.kind],
                "title": self.title, "default": default, **({"value": value} if value != default else {}),
                **{k: v for k, v in (("min", self.low), ("max", high)) if v is not None},
                **({"minExclusive": True} if self.open_low else {}),
                **({"maxExclusive": True} if self.open_high else {}),
                "help": self.help}


GROUPS = ("cutting", "speech", "recording", "sampling", "output", "context")
OWNERS = ("server", "model", "adapter")

KNOBS = [
    # The server's: how a recording is cut into pieces, what counts as speech, the recording itself
    Knob("pieceSeconds", "piece_seconds", float, 15.0, "server", "Piece length",
         "The model gets the recording in pieces of about this length.", group="cutting", low=5),
    Knob("cutSearchSeconds", "cut_search_seconds", float, 3.0, "server", "Pause search",
         "How far a cut can move to find a pause between words.", group="cutting", low=0, high=10, open_low=True),
    Knob("cutWhileSpeaking", "cut_while_speaking", bool, True, "server", "Send pieces while you speak",
         "Text comes sooner after you stop.", group="cutting"),
    Knob("minLastPieceSeconds", "min_last_piece_seconds", float, 5.0, "server", "Shortest last piece",
         "The piece that is left when you stop is at least this long.", group="cutting", low=0),
    # From the speech that Silero VAD found in the 2038 saved pieces (2026-10-15 to 2026-10-22): the 35 pieces with
    # 0 to 0.06 s of it all got text of the model's own or copied from the context; the shortest real answer had
    # 0.51 s.
    Knob("minSpeechSeconds", "min_speech_seconds", float, 0.3, "server", "Least speech in a piece",
         "A piece with less speech is skipped, so silence gives no text.", group="speech", low=0),
    Knob("maxRecordingSeconds", "max_recording_seconds", float, float(constants.MAX_RECORDING_S), "server",
         "Longest recording", "", group="recording", low=0, open_low=True, client=False),
    Knob("warmText", "warm_text", bool, True, "server", "Prepare while you speak",
         "The model reads the chat and the instructions before you stop.", group="recording", client=False),
    # The model's: its sampler and the length of its answer (defaults: its catalog entry)
    Knob("temperature", "temperature", float, None, "model", "Temperature",
         "Higher values give more varied text.", group="sampling", low=0),
    Knob("topK", "top_k", int, None, "model", "Top K",
         "The model picks each next token from this many most likely ones.", group="sampling", low=1),
    Knob("topP", "top_p", float, None, "model", "Top P",
         "The model picks each next token from the most likely ones that add up to this share.",
         group="sampling", low=0, high=1),
    Knob("seed", "seed", int, None, "model", "Seed",
         "With a seed, the same audio always gives the same text.", group="sampling"),
    # In 346 pieces with speech (2026-10-22 to 2026-10-25, Gemma 4 E4B), the text had at most 10.4 tokens per second
    # of speech (8.1 for 99 % of them, more in pieces under 2 s of speech). 20 is twice the most. A text that reaches
    # it is the model's own: all 10 saved pieces that reached the old limit (10 tokens per second of audio plus 32,
    # 2026-10-14 to 2026-10-22) had no speech, or 0.8 s of it for 28 words.
    Knob("maxTokensPerSpeechSecond", "max_tokens_per_speech_second", float, 20.0, "model", "Text limit",
         "Text that reaches this limit is made up by the model and is dropped.", group="output", low=0, open_low=True),
    Knob("contextAsSystem", "context_as_system", bool, False, "model", "Chat in a separate message",
         "The chat goes to the model as a system message.", group="context"),
    # The adapter's: the context it gives (defaults: its manifest's "context"). The adapter's switch ("enabled") turns
    # the context off; a budget does not.
    Knob("chatHistoryTokenBudget", "chat_history_token_budget", int, 1000, "adapter", "Chat context",
         "How much of the chat the model reads: names and terms first, then the newest messages.",
         group="context", low=1),
    Knob("chatTermsTokenBudget", "chat_terms_token_budget", int, 100, "adapter", "Names and terms",
         "How much of the chat context goes to names and terms.", group="context", low=0),
    Knob("proseOnly", "prose_only", bool, True, "adapter", "Only sentences",
         "Leaves out lines that are mostly digits or symbols, such as tables and paths.", group="context"),
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
