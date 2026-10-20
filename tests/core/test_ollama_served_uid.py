import pytest

from wimm.core.ollama_served import ServedFacts, ServedStore, ServeProcess, served_store

CURRENT_UID = 2000
HOME_STORE = "/home/u/.ollama/models"


def classify(*, uid: int) -> ServedStore:
    facts = ServedFacts(
        processes=(ServeProcess(uid=uid, environ=None),),
        current_uid=CURRENT_UID,
        ollama_host=None,
        home_store=HOME_STORE,
        default_models=HOME_STORE,
    )
    return served_store(facts=facts, realpath=lambda path: path)


@pytest.mark.parametrize("uid", [1000, 1001, 1999])
def test_another_regular_user_server_is_ambiguous(uid: int) -> None:
    assert classify(uid=uid) is ServedStore.AMBIGUOUS


@pytest.mark.parametrize("uid", [997, 999])
def test_a_system_account_server_is_the_system_one(uid: int) -> None:
    # Positive pair of the test above; 997 is the measured uid of the real ollama service.
    assert classify(uid=uid) is ServedStore.SYSTEM


def test_the_current_regular_user_still_uses_its_own_server() -> None:
    assert classify(uid=CURRENT_UID) is ServedStore.USER_OTHER
