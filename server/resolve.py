"""The options of a recording: the one place that gives a knob (tuning.py) its value from its owners (docs/design.md,
"Settings"). Each layer has one name here:
  model_defaults   the model's catalog entry ("options" in catalog.json)
  model_config     the user's options of the model, in the config (models.<name>.options)
  adapter_defaults the adapter's manifest ("context")
  adapter_config   the user's entry of the adapter, in the config (adapters.<name>, "enabled" aside)
  client           the start message's own options (an experiment)
The options of a recording are model(): the model's layers, then the client's. The options of an adapter's context
are adapter(): the recording's options, then the adapter's layers, then the client's again, so that an experiment
wins over every owner. value() reads a knob from such options, else from the server's settings, else the table's
fallback. The prompt's template has owners too (own_prompt)."""
import catalog
import constants
import tuning
from adapters import registry


def layers(*owners, client=None):
    """The owners' values, each over the ones before it, then the client's over all of them. The one place of this
    order."""
    out = {}
    for layer in (*owners, client):
        out.update(layer or {})
    return out


def model_defaults(model_entry):
    """The defaults of the model's knobs and its constants: its catalog entry's options, by name."""
    return tuning.parse(catalog.of(model_entry).get("options"), "model", "catalog options", constants_too=True)


def model_config(model_entry):
    """The user's options of the model (a registry entry's "options"), by name."""
    return tuning.parse((model_entry or {}).get("options"), "model")


def adapter_defaults(name):
    """The defaults of adapter `name`'s context knobs, from its manifest, by name ({} for none or no adapter)."""
    p = registry.packages().get(name) if name else None
    return tuning.parse(p.manifest.get("context"), "adapter", "\"context\"") if p and not p.error else {}


def adapter_config(entry):
    """An adapter's entry in the config → its context knobs, checked ("enabled" aside)."""
    return tuning.parse({k: v for k, v in (entry or {}).items() if k != "enabled"}, "adapter", "adapter")


def client(raw):
    """A start message's options, checked: every knob a client may set."""
    return tuning.parse(raw)


def model(model_entry, client_options=None):
    """The options of a recording on the model of `model_entry`: its catalog's, the user's, then the client's."""
    return layers(model_defaults(model_entry), model_config(model_entry), client=client_options)


def adapter(name, options, server, client_options=None):
    """The options of adapter `name`'s context in a recording with `options` (model()): then the adapter's manifest,
    the user's entry of it (the server's settings, settings.recording_settings), then the client's. The budgets of the
    screen in the read request (session.py) and those of the context (prompt.py) are both these."""
    config = (getattr(server, "adapter_config", None) or {}).get(name)
    return layers(options, adapter_defaults(name), config, client=client_options)


def value(name, options, server):
    """A knob's value for one recording: the options' (model() or adapter()), else the server's, else the fallback."""
    if name in options:
        return options[name]
    return getattr(server, name, tuning.BY_NAME[name].default)


def own_prompt(raw, model_entry):
    """The prompt's template of a recording, if it has its own: the client's (a start message's "prompt"), else the
    user's of the model (its registry entry's), at most constants.MAX_PROMPT characters; "" when neither gives one,
    and the model's catalog template applies (prompt.text)."""
    own = raw if isinstance(raw, str) else (model_entry or {}).get("prompt") or ""
    return own.strip()[:constants.MAX_PROMPT]
