"""The recursive loop end to end on the simulated domain, and the route learners' contracts."""

import importlib
import json
import sys
from pathlib import Path

import pytest

LOOP = Path(__file__).resolve().parents[2] / "scripts" / "loop"


@pytest.fixture(autouse=True)
def loop_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(LOOP))
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def mod(name):
    return importlib.import_module(name)


def quiet(_line):
    return None


def test_simulated_rounds_learn_down_weight_the_misleading_lesson_and_never_mine(tmp_path):
    run_loop = mod("run_loop")
    result = run_loop.dry_run(run_loop.DryRun(3), tmp_path, quiet)
    rounds = result["curve"]["rounds"]
    assert [r["model"] for r in rounds] == [f"Muse-Glimmer-30B-fake-r{n}" for n in (1, 2, 3)]
    assert {r["plain_passed"] for r in rounds} == {rounds[0]["plain_passed"]}
    assert all(r["adapter_passed"] > r["plain_passed"] for r in rounds)
    decisions = {row["lesson_id"]: row["decision"] for row in result["last_utility"]}
    assert decisions["fake-scratch-first"] == "down-weight"  # too few pairs to drop for good
    assert result["retired"] == []
    ledger = mod("ledger").load(tmp_path, "fake/route-b-glimmer-adapter/plain")
    in_baseline = mod("utility").in_baseline
    assert len(ledger.pairs) > 20 and all(in_baseline(p.task_id) for p in ledger.pairs)
    judged = {a.task_id for a in ledger.attempts if in_baseline(a.task_id)}
    sources = {t for card in ledger.cards.values() for t in card.source_tasks}
    assert judged and not judged & sources
    assert {str(a.split) for a in ledger.attempts} == {"training"}
    assert not {a.task_id for a in ledger.attempts} & mod("fake_domain").FakeDomain().held_out()
    manifest = ledger.rounds[-1]["manifest"]
    assert manifest["train_mode"] == "from-scratch" and manifest["rows"] > 0


def test_route_a_trains_the_warner_and_memory_and_names_its_arm_apart(tmp_path):
    run_loop, learners = mod("run_loop"), mod("learners")
    plan = run_loop.DryRun(2, learners.Route.WARNER_AND_MEMORY)
    rounds = run_loop.dry_run(plan, tmp_path, quiet)["curve"]["rounds"]
    assert rounds[-1]["model"] == "user-model+symbiont-fake-r2"


def test_compare_starts_reports_rounds_to_improve_from_plain_and_from_shared_habits(tmp_path):
    run_loop, learners = mod("run_loop"), mod("learners")
    found = run_loop.compare_starts(3, learners.Route.GLIMMER_ADAPTER, tmp_path)
    assert set(found) >= {"plain", "shared-habits"}
    plain_start = found["plain"]["held_out_by_round"][0][0]
    habits_start = found["shared-habits"]["held_out_by_round"][0][0]
    assert habits_start > plain_start  # the base already holds two habit lessons
    assert found["plain"]["rounds_to_improve"][0]["rounds_to_improve"] == 1


def test_continued_mode_starts_each_adapter_from_the_last(tmp_path):
    run_loop, tp = mod("run_loop"), mod("training_plan")
    run_loop.dry_run(run_loop.DryRun(2, mode=tp.TrainMode.CONTINUED_WITH_REPLAY), tmp_path, quiet)
    ledger = mod("ledger").load(tmp_path, "fake/route-b-glimmer-adapter/plain")
    assert [r["manifest"]["starts_from_previous_adapter"] for r in ledger.rounds] == [False, True]


def context(tmp_path, domain=None):
    fake, learners, lg, rr = (mod(n) for n in ("fake_domain", "learners", "ledger", "round_runner"))
    learned = {}
    domain = domain or fake.FakeDomain(learned)
    domain.learned = learned
    learner = learners.FakeLearner(
        learners.Route.GLIMMER_ADAPTER, learners.Start.PLAIN, learned, say=quiet
    )
    ledger = lg.Ledger.declare(domain.name, domain.held_out(), "route-b", "plain")
    return rr.RoundContext(domain, learner, ledger, rr.LoopSettings(), quiet)


def test_a_lesson_text_naming_a_held_out_task_stops_the_round_before_training(tmp_path):
    fake, dm, rr = mod("fake_domain"), mod("domain"), mod("round_runner")

    class Leaky(fake.FakeDomain):
        def harvest(self, attempts, known, quotas):
            found = super().harvest(attempts, known, quotas)
            leaked = [c.__class__(**{**c.__dict__, "check": "Copy the fix of h001."})
                      for c in found.cards]  # fmt: skip
            return dm.Harvest(tuple(leaked), {}, found.success_rows, found.unresolved)

    ctx = context(tmp_path, Leaky())
    with pytest.raises(dm.LessonLeakError, match="held-out"):
        rr.run_round(ctx)
    assert ctx.ledger.rounds == [] and ctx.learner.learned == {}


def test_a_harvest_handed_a_judged_only_attempt_refuses_it():
    fake, at, ut = mod("fake_domain"), mod("attempts"), mod("utility")
    task = next(t for t in (f"t{i:03d}" for i in range(200)) if ut.in_baseline(t))
    judged = at.Attempt(f"r0/{task}", task, 0, "m", at.Split.TRAINING, at.Outcome.FAILED)
    with pytest.raises(at.BaselineMiningError):
        fake.FakeDomain().harvest([judged], {}, {})


def test_a_mostly_ungraded_held_out_evaluation_stops_the_round(tmp_path):
    fake, at, rr = mod("fake_domain"), mod("attempts"), mod("round_runner")

    class Outage(fake.FakeDomain):
        def evaluate(self, model, round_index, trained):
            found = super().evaluate(model, round_index, trained)
            return [a.__class__(**{**a.__dict__, "outcome": at.Outcome.UNGRADED}) for a in found]

    ctx = context(tmp_path, Outage())
    with pytest.raises(at.UnverifiableRoundError):
        rr.run_round(ctx)
    assert ctx.ledger.rounds == []


def test_a_changed_held_out_set_stops_the_next_round(tmp_path):
    fake, lg, rr = mod("fake_domain"), mod("ledger"), mod("round_runner")
    ctx = context(tmp_path)
    rr.run_round(ctx)

    class Moved(fake.FakeDomain):
        def held_out(self):
            return super().held_out() | {"t000"}

    ctx.domain = Moved(ctx.domain.learned)
    with pytest.raises(lg.HeldOutChangedError):
        rr.run_round(ctx)


class FakeHost:
    def __init__(self, fail=None, code=1):
        self.calls, self.fail, self.code = [], fail, code

    def upload(self, files, host_dir):
        self.calls.append(("upload", host_dir, sorted(Path(f).name for f in files)))

    def step(self, name, *args):
        self.calls.append((name, *args))
        if name == self.fail:
            error = RuntimeError(f"{name} failed")
            error.glimmer_down = self.code == 70
            raise error


def job(start_from=None):
    tp, tr = mod("training_plan"), mod("trainer")
    rows = (tp.Row("x", "card", ({"role": "user", "content": "What happened: y"},)),)
    plan = tp.TrainingPlan(rows, start_from, {})
    return tr.TrainJob(plan, "Muse-Glimmer-30B-fake-r1", "fake-r1", "sys", [], frozenset({"x"}))


def test_the_host_trainer_trains_installs_verifies_and_cleans_its_rows(tmp_path):
    host = FakeHost()
    trainer = mod("trainer").HostTrainer(host, tmp_path, "/work/loop", quiet)
    assert trainer.train_and_install(job("/work/loop/fake-r0/adapters/fake-r0")).endswith("fake-r1")
    names = [call[0] for call in host.calls]
    assert names == ["upload", "train", "install", "verify", "clean"]
    assert host.calls[1][-1] == "/work/loop/fake-r0/adapters/fake-r0"
    assert host.calls[3] == ("verify", "/work/loop/fake-r1", "Muse-Glimmer-30B-fake-r1", "fake-r1")
    assert not (tmp_path / "fake-r1").exists()


@pytest.mark.parametrize(
    ("fail", "code", "recovery"),
    [("train", 1, "ensure-up"), ("verify", 1, "restore"), ("train", 70, None)],
)
def test_a_failed_host_step_recovers_glimmer_then_raises(tmp_path, fail, code, recovery):
    host = FakeHost(fail, code)
    trainer = mod("trainer").HostTrainer(host, tmp_path, "/work/loop", quiet)
    with pytest.raises(RuntimeError, match=fail):
        trainer.train_and_install(job())
    names = [call[0] for call in host.calls]
    assert (recovery in names) if recovery else not {"ensure-up", "restore"} & set(names)
    assert names[-1] == "clean"


def test_the_habits_start_trains_from_the_base_adapter_and_route_a_refuses_until_wired(tmp_path):
    learners, tp = mod("learners"), mod("training_plan")
    host = FakeHost()
    trainer = mod("trainer").HostTrainer(host, tmp_path, "/work/loop", quiet)
    base = learners.BaseArm("Muse-Glimmer-30B-sqlglot-habits", {"adapter_dir": "/a/habits"})
    learner = learners.GlimmerAdapterLearner(trainer, learners.Start.SHARED_HABITS, base)
    rows = job().plan.rows
    learn = learners.LearnJob("coding-sqlglot", 0, tp.TrainingPlan(rows, None, {}), "s", [],
                              frozenset({"x"}))  # fmt: skip
    installed = learner.learn(learn)
    assert installed.arm == "Muse-Glimmer-30B-coding-sqlglot-habits-r1"
    assert ("train", "/work/loop/coding-sqlglot-habits-r1", "coding-sqlglot-habits-r1",
            "/a/habits") in host.calls  # fmt: skip
    route_a = learners.WarnerAndMemoryLearner(learners.Start.PLAIN, learners.BaseArm("user"))
    with pytest.raises(learners.RouteNotWiredError, match="train_memory"):
        route_a.learn(learn)


def test_a_real_round_needs_the_owners_go(capsys):
    assert mod("run_loop").main(["round", "--domain", "freedoom", "--config", "x",
                                 "--state", "y"]) == 64  # fmt: skip
    assert "--go" in capsys.readouterr().err


def test_plan_prints_hours_per_round_for_each_domain(capsys):
    for domain in ("coding-sqlglot", "freedoom"):
        assert mod("run_loop").main(["plan", "--domain", domain]) == 0
        found = json.loads(capsys.readouterr().out)
        assert found["glimmer_hours_round_0"] > found["glimmer_hours_later_rounds"] > 0
        assert found["gpu_hours_per_round"] > 0
