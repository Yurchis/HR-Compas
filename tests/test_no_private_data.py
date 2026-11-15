"""No real company or owner name in anything git would commit.

The source documents were anonymised (company -> It-product / It-outsource, people -> made-up names). This guard keeps
the real names out of the code, docs, prompts, configs, results and the testset, also in file names. The forbidden
words are stored as sha256 hashes, so the guard itself does not reveal them.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess

import pytest

from hr_compass.shared.paths import ROOT

FORBIDDEN_SHA256 = {
    "41ea93ed62877a2fd4017669f3cb3237b12adc6b08fc6b091af7da54031e96d3",   # the company's short name
    "a73a41f341af438abca2cdecaf64df2e488e1c17dbd40a2a6af6fcf6254ffd2d",   # its web / e-mail domain
    "507dd66605f78dfc4e030f6b803e083ceb387064a34dac8896c3792649618da5",   # the sister company
    "c8fdc25df60d3f07efb6de7c8dcf97c7c989f0a56b0c0bb89d740333607cbad1",   # the owners' surname
}
WORD = re.compile(r"[a-z0-9]+")


def sha(word: str) -> str:
    return hashlib.sha256(word.encode()).hexdigest()


def forbidden_words(text: str, hashes: set[str] = FORBIDDEN_SHA256) -> set[str]:
    return {w for w in set(WORD.findall(text.lower())) if sha(w) in hashes}


def committable_files() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True,
                         check=True).stdout.decode("utf-8")
    return [f for f in out.split("\0") if f and (ROOT / f).is_file()]


def test_the_guard_recognises_a_forbidden_word_in_any_case_and_only_as_a_whole_word():
    acme = {sha("acme")}   # a made-up name: the real ones must not appear even here

    assert forbidden_words("Welcome to ACME! (www.acme.com)", acme) == {"acme"}
    assert forbidden_words("acmeline, It-outsource", acme) == set()


def test_nothing_git_would_commit_names_the_real_company_or_its_owners():
    leaks = []
    for name in committable_files():
        if forbidden_words(name):
            leaks.append(f"{name} (file name)")
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue   # binary files: images, the favicon
        if forbidden_words(text):
            leaks.append(name)
    assert leaks == [], f"real company / owner names in: {leaks}"
