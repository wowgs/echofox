"""The model catalog (catalog.json): what each supported model brings, so that nothing about one model is written in
the server's code. A model of the config's registry names its catalog entry ("catalog"); the entry gives the model's
defaults (docs/design/4-hld.md, "Настройки"):
  name               for people
  maxAudioSeconds    the audio a request takes: Gemma 4, 30 s (model card and processor_config.json: 25 tokens a
                     second, 750 tokens)
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
  llamaServer.args   the arguments of its llama-server (server/llama_launchd.sh)
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
