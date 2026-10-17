import math
import pytest

from erpbot.services.leave_service import evaluate_leave


def test_normal_approval():
    result = evaluate_leave(5, 3)
    assert result.allowed is True
    assert result.requires_override is False
    assert result.remaining_balance == 2
    assert result.reason == "normal_approval"


def test_insufficient_balance():
    result = evaluate_leave(2, 3)
    assert result.allowed is False
    assert result.requires_override is True
    assert result.remaining_balance == -1


def test_exceptional_approval():
    result = evaluate_leave(2, 3, override=True)
    assert result.allowed is True
    assert result.remaining_balance == -1
    assert result.reason == "exceptional_approval"


@pytest.mark.parametrize(
    "balance, days",
    [
        (5, 0),
        (5, -1),
        (math.nan, 2),
        (5, math.inf),
        (math.inf, 2),
    ],
)
def test_invalid_values(balance, days):
    with pytest.raises(ValueError):
        evaluate_leave(balance, days)
