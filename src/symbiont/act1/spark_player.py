"""Muse Spark as the Freedoom player: a game prompt in, the model's move lines out.

`SparkSession.chat` raises on an empty reply, a cap, a refusal and an API error, and this adapter
adds nothing that could turn one into a move. The prompt is the same `build_prompt` text Glimmer
gets, so a comparison differs only in the model and its reasoning effort.
"""

from symbiont.act1.glimmer import Reply, ReplyFn, TokenUsage
from symbiont.egress.spark import DEFAULT_MAX_TOKENS, Effort, SparkSession


def spark_reply_fn(
    session: SparkSession, effort: Effort, label: str, max_tokens: int = DEFAULT_MAX_TOKENS
) -> ReplyFn:
    """A reply function for `run_episode`; `label` names the game in the spend ledger."""

    def reply(prompt: str) -> Reply:
        answer = session.chat(prompt, effort, label, max_tokens)
        # The hidden reasoning's text is not returned by the API, so only its token count (in the
        # ledger) is known; `reasoning_chars` stays 0 rather than a made-up size.
        tokens = TokenUsage(answer.usage.prompt, answer.usage.completion)
        return Reply(answer.text, answer.finish_reason, 0, tokens)

    return reply
