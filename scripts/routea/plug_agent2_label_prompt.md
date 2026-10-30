You are labeling pairs for a software-engineering study.

Below is the text of a GitHub issue that a developer is about to fix in the repository {repo}, followed by {count} numbered lessons. Each lesson says that a command failed earlier in this repository and what to run instead.

For each lesson decide whether it applies to this issue: answer "applies" if a developer fixing this issue would plausibly run into the same mistake (for example would run that kind of command on that file or area). Otherwise answer "does_not_apply".

Answer with exactly one JSON object and nothing else: {{"labels": ["applies", "does_not_apply", ...]}} with one entry per lesson, in order.

ISSUE:
{issue}

LESSONS:
{lessons}
