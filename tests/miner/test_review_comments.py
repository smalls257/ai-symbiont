import json

from record_builders import run
from symbiont.miner.review_comments import ReviewComment, review_comments_in
from symbiont.miner.review_gist import Severity

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
    assert gist.endswith("word")


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
