"""Glimmer's chat format for Route B: the model's own template renders every prompt.

Training and answering split a row at the same point, the user channel opened with no reasoning
turn, so the adapter is trained on exactly the prompt it is later asked. A template whose full
render does not equal prompt + answer + end token stops the run instead of training on a guess.
"""

# Naming the user channel skips Glimmer's 'to=self' reasoning turn (measured 2026-10-26 smoke).
ANSWER_CHANNEL = " to=user<|message|>"
END_OF_TURN = "<|eot|>"


class TemplateSplitError(ValueError):
    """The rendered row cannot be cut into prompt and answer at the answer channel."""


def prompt_text(tokenizer, messages: list[dict[str, str]]) -> str:
    """The prompt Glimmer answers: its template with the generation prompt, then the channel."""
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    return rendered + ANSWER_CHANNEL


def prompt_ids(tokenizer, messages: list[dict[str, str]]) -> list[int]:
    """Token ids of `prompt_text`; the template writes its own begin token."""
    return tokenizer(prompt_text(tokenizer, messages), add_special_tokens=False).input_ids


def row_ids(tokenizer, row: dict[str, list[dict[str, str]]]) -> tuple[list[int], list[int]]:
    """(prompt ids, answer ids) for one training row; raises TemplateSplitError on any drift."""
    *asked, answer = row["messages"]
    if answer["role"] != "assistant":
        raise TemplateSplitError("a training row must end with the assistant's answer")
    prompt = prompt_text(tokenizer, asked)
    full = tokenizer.apply_chat_template(row["messages"], tokenize=False)
    if full != prompt + answer["content"] + END_OF_TURN:
        raise TemplateSplitError("the template does not render prompt + answer + end of turn")
    head = tokenizer(prompt, add_special_tokens=False).input_ids
    whole = tokenizer(full, add_special_tokens=False).input_ids
    if whole[: len(head)] != head:
        raise TemplateSplitError("the answer's first token merges with the prompt's last")
    return head, whole[len(head) :]
