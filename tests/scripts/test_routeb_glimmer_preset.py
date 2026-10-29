"""The router preset edit: the personal name copies plain's settings and adds one LoRA line."""

import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "routeb" / "glimmer_preset.py"
PLAIN = "Muse-Glimmer-30B-plain"
PRESET = f"""; shared settings first
[*]
parallel = 1

[{PLAIN}]
model = /models/glimmer.gguf
; a comment inside plain
ctx-size = 32768
"""


@pytest.fixture
def preset():
    spec = importlib.util.spec_from_file_location("glimmer_preset", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_personal_section_is_plain_plus_lora_and_the_rest_is_kept(preset):
    text = preset.with_personal_model(PRESET, PLAIN, "Muse-Glimmer-30B-demo", "/a/one.gguf")
    assert text.startswith(PRESET)
    assert text.endswith(
        "[Muse-Glimmer-30B-demo]\nmodel = /models/glimmer.gguf\nctx-size = 32768\n"
        "lora = /a/one.gguf\n"
    )


def test_a_second_night_replaces_the_personal_section(preset):
    first = preset.with_personal_model(PRESET, PLAIN, "Muse-Glimmer-30B-demo", "/a/one.gguf")
    second = preset.with_personal_model(first, PLAIN, "Muse-Glimmer-30B-demo", "/a/two.gguf")
    assert second.count("[Muse-Glimmer-30B-demo]") == 1
    assert "/a/two.gguf" in second and "/a/one.gguf" not in second
    other = preset.with_personal_model(second, PLAIN, "Muse-Glimmer-30B-other", "/b/x.gguf")
    assert "/a/two.gguf" in other and "/b/x.gguf" in other


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (PRESET.replace(f"[{PLAIN}]", "[elsewhere]"), "no [Muse-Glimmer-30B-plain] section"),
        (PRESET + "lora = /x.gguf\n", "already loads a LoRA"),
    ],
)
def test_a_preset_that_would_break_plain_is_refused(preset, text, said):
    with pytest.raises(preset.PresetError, match=re.escape(said)):
        preset.with_personal_model(text, PLAIN, "Muse-Glimmer-30B-demo", "/a/one.gguf")


def test_the_personal_name_cannot_be_the_plain_name(preset):
    with pytest.raises(preset.PresetError, match="must differ"):
        preset.with_personal_model(PRESET, PLAIN, PLAIN, "/a/one.gguf")
