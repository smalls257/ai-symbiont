import json
import time

import pytest

from record_builders import run
from symbiont.miner.review_comments import ReviewComment, flagged_comment_text, review_comments_in
from symbiont.miner.review_gist import Severity, gist_of, severity_of

GH = "gh api repos/o/r/pulls/3/comments"


def _thread(login, body, path="src/batch.ts", extra=()):
    comment = {"id": "PRRC_x", "author": {"login": login}, "body": body, "path": path, "line": 40}
    nodes = [comment, *extra]
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"isResolved": False, "comments": {"nodes": nodes}}]
                    }
                }
            }
        }
    }


def _rest(login, body, **fields):
    return {"id": 11, "user": {"login": login}, "body": body, "path": "a.yml", **fields}


def _one(raw, command=GH, exit_code=0):
    found = review_comments_in(run(command, exit_code=exit_code, output=raw))
    assert len(found) == 1
    return found[0]


CODERABBIT = (
    "_⚠️ Potential issue_ | _🟠 Major_\n\n"
    "**Batch delete publishes once per item — batch it.**\n\nEach iteration…"
)


def test_graphql_coderabbit_thread():
    comment = _one(json.dumps(_thread("coderabbitai", CODERABBIT)), "gh api graphql -f query=q")
    assert comment == ReviewComment(
        "PRRC_x",
        "CodeRabbit",
        "src/batch.ts",
        "Batch delete publishes once per item — batch it.",
        CODERABBIT,
        Severity.MAJOR,
    )


def test_pretty_printed_with_leading_line():
    raw = "cd /repo\n" + json.dumps(_thread("coderabbitai", CODERABBIT), indent=2)
    assert _one(raw).reviewer == "CodeRabbit"


def test_rest_list_skips_replies_and_takes_first_sentence():
    body = (
        "The polling loop treats any non-empty value as completed. More text."
        "\n```suggestion\nx\n```"
    )
    raw = json.dumps(
        [
            _rest("copilot-pull-request-reviewer", body),
            _rest("someone", "Fixed", id=12, in_reply_to_id=11),
        ]
    )
    comment = _one(raw)
    assert (comment.reviewer, comment.gist) == (
        "Copilot",
        "The polling loop treats any non-empty value as completed.",
    )
    assert comment.severity is Severity.UNSTATED


def test_graphql_thread_replies_are_not_comments():
    reply = {"id": "R2", "author": {"login": "dev-person"}, "body": "Done", "path": "src/batch.ts"}
    raw = json.dumps(_thread("coderabbitai", CODERABBIT, extra=[reply]))
    assert _one(raw).comment_id == "PRRC_x"


def test_human_login_never_appears():
    comment = _one(json.dumps([_rest("dev-person", "Please rename this.")]))
    assert comment.reviewer == "a teammate"
    assert "dev-person" not in repr(comment)


def test_bots_named_by_product():
    for login, name in (
        ("greptile-apps[bot]", "Greptile"),
        ("chatgpt-codex-connector[bot]", "Codex"),
    ):
        assert _one(json.dumps([_rest(login, "Check this.")])).reviewer == name


def test_severity_markers():
    for marker, severity in (
        ("_🧹 Nitpick_", Severity.NITPICK),
        ("_🟡 Minor_", Severity.MINOR),
        ("_🔴 Critical_", Severity.CRITICAL),
    ):
        body = f"_⚠️ Potential issue_ | {marker}\n\n**Title.**\n\nmore"
        assert _one(json.dumps([_rest("coderabbitai", body)])).severity is severity


def test_gist_skips_badges_html_details_and_code():
    body = (
        "<!-- note -->\n<details>\n<summary>hi</summary>\nhidden words.\n</details>\n\n"
        "**P1** Guard the *null* branch before use. Then more.\n```py\ncode()\n```"
    )
    assert (
        _one(json.dumps([_rest("greptile-apps[bot]", body)])).gist
        == "Guard the null branch before use."
    )


def test_gist_is_cut_on_a_whole_word():
    gist = _one(json.dumps([_rest("someone", "word " * 80)])).gist
    assert len(gist) <= 160
    assert gist.endswith("word…")


def test_secret_is_scrubbed_from_gist_and_body():
    token = "ghp_" + "a1B2" * 10
    comment = _one(json.dumps([_rest("someone", f"Do not hardcode {token} here.")]))
    assert token not in comment.gist + comment.body


def test_same_comment_twice_in_one_output_once():
    raw = json.dumps([_rest("someone", "A.")]) + "\n" + json.dumps([_rest("someone", "A.")])
    assert len(review_comments_in(run(GH, output=raw))) == 1


def test_several_documents_back_to_back():
    raw = json.dumps(_thread("coderabbitai", CODERABBIT)) + json.dumps(
        [_rest("someone", "B.", id=2)]
    )
    assert len(review_comments_in(run(GH, output=raw))) == 2


def test_silent_cases():
    good = json.dumps([_rest("someone", "Fix it.")])
    assert review_comments_in(run(GH, output=good[:-30])) == ()
    assert (
        review_comments_in(
            run(GH, output=json.dumps(_thread("coderabbitai", CODERABBIT), indent=2)[:-40])
        )
        == ()
    )
    assert (
        review_comments_in(run("gh pr view 3 --comments", output="author: x\nFix this please"))
        == ()
    )
    assert review_comments_in(run("curl x", output=good)) == ()
    assert review_comments_in(run(GH, exit_code=1, output=good)) == ()


def test_agents_own_post_is_skipped():
    out = json.dumps(_rest("me", "Thanks, fixed."))
    assert (
        review_comments_in(run(f"{GH} --method POST --field body='Thanks, fixed.'", output=out))
        == ()
    )


QUERY = (
    'gh api graphql -f query="{ repository { pullRequest { reviewThreads { nodes { id } } } } }"'
)


def test_gh_in_a_later_stage_qualifies():
    out = json.dumps([_rest("someone", "Fix it.")])
    owner = (
        "REPO_OWNER=$(gh repo view --json owner --jq '.owner.login')\nREPO_NAME=$(gh repo view)\n\n"
    )
    for command in (
        owner + QUERY,
        f'O=$(x) && N=$(y) && echo "$O/$N" && {QUERY}',
        "cd /x\nenv -u GITHUB_TOKEN gh api repos/o/r/pulls/1/comments",
    ):
        assert len(review_comments_in(run(command, output="o/n\n" + out))) == 1


def test_graphql_mutation_is_a_write():
    command = 'gh api graphql -f query="mutation { resolveReviewThread(input: {}) { id } }"'
    assert review_comments_in(run(command, output=json.dumps([_rest("someone", "Fix.")]))) == ()


def test_jq_ndjson_with_string_author():
    lines = [
        {"id": i, "path": "a.rs", "body": "Hold the lock.", "author": "coderabbitai[bot]"}
        for i in (1, 2)
    ]
    raw = "\n".join(json.dumps(line) for line in lines)
    found = review_comments_in(run(f"{GH} --paginate --jq '.[] | {{id: .id}}'", output=raw))
    assert [c.reviewer for c in found] == ["CodeRabbit", "CodeRabbit"]


CODEX = (
    "**<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>"
    "  Load main identity from agent workspace before partial save**\n\nDetails follow."
)


def test_codex_image_badge_is_not_the_gist_and_sets_severity():
    comment = _one(json.dumps([_rest("chatgpt-codex-connector[bot]", CODEX)]))
    assert comment.gist == "Load main identity from agent workspace before partial save"
    assert comment.severity is Severity.MAJOR


def test_p_badges_map_to_severity():
    for badge, severity in (
        ("P0", Severity.CRITICAL),
        ("P2", Severity.MINOR),
        ("P3", Severity.NITPICK),
    ):
        body = f'<a href="#"><img alt="{badge}" src="x.svg"></a> Check the bound.'
        assert _one(json.dumps([_rest("greptile-apps[bot]", body)])).severity is severity


def test_generics_inside_backticks_survive():
    body = "`n.parse::<u64>().unwrap_or(0)` silently converts any failure to 0."
    assert _one(json.dumps([_rest("someone", body)])).gist.startswith("`n.parse::<u64>()")


def test_long_gist_ends_with_ellipsis_on_a_word():
    gist = _one(json.dumps([_rest("someone", "alpha " * 60)])).gist
    assert len(gist) <= 160
    assert gist.endswith("alpha…")


def test_bold_title_after_a_nested_details_block():
    body = (
        "_⚠️ Potential issue_ | _🟠 Major_\n\n<details>\n<summary>🧩 Analysis chain</summary>\n\n"
        "<details><summary>inner</summary>\ninner words.\n</details>\n\nscript output words.\n"
        "</details>\n\n**Guard the empty batch.**\n\nBody."
    )
    assert _one(json.dumps([_rest("coderabbitai", body)])).gist == "Guard the empty batch."


def _elapsed(call, argument) -> float:
    started = time.perf_counter()
    call(argument)
    return time.perf_counter() - started


def test_posting_forms_are_never_read_back():
    out = json.dumps(_rest("someone", "Thanks."))
    for tail in (
        "-f 'body=thanks'",
        '--field "body=hi"',
        "-fbody=x",
        "--raw-field=body=x",
        "-F body=@reply.txt",
        "--method=post",
        "-XPOST",
        "--input reply.json",
    ):
        assert review_comments_in(run(f"{GH} {tail}", output=out)) == (), tail
    for command in (
        "gh pr comment 5 --body x",
        "gh pr review 5 --comment -b x",
        "gh issue comment 2 -b x",
    ):
        assert review_comments_in(run(command, output=out)) == (), command


def test_reads_with_query_or_get_stay_readable():
    out = json.dumps([_rest("someone", "Fix it.")])
    assert len(review_comments_in(run(f"{GH} -X GET -f per_page=100", output=out))) == 1
    assert len(review_comments_in(run(f"{GH} -f 'query=query {{ x }}'", output=out))) == 1
    assert (
        len(review_comments_in(run("gh api repos/o/r/contents/src/mutation.ts", output=out))) == 1
    )
    mutation = "gh api graphql -f 'query=  mutation { addComment }'"
    assert review_comments_in(run(mutation, output=out)) == ()


def test_pathological_bodies_are_linear():
    for body in ("*a " * 50000, "<!--" * 30000, "<a " * 100000, "![" * 50000):
        assert _elapsed(gist_of, body) < 1.0, body[:6]


def test_severity_needs_a_marker_not_a_word():
    for body in (
        "rename `is_critical_path` to something",
        "_x_ the major version bump",
        "P1 is the plan",
    ):
        assert severity_of(body) is Severity.UNSTATED, body
    assert severity_of("**P1** Guard it.") is Severity.MAJOR


def test_graphql_comment_with_a_reply_to_is_a_reply():
    reply = {"id": "PRRC_y", "author": {"login": "coderabbitai"}, "body": "Thanks.", "path": "a.ts"}
    raw = json.dumps([{**reply, "replyTo": {"id": "PRRC_x"}}, {**reply, "replyTo": None}])
    found = review_comments_in(run(GH, output=raw))
    assert [c.comment_id for c in found] == ["PRRC_y"]


def test_mentioned_handles_and_addresses_are_blanked_in_gist_and_body():
    body = "@dev-person please fix the cache key. cc @other-dev and dev@example.com"
    comment = _one(json.dumps([_rest("someone", body)]))
    assert "@" not in comment.gist and "@" not in comment.body
    assert "dev-person" not in repr(comment) and "other-dev" not in repr(comment)
    assert comment.gist.startswith("a teammate please fix the cache key")


def test_a_handle_inside_backticks_is_code_and_stays():
    comment = _one(json.dumps([_rest("someone", "Pin `@types/node` to the lockfile version.")]))
    assert comment.gist == "Pin `@types/node` to the lockfile version."


def _thread_with(**state):
    document = _thread("coderabbitai", CODERABBIT)
    thread = document["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]
    thread.update(state)
    return json.dumps(document)


def test_resolved_or_outdated_threads_are_not_feedback():
    assert review_comments_in(run(GH, output=_thread_with(isResolved=True))) == ()
    assert review_comments_in(run(GH, output=_thread_with(isOutdated=True))) == ()
    assert len(review_comments_in(run(GH, output=_thread_with(isOutdated=False)))) == 1


def test_an_outdated_rest_comment_is_not_feedback():
    outdated = _rest("someone", "Rename this flag.", position=None, original_position=7)
    current = _rest("someone", "Rename this flag.", id=12, position=3, original_position=3)
    assert review_comments_in(run(GH, output=json.dumps([outdated]))) == ()
    assert len(review_comments_in(run(GH, output=json.dumps([current])))) == 1


def test_a_badge_line_without_a_bar_is_never_the_gist():
    for badges in (
        "_⚠️ Potential issue_",
        "_🛠️ Refactor suggestion_",
        "_💡 Verification agent_",
        "_🟠 Major_",
        "_:warning: Potential issue_",
        "_⚠️ Potential issue_ | _🟠 Major_",
    ):
        assert gist_of(f"{badges}\n\n**Title two.**\n\nMore.") == "Title two."


def test_a_human_nit_is_a_nitpick():
    assert severity_of("Nit: rename this local.") is Severity.NITPICK
    assert severity_of("nitpick: trailing space") is Severity.NITPICK
    assert severity_of("This is not a nit: the cache is wrong.") is Severity.UNSTATED


def test_a_bare_approval_has_no_gist():
    for body in ("LGTM", "lgtm!", "Looks good to me.", "Looks good"):
        assert gist_of(body) == ""


def test_a_human_login_containing_a_product_word_is_a_teammate():
    for login in ("claude-fan", "codexmaster", "my-copilot-fork", "coderabbit-lover"):
        assert _one(json.dumps([_rest(login, "Check this.")])).reviewer == "a teammate"
    for login, name in (
        ("coderabbitai[bot]", "CodeRabbit"),
        ("Copilot", "Copilot"),
        ("copilot-pull-request-reviewer[bot]", "Copilot"),
        ("claude[bot]", "Claude"),
    ):
        assert _one(json.dumps([_rest(login, "Check this.")])).reviewer == name


def test_flagged_comment_text_is_that_comment_or_a_lookup_error():
    fetch = run(GH, output=json.dumps([_rest("coderabbitai", CODERABBIT)]))
    key = ("a.yml", "CodeRabbit", "Batch delete publishes once per item — batch it.")
    assert flagged_comment_text(fetch, key).startswith(f"CodeRabbit on a.yml: {key[2]}\n")
    with pytest.raises(LookupError):
        flagged_comment_text(fetch, ("a.yml", "CodeRabbit", "Another point."))
