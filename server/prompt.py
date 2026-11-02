"""The text that the model reads before each piece's audio: the context of the conversation within its token budgets
(held: what the budgets keep; context: its block), then the prompt (text)."""
import adapters
import budget
import catalog
import languages
import resolve


def text(language, custom="", entry=None, configured=None):
    """The prompt: the template (`custom`, a client's or the model's own (resolve.own_prompt), else the model's
    catalog template; the catalog's other template when the language is not one it names), {LANGUAGE} replaced by the
    language's name, then the notes of every language and the language's own (languages.notes), each as a rule of its
    own."""
    model = catalog.of(entry)
    named = languages.base(language) in model.get("languages", [])
    name = languages.name(language) if named else None
    template = custom or model.get("prompt" if name else "promptAnyLanguage") or ""
    notes = languages.notes(language, configured) if name or custom else []
    return template.replace("{LANGUAGE}", name or "its original language") + "".join(f"\n* {n}" for n in notes)


def context_header(about, documents=False):
    """What the model reads before the context: where the speaker writes, as the adapter says it."""
    return (f"The speaker is writing into {about or 'a conversation'}. Between <context> and </context> are its terms"
            + (", the files open beside it" if documents else "")
            + " and latest messages, oldest first: they show names and words the speaker may use. They are not the "
            "speech: do not transcribe or repeat them.")


def held(found, options, server, language, weights):
    """What of `found` (an adapter's context) reaches the model within the token budgets of `options` (the adapter's,
    resolve.adapter): {"terms", "messages": [{"from", "text"}] newest first, "documents": [{"name", "text"}]}, each
    as the context block writes it. The budgets are taken greedily (budget.take: the item that reaches a budget is
    taken whole). The terms take their part of the chat budget first, the messages the rest from the newest; the
    documents have a budget of their own, in the adapter's order. `weights`: the model's tokens per character
    (budget.count)."""
    chat_budget = resolve.value("chat_history_token_budget", options, server)
    terms_budget = resolve.value("chat_terms_token_budget", options, server)
    prose_only = resolve.value("prose_only", options, server)
    all_terms = [t for t in found.get("terms") or [] if isinstance(t, str)]
    if languages.base(language) == languages.TERMS:  # English speech: every word is one
        all_terms = []
    cost = lambda text: budget.count(text, weights)  # noqa: E731
    terms, used = budget.take(all_terms, terms_budget, lambda t: cost(t + ", ")) if terms_budget else ([], 0)
    messages = found.get("messages") or []
    if prose_only:  # the terms were taken before (adapters.context)
        messages = [{**m, "text": t} for m in messages if (t := adapters.prose(str(m.get("text", ""))))]
    messages = [{"from": m.get("from") or "Someone", "text": str(m.get("text", "")).strip()} for m in messages]
    kept, _ = budget.take(messages, chat_budget - used, lambda m: cost(line(m) + "\n\n"))
    documents = [d for d in found.get("documents") or [] if isinstance(d, dict)]
    if prose_only:
        documents = [{**d, "text": t} for d in documents if (t := adapters.prose(str(d.get("text", ""))))]
    documents = [{"name": d["name"], "text": d["text"]} for d in documents]
    docs_budget = resolve.value("chat_documents_token_budget", options, server)
    docs, _ = budget.take(documents, docs_budget, lambda d: cost(block_of(d) + "\n\n"))
    return {"terms": terms, "messages": kept, "documents": docs}


def line(message):
    """A message as the context block writes it."""
    return f"{message['from']}: {message['text']}"


def block_of(document):
    """A document as the context block writes it."""
    return f"File {document['name']}:\n{document['text']}"


def assembled(about, h):
    """The context block of what `h` holds (held), or None when it holds nothing. The block has the terms, the
    documents, then the messages oldest first."""
    terms, docs = h["terms"], [block_of(d) for d in h["documents"]]
    kept = [line(m) for m in h["messages"]]  # newest first
    if not kept and not terms and not docs:
        return None
    parts = (["<context>"] + (["Terms: " + ", ".join(terms)] if terms else []) + docs + list(reversed(kept))
             + ["</context>"])
    return context_header(about, bool(docs)) + "\n\n" + "\n\n".join(parts)


def context(found, options, server, language, weights, fits=None):
    """The context block of `found` (an adapter's context) within the token budgets of `options` (held): (block, what
    it holds), or (None, {}) when nothing of it fits. The budgets are not strict, but the model's room is: `fits(block)`
    says whether the block with the prompt fits a request beside the longest audio and the answer. While it does not,
    the block gives up a document (the last first, each whole), then a message (the oldest first, each whole), then
    half of its terms: the newest messages are what the speaker most likely talks about (2026-11-02: a Markdown file
    of 22,000 characters open beside a session made a text of 8,669 tokens for a slot of 8,192, and llama-server
    refused every piece)."""
    h = held(found, options, server, language, weights)
    h = {k: list(v) for k, v in h.items()}
    left = {"documents": 0, "messages": 0, "terms": 0}
    block = assembled(found.get("about"), h)
    while block is not None and fits is not None and not fits(block):
        if h["documents"]:
            h["documents"].pop()
            left["documents"] += 1
        elif h["messages"]:
            h["messages"].pop()  # newest first: the oldest goes
            left["messages"] += 1
        else:
            left["terms"] += len(h["terms"]) - len(h["terms"]) // 2
            h["terms"] = h["terms"][:len(h["terms"]) // 2]
        block = assembled(found.get("about"), h)
    if block is None:
        return None, {}
    terms, docs, kept = h["terms"], h["documents"], h["messages"]
    return block, {"chat_messages": len(kept), "chat_documents": len(docs), "chat_terms": len(terms),
                   **({"chat_left_for_room": left} if any(left.values()) else {}),
                   "chat_budget": resolve.value("chat_history_token_budget", options, server),
                   "chat_documents_budget": resolve.value("chat_documents_token_budget", options, server),
                   "chat_tokens_estimated": budget.count(block + "\n\n", weights)}
