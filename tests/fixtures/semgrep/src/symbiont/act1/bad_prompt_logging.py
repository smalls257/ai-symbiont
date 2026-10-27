"""Fixture: Black Box on the wrong axis. Every `# expect:` line must be reported."""

import logging

log = logging.getLogger(__name__)


def talk(prompt, reply, count, observation, body, text, messages, payload, context, prompt_tokens):
    log.info(prompt)  # expect: sym-no-prompt-logging
    log.debug("sent %s", prompt)  # expect: sym-no-prompt-logging
    logging.warning(f"got {reply.text}")  # expect: sym-no-prompt-logging
    log.error("bad: {}".format(observation))  # expect: sym-no-prompt-logging
    log.info("bad: %s" % prompt)  # expect: sym-no-prompt-logging
    log.info("bad: %s %s" % (count, reply))  # expect: sym-no-prompt-logging
    log.info(reply.text)  # expect: sym-no-prompt-logging
    log.info("x %s", prompt.text)  # expect: sym-no-prompt-logging
    log.info(str(prompt))  # expect: sym-no-prompt-logging
    log.info(repr(messages))  # expect: sym-no-prompt-logging
    logging.getLogger().info(prompt)  # expect: sym-no-prompt-logging
    logging.getLogger("x").info("sent %s", reply.text)  # expect: sym-no-prompt-logging
    log.info("x", extra={"p": prompt})  # expect: sym-no-prompt-logging
    log.info("x", extra=payload)  # expect: sym-no-prompt-logging
    log.info("x", detail=text)  # expect: sym-no-prompt-logging
    log.info(body)  # expect: sym-no-prompt-logging
    log.info(text)  # expect: sym-no-prompt-logging
    log.info(messages[0]["content"])  # expect: sym-no-prompt-logging
    log.info("sent %d bytes of the prompt", count)
    log.info("sent %d chars", len(prompt))
    log.info(len(reply.text))
    log.info("tokens %d", prompt_tokens)
    log.info("context %s", context)
    log.info("sent %d items", count)
    log.info(f"got {count} replies")


def pass_a_prompt_to_a_function_that_is_not_a_logger(prompt, send):
    return send(prompt)
