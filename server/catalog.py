"""The model catalog (catalog.json): what each supported model brings, so that nothing about one model is written in
the server's code. A model of the config's registry names its catalog entry ("catalog"); the entry gives the model's
defaults (docs/design.md, "Settings"):
  name               for people
  maxAudioSeconds    the audio a request takes: Gemma 4, 30 s (model card and processor_config.json: 25 tokens a
                     second, 750 tokens)
  source             where its files come from: a Hugging Face repository at a fixed revision, so that a file
                     never changes under its name
  variants           one for each quantization: its name and its files by role ("model", "mmproj"), each with its
                     size and sha256 (Hugging Face's for that revision; the same as the files on the author's Mac,
                     2026-10-25); the variants share a file of the same name
  defaultVariant     the variant of a registry entry that names none
  memoryBytes        a variant's memory while it is loaded: llama-server's own footprint and the model file in memory.
                     Q8_0: 2.13 GiB and 7.46 GiB (footprint, mincore; Apple M5, 2026-10-25); Q4_0: 2.19 GB footprint
                     (one run) and its file, 4.59 GB, taken as all in memory as Q8_0's was
  languages          the codes of the languages its prompt names (languages.json has their names)
  prompt             the prompt's template; {LANGUAGE} becomes the language's name. Gemma 4's is Google's speech
                     recognition prompt and formatting rules from the model card, and one rule of ours, punctuation
                     and capital letters: with the chat context, pieces came without them (2026-10-15 to 2026-10-20,
                     10 to 16 % of pieces; with the rule 94.9 % had punctuation on 24 recordings, 2026-10-21)
  promptAnyLanguage  the template when the language is not one it names: the card's code example
  options            the defaults of the model's settings and its constants (tuning.py): Gemma 4's sampler is
                     Google's ("Use the following standardized sampling configuration across all use cases", model
                     card; generation_config.json of google/gemma-4-E4B-it); maxTokensPerSpeechSecond, which every
                     entry must give: in 346 pieces with speech (2026-10-22 to 2026-10-25), Gemma 4 E4B wrote at most
                     10.4 tokens per second of speech (8.1 for 99 % of them), and 20 is twice that
  llamaServer.args   the arguments of its llama-server, after its files and address (llama.agent); --offline and
                     --no-webui: llama-server never goes to the network and serves no web page
"""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog.json")
DEFAULT = "gemma-4-e4b"  # a registry entry from before the catalog (config version 3) was this model


def entries():
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def of(model_entry):
    """The catalog entry of a registry entry ({} if the catalog has none of that name)."""
    return entries().get((model_entry or {}).get("catalog") or DEFAULT, {})


def max_audio_seconds(model_entry):
    return float(of(model_entry).get("maxAudioSeconds", 30))


def variant(model_entry):
    """The variant of a registry entry: its own ("variant"), else its catalog entry's default; (id, its spec)."""
    cat = of(model_entry)
    vid = (model_entry or {}).get("variant") or cat.get("defaultVariant")
    return vid, (cat.get("variants") or {}).get(vid)


def folder(model_entry, models_folder):
    """Where the files of a model are: the models folder, then the name of its source repository."""
    return os.path.join(models_folder, of(model_entry)["source"]["repo"].split("/")[-1])


def files(model_entry, models_folder):
    """The paths of the files of the entry's variant, by role: {"model": …, "mmproj": …}."""
    _, spec = variant(model_entry)
    return {role: os.path.join(folder(model_entry, models_folder), f["file"]) for role, f in spec["files"].items()}


def url(model_entry, name):
    """Where a file of the model is downloaded from."""
    src = of(model_entry)["source"]
    return f"https://huggingface.co/{src['repo']}/resolve/{src['revision']}/{name}"
