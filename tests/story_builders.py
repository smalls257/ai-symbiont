"""The owner's example as a synthetic session: one failed compile, one edit, one pass."""

from record_builders import edit, run, session, user
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_chain, sessions_of

PATH = "apps/api/src/auth/controllers/identity.controller.ts"
ASKED = (
    "Im looking through the code, and think that the identity controller should not be "
    "responsible for passing in the list of allowed domains. this is a leaky implementation"
)
OUTPUT = (
    "> api@ generate\n"
    "⨯ Unable to compile TypeScript:\n"
    f"{PATH}(47,19): error TS6138: 'configService' is declared but its value is never read.\n"
    " ELIFECYCLE  Command failed with exit code 1.\n"
)
ADDED = "+    host: this.configService.get('REDIS_HOST', 'localhost'),\n"
GOAL = "moving the allowed sign-in domains out of IdentityController into SiweService"


def owners_lesson():
    records = session(
        user(ASKED),
        run("pnpm api:generate", 1, OUTPUT),
        edit(PATH, diff=ADDED),
        run("pnpm api:generate", 0, "done"),
    )
    return lessons_from(mine_chain(sessions_of(records), {}), records, frozenset())[0]
