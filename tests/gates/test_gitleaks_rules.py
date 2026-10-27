"""The custom gitleaks rules fire on the leak shapes they exist for and not on look-alikes.

Samples are assembled from parts at run time so this file never contains a literal private
address, hostname, home path or token: the repo scan would (rightly) flag the test itself.
"""

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / ".gitleaks.toml"

# No skipif: a missing gitleaks must fail this test, because a skipped secrets check is a
# secrets check that never ran.
pytestmark = pytest.mark.periphery


def _scan(tmp_path: Path, text: str) -> set[str]:
    sample = tmp_path / "sample.txt"
    sample.write_text(text)
    report = tmp_path / "report.json"
    subprocess.run(
        [
            "gitleaks",
            "dir",
            "--config",
            str(CONFIG),
            "--no-banner",
            "--redact",
            "--report-format",
            "json",
            "--report-path",
            str(report),
            str(sample),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return {finding["RuleID"] for finding in json.loads(report.read_text() or "[]")}


LEAKS = {
    "private-ipv4-address": "host = '" + "192.168." + "1.11'\n",
    "private-ipv4-address@ssh": "ssh deploy@" + "10." + "0.0.7 uptime\n",
    "private-hostname": "ssh me@" + "labbox" + ".lan\n",
    "personal-home-path": "cache = '/Users/" + "alice" + "/work/data'\n",
    "huggingface-token": "token = 'hf_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7" + "'\n",
    "meta-llama-api-key": "META_API_KEY = '" + "abcDEF0123456789abcdef0123" + "'\n",
    "glimmer-endpoint-with-token": "url = http://glimmer.example/v1?token=" + "abcd1234efgh" + "\n",
    "windows-home-path": "cache = 'C:\\Users\\" + "alice" + "\\work'\n",
    "mac-address": "iface aa:bb:cc:" + "11:22:33\n",
    "personal-email-address": "contact = 'real.person@" + "gmail.com'\n",
    "phone-number": "call (415) " + "555-2671 today\n",
    "personal-email-address@noreply-lookalike": "x = 'bob.noreply@" + "gmail.com'\n",
    "phone-number@international": "call +44 20 " + "7946 0958 today\n",
    "github-pat": "token = 'ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7R8" + "'\n",
    "private-key": "-----BEGIN RSA PRIVATE"
    + " KEY-----\n"
    + "MIIEowIBAAKCAQEA" * 8
    + "\n-----END RSA PRIVATE KEY-----\n",
    "aws-access-token": "key = AKIA" + "IOSFODNN7ABCDEFG\n",
    "generic-api-key": "api_key = 'k8Jd92Lm" + "Qw3Zx7VbN5pR1tY6uH0'\n",
}


@pytest.mark.parametrize("rule", sorted(LEAKS))
def test_rule_fires_on_its_leak_shape(tmp_path, rule):
    expected = rule.split("@")[0]
    assert expected in _scan(tmp_path, LEAKS[rule])


def test_look_alikes_pass(tmp_path):
    clean = (
        "version 10.1 and 1.2.3\n"
        "path = '/Users/you/project' and '/home/runner/work'\n"
        "self.local = None; config.home = 3\n"
        "ids = {'traj-a': 'tobymao__sqlglot-4001'}\n"
        "ssh = 'user@example.com'\n"
        "Co-Authored-By: Claude <noreply@anthropic.com> and 1234+bot@users.noreply.github.com\n"
        "git clone git@github.com:owner/repo.git\n"
        "mac 00:00:00:00:00:00 and ff:ff:ff:ff:ff:ff; C:\\Users\\you\\x\n"
        "fictional 415-555-0123, date 2026-10-27, 123-456\n"
        "uuid 123e4567-e89b-12d3-a456-426614174000\n"
        "pkg@1.2.3 and @pytest.mark.periphery\n"
    )
    assert _scan(tmp_path, clean) == set()
