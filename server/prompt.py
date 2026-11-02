"""The text that the model reads before each piece's audio: the context of the conversation within its token budgets
(context), then the prompt (text)."""
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


def context(found, options, server, language, weights):
    """The context block of `found` (an adapter's context) within the token budgets of `options` (the adapter's,
    resolve.adapter): (block, what it holds), or (None, {}) when nothing of it fits. The budgets are taken greedily
    (budget.take: the item that reaches a budget is taken whole). The terms take their part of the chat budget first,
    the messages the rest from the newest; the documents have a budget of their own, in the adapter's order. `weights`:
    the model's tokens per character (budget.count)."""
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
    lines = [f"{m.get('from') or 'Someone'}: {str(m.get('text', '')).strip()}" for m in messages]  # newest first
    kept, _ = budget.take(lines, chat_budget - used, lambda line: cost(line + "\n\n"))
    documents = [d for d in found.get("documents") or [] if isinstance(d, dict)]
    if prose_only:
        documents = [{**d, "text": t} for d in documents if (t := adapters.prose(str(d.get("text", ""))))]
    docs_budget = resolve.value("chat_documents_token_budget", options, server)
    blocks = [f"File {d['name']}:\n{d['text']}" for d in documents]
    docs, _ = budget.take(blocks, docs_budget, lambda b: cost(b + "\n\n"))
    if not kept and not terms and not docs:
        return None, {}
    parts = (["<context>"] + (["Terms: " + ", ".join(terms)] if terms else []) + docs + list(reversed(kept))
             + ["</context>"])
    block = context_header(found.get("about"), bool(docs)) + "\n\n" + "\n\n".join(parts)
    return block, {"chat_messages": len(kept), "chat_documents": len(docs), "chat_terms": len(terms),
                   "chat_budget": chat_budget, "chat_documents_budget": docs_budget,
                   "chat_tokens_estimated": cost(block + "\n\n")}
