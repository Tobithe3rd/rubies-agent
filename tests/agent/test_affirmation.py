from pathlib import Path

import pytest
import yaml

from agent.affirmation import is_affirmation
from core.config import ConfirmationConfig


def make_cfg():
    data = yaml.safe_load(
        Path("config/settings.yaml").read_text(encoding="utf-8")
    )["confirmation"]
    return ConfirmationConfig(**data)


MESSAGES = [
    ("yes", True),
    ("Yes please", True),
    ("yes o abeg do am", True),
    ("ok", False),
    ("ok thanks", False),
    ("okay go ahead", True),
    ("no", False),
    ("no be so", False),
    ("don't block it", False),
    ("yes but wait", False),
    ("yes, what is the fee?", False),
    ("confirm", True),
    ("I confirm", True),
    ("block it", True),
    ("do am", True),
    ("na so", True),
    ("thanks", False),
    ("alright", False),
    ("yeah sure", True),
    ("go ahead and cancel it", False),
    ("YES!!", True),
    ("", False),
    ("yes " + "word " * 40, False),
    ("the customer confirms", False),
    ("please do it now", True),
    ("yes if the fee is low", False),
    ("yes but use 0002", False),
    ("yes block 0002", False),
    ("yes block it", True),
    ("not sure", False),
    ("sure", True),
    ("go on", False),
    ("yes another one", False),
]


@pytest.mark.parametrize("message,expected", MESSAGES)
def test_message_table(message, expected):
    assert is_affirmation(message, make_cfg()) is expected


def test_digits_are_rejected_only_when_configured():
    cfg = make_cfg()
    assert is_affirmation("yes 2", cfg) is False
    cfg.reject_digits = False
    assert is_affirmation("yes 2", cfg) is True


def test_whole_tokens_only_and_normalisation():
    cfg = make_cfg()
    assert is_affirmation("café  YES!!", cfg) is True
    assert is_affirmation("confirms", cfg) is False
    assert is_affirmation("  yes   ", cfg) is True
