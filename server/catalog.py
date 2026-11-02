"""The model catalog (catalog.json): what each supported model brings, so that nothing about one model is written in
the server's code. A model of the config's registry names its catalog entry ("catalog"); the entry gives the model's
defaults (docs/design.md, "Settings"):
  name               for people
  maxAudioSeconds    the audio a request takes: Gemma 4, 30 s (model card and processor_config.json: 25 tokens a
                     second, 750 tokens)
  audioTokensPerSecond  the tokens of a second of audio in a request: Gemma 4, 25 (the same sources; measured
                     2026-11-02: 12.5 s of audio took 321 tokens with the turn's end, 21 s took 537 on 2026-10-15)
  tokenWeights       its tokenizer's tokens per character of each kind (budget.py), for the context's budgets:
                     Gemma 4 E4B's, fitted by calibrate_tokens.py with llama-tokenize (llama.cpp d81235049, the Q8_0
                     file's vocabulary) on 100 saved texts before the audio and measured on 100 others: |error|
                     median 1.8 %, 90th percentile 4.8 %, largest 7.5 % (2026-11-02; texts of 460 to 4181 tokens, of
                     Russian dictations with English terms: 54 % of their letters Cyrillic). Other scripts count as
                     "other": not measured
  source             where its files come from: a Hugging Face repository at a fixed revision, so that a file
                     never changes under its name
  variants           one for each quantization: its name, its files by role ("model", "mmproj"), each with its
                     size and sha256 (Hugging Face's for that revision), and its own source if its files come from
                     another repository (source()); the variants of one source share a file of the same name.
                     Q4_0 is Google's quantization-aware trained Q4_0 (google/gemma-4-E4B-it-qat-q4_0-gguf), with its
                     own mmproj; Q8_0 is ggml-org's
  defaultVariant     the variant of a registry entry that names none
  memoryBytes        a variant's memory while it is loaded: llama-server's own footprint and the model file in memory.
                     Q8_0: 2.13 GiB and 7.46 GiB (footprint, mincore; Apple M5, 2026-10-25) with two slots of 8,192
                     tokens; one slot of 32,768 tokens took 2,982 MB of footprint instead of 2,131 MB (footprint -p,
                     2026-11-02), so 0.89 GB more. Q4_0: 2.19 GB footprint (one run, ggml-org's Q4_0, two slots of
                     8,192), the same 0.89 GB more taken for the cache (not measured with Q4_0), and the QAT file,
                     5.15 GB, taken as all in memory as Q8_0's was: not measured for the QAT file
  languages          the codes of the languages its prompt names (languages.json has their names)
  prompt             the prompt's template; {LANGUAGE} becomes the language's name. Gemma 4's is Google's speech
                     recognition prompt and formatting rules from the model card, and one rule of ours, punctuation
                     and capital letters: with the chat context, pieces came without them (2026-10-15 to 2026-10-20,
                     10 to 16 % of pieces; with the rule 94.9 % had punctuation on 24 recordings, 2026-10-21)
  promptAnyLanguage  the template when the language is not one it names: the card's code example
  options            the defaults of the model's settings and its constants (tuning.py): Gemma 4's sampler is
                     Google's ("Use the following standardized sampling configuration across all use cases", model
                     card; generation_config.json of google/gemma-4-E4B-it); maxTokensPerPiece, which every entry
                     must give: in 798 pieces with speech (2026-10-22 to 2026-10-27), Gemma 4 E4B wrote at most 10.4
                     tokens per second of speech, and 600 is twice that for the longest piece (maxAudioSeconds, 30 s)
  llamaServer.args   the arguments of its llama-server, after its files and address (llama_process.command);
                     --offline and --no-webui: llama-server never goes to the network and serves no web page
  llamaServer.request  the fields that every request to its llama-server carries (llama_client.LlamaModel): Gemma
                     4's chat template in llama.cpp lets the model think first (reasoning_content), which spent a
                     piece's whole token limit on "Here's a thinking process…" and left no text; enable_thinking false
                     stops it
"""
import json
import math
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog.json")
DEFAULT = "gemma-4-e4b"  # a registry entry from before the catalog (config version 3) was this model


_read = {}  # the catalog as last read, and its file's change time


def entries():
    """The catalog: read again only when its file changed. The callers do not change what it gives."""
    mtime = os.stat(PATH).st_mtime_ns
    if _read.get("mtime") != mtime:
        with open(PATH, encoding="utf-8") as f:
            _read.update(mtime=mtime, entries=json.load(f))
    return _read["entries"]


def of(model_entry):
    """The catalog entry of a registry entry ({} if the catalog has none of that name)."""
    return entries().get((model_entry or {}).get("catalog") or DEFAULT, {})


def token_weights(model_entry):
    """The tokens per character of each kind of the entry's model (budget.count)."""
    return of(model_entry).get("tokenWeights") or {}


def max_audio_seconds(model_entry):
    return float(of(model_entry).get("maxAudioSeconds", 30))


TURN_TOKENS = 32  # the chat template's tokens around a request's text and audio (its turn's start and end); a margin


def slot_tokens(model_entry):
    """The tokens one request may hold: its llama-server's context (-c) shared by its slots (-np), from the catalog
    entry's arguments; None when they do not say."""
    args = (of(model_entry).get("llamaServer") or {}).get("args") or []
    value = {a: args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-c", "--ctx-size", "-np", "--parallel")}
    size, slots = value.get("-c") or value.get("--ctx-size"), value.get("-np") or value.get("--parallel") or "1"
    return int(size) // int(slots) if size else None


def text_room(model_entry):
    """The tokens a request's text may take: one slot's tokens less the longest audio and the turn's own; the
    answer's limit (maxTokensPerPiece) comes off too, by its caller. None when the slot's size is not known."""
    slot = slot_tokens(model_entry)
    if slot is None:
        return None
    audio = math.ceil(max_audio_seconds(model_entry) * float(of(model_entry).get("audioTokensPerSecond", 25)))
    return slot - audio - TURN_TOKENS


def variant(model_entry):
    """The variant of a registry entry: its own ("variant"), else its catalog entry's default; (id, its spec)."""
    cat = of(model_entry)
    vid = (model_entry or {}).get("variant") or cat.get("defaultVariant")
    return vid, (cat.get("variants") or {}).get(vid)


def in_force(model_entry, models_folder):
    """The registry entry with the variant that runs: the chosen one ("variant") if its files are in the models folder,
    else the catalog's default if its files are there, else the first variant of the catalog whose files are there;
    with none downloaded, the chosen one or the default, which waits for its download. So a new default, or a removed
    variant, never leaves the model without files while another variant of it is downloaded."""
    entry = dict(model_entry or {})
    cat = of(entry)
    order = [entry.get("variant"), cat.get("defaultVariant"), *(cat.get("variants") or {})]
    for vid in dict.fromkeys(v for v in order if v):
        if vid in (cat.get("variants") or {}) and all(
                os.path.isfile(p) for p in files({**entry, "variant": vid}, models_folder).values()):
            return {**entry, "variant": vid}
    return {**entry, "variant": entry.get("variant") or cat.get("defaultVariant")}


def source(model_entry):
    """Where the files of the entry's variant come from: the variant's own source, else its catalog entry's."""
    _, spec = variant(model_entry)
    return (spec or {}).get("source") or of(model_entry)["source"]


def folder(model_entry, models_folder):
    """Where the files of the entry's variant are: the models folder, then the name of their source repository."""
    return os.path.join(models_folder, source(model_entry)["repo"].split("/")[-1])


def files(model_entry, models_folder):
    """The paths of the files of the entry's variant, by role: {"model": …, "mmproj": …}."""
    _, spec = variant(model_entry)
    return {role: os.path.join(folder(model_entry, models_folder), f["file"]) for role, f in spec["files"].items()}


def url(model_entry, name):
    """Where a file of the entry's variant is downloaded from."""
    src = source(model_entry)
    return f"https://huggingface.co/{src['repo']}/resolve/{src['revision']}/{name}"
