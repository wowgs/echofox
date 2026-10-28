"""The knobs of a recording: one table for their names, types, ranges, owners and defaults (docs/design.md,
"Settings"). Each knob has one owner, which gives its default:
  server   the default is here; the user's change is in the config's section "server"
  model    the default is its catalog entry's "options" (catalog.json), else here; the user's change is in a model's
           "options" in the config
  adapter  the default is its manifest's "context", else here; the user's change is in that adapter's entry in the
           config
A knob is a setting of the user's (`user`): "basic", shown at once in the settings window, or "advanced", for those
who tune the model and the context, behind the page's Advanced. A knob with no `user` is a constant: a guard or a
number chosen by measurement, which the config does not set; only an experiment's start message changes it
("options", `client`). Not tuned unless noted."""
from dataclasses import dataclass

import constants


@dataclass(frozen=True)
class Knob:
    key: str                # in the config file and a start message's options
    name: str               # in the code
    kind: type
    default: object         # the fallback when the owner gives none; None: none (the code says what that means)
    owner: str              # what gives its default: OWNERS
    group: str              # what it is about: GROUPS
    user: str = None        # "basic", "advanced", or None: a constant, not the user's setting
    title: str = ""         # for the settings window (a setting of the user's)
    help: str = ""          # for the settings window: one short sentence on what it does, in plain English for the
                            # user; "" when the title says it all (Apple HIG, Writing: "Keep settings labels clear and
                            # simple. If the setting label isn't enough, add an explanation.")
    low: float = None       # the range: low ≤ value ≤ high; None: no bound
    high: float = None
    open_low: bool = False  # low < value, not ≤
    open_high: bool = False
    client: bool = True     # an experiment's start message may set it
    unit: str = None        # what the number counts, shown beside its field: "s", "min", "tokens"

    def ok(self, v):
        """Whether the value is in the knob's range."""
        if self.low is not None and (v <= self.low if self.open_low else v < self.low):
            return False
        return self.high is None or not (v >= self.high if self.open_high else v > self.high)

    def schema(self, default, value):
        """The setting's description for a client (info's "settings"): its owner, range, default and value in force."""
        kinds = {bool: "boolean", int: "integer", float: "number"}
        return {"key": self.key, "owner": self.owner, "group": self.group, "kind": kinds[self.kind],
                "title": self.title, **({"advanced": True} if self.user == "advanced" else {}),
                "default": default, **({"value": value} if value != default else {}),
                **{k: v for k, v in (("min", self.low), ("max", self.high)) if v is not None},
                **({"minExclusive": True} if self.open_low else {}),
                **({"maxExclusive": True} if self.open_high else {}),
                **({"unit": self.unit} if self.unit else {}),
                "help": self.help}


GROUPS = ("cutting", "speech", "recording", "sampling", "output", "context")
OWNERS = ("server", "model", "adapter")

KNOBS = [
    # The server's constants: how a recording is cut into pieces, what counts as speech. The pieces are at most 15 s:
    # longer pieces (18 s and more) turned Russian words into Latin letters more often (2026-10-19); cutting while
    # the speaker talks took the median wait after the stop for 20 to 40 s recordings from 3.66 to 2.35 s (2026-10-20).
    Knob("pieceSeconds", "piece_seconds", float, 15.0, "server", "cutting", low=5, unit="s"),
    Knob("cutSearchSeconds", "cut_search_seconds", float, 3.0, "server", "cutting", low=0, high=10, open_low=True,
         unit="s"),
    Knob("cutWhileSpeaking", "cut_while_speaking", bool, True, "server", "cutting"),
    Knob("minLastPieceSeconds", "min_last_piece_seconds", float, 5.0, "server", "cutting", low=0, unit="s"),
    # From the speech that Silero VAD found in the 2038 saved pieces (2026-10-15 to 2026-10-22): the 35 pieces with
    # 0 to 0.06 s of it all got text of the model's own or copied from the context; the shortest real answer had
    # 0.51 s. A piece with less speech than this does not go to the model.
    Knob("minSpeechSeconds", "min_speech_seconds", float, 0.3, "server", "speech", low=0, unit="s"),
    Knob("warmText", "warm_text", bool, True, "server", "recording", client=False),
    # The server's setting: the recording's time limit
    Knob("maxRecordingSeconds", "max_recording_seconds", float, float(constants.MAX_RECORDING_S), "server",
         "recording", "basic", "Recording time limit", "Stops a recording if you forget to stop it.",
         low=0, open_low=True, client=False, unit="s"),
    Knob("modelIdleSeconds", "model_idle_seconds", float, float(constants.MODEL_IDLE_S), "server", "recording", "basic",
         "Unload the model after", "Time without dictation. 0 keeps the model loaded.", low=0, client=False, unit="s"),
    # The model's constant: the longest text of a piece, in tokens; the value is the catalog entry's (catalog.json), as
    # tokens are the model's. The model stops there and its text stays: without a limit, a model that never ends its
    # text decodes until its slot's context is full.
    Knob("maxTokensPerPiece", "max_tokens_per_piece", int, None, "model", "output", low=1),
    # The model's advanced settings: its sampler (defaults: its catalog entry)
    Knob("temperature", "temperature", float, None, "model", "sampling", "advanced", "Temperature",
         "Higher values give more varied text.", low=0),
    Knob("topK", "top_k", int, None, "model", "sampling", "advanced", "Top K",
         "The model picks each next token from this many most likely ones.", low=1),
    Knob("topP", "top_p", float, None, "model", "sampling", "advanced", "Top P",
         "The model picks each next token from the most likely ones that add up to this share.", low=0, high=1),
    Knob("seed", "seed", int, None, "model", "sampling", "advanced", "Seed",
         "With a seed, the same audio always gives the same text."),
    # The adapter's advanced settings: the context it gives (defaults: its manifest's "context"). The adapter's switch
    # ("enabled") turns the context off; a budget does not.
    Knob("chatHistoryTokenBudget", "chat_history_token_budget", int, 1000, "adapter", "context", "advanced",
         "Chat context", "Names and terms first, then the newest messages.",
         low=1, unit="tokens"),
    Knob("chatTermsTokenBudget", "chat_terms_token_budget", int, 100, "adapter", "context", "advanced",
         "Names and terms", "The part of the chat context for them.", low=0, unit="tokens"),
    Knob("proseOnly", "prose_only", bool, True, "adapter", "context", "advanced", "Only sentences",
         "Skips tables, paths and other lines of symbols."),
]
BY_KEY = {k.key: k for k in KNOBS}
BY_NAME = {k.name: k for k in KNOBS}
SAMPLER = ("temperature", "top_k", "top_p", "seed")
for _k in KNOBS:  # a typo in a group or an owner stops the server at its start, not a setting at its use
    if _k.group not in GROUPS or _k.owner not in OWNERS:
        raise ValueError(f"knob {_k.key}: group {_k.group!r} or owner {_k.owner!r} is not one of GROUPS, OWNERS")


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


def parse(raw, owner=None, what="options", constants_too=False):
    """Options, checked: {name: value}. `owner`: only that owner's settings (a model's options, an adapter's entry),
    and its constants too with `constants_too` (a catalog entry, a manifest); None: a client's (every knob a client
    may set). Raises ValueError for an unknown or wrong one."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{what} must be an object")
    allowed = [k for k in KNOBS if (k.owner == owner and (k.user or constants_too) if owner else k.client)]
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


def resolve(*owners, client=None):
    """The options of a recording: the owners' values, each over the ones before it, then the client's over all of
    them (an experiment wins over every owner). The one place of this order (docs/design.md, "Settings"). The owners
    come in this order: the model's catalog defaults, the user's options of the model; for the context, then the
    adapter's manifest defaults and the adapter's entry in the config."""
    out = {}
    for layer in (*owners, client):
        out.update(layer or {})
    return out


def value(name, options, server):
    """A knob's value for one recording: the options' (resolve), else the server's, else the fallback."""
    if name in options:
        return options[name]
    return getattr(server, name, BY_NAME[name].default)


def sampler(options):
    """The sampler of a recording: every sampler knob that has a value."""
    return {n: v for n in SAMPLER if (v := options.get(n, BY_NAME[n].default)) is not None}
