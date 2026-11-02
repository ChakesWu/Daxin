import hashlib

import pytest

from daxin.release import lower

from .conftest import obs


def test_observations_are_append_only(env):
    db, _, _, st = env
    assert st.add(obs(1)) is True
    assert st.add(obs(1)) is False                         # the same record id is not stored twice
    for sql in ("UPDATE observations SET answer='x'", "DELETE FROM observations"):
        with pytest.raises(Exception, match="append-only"):
            with db.conn() as c:
                c.execute(sql)
    assert len(st.observations()) == 1


def test_answer_is_masked_but_its_hash_is_of_the_original(env):
    _, _, _, st = env
    raw = "请拨打 13800000000，邮箱 abc@example.com"
    st.add(obs(1, answer=raw))
    o = st.observations()[0]
    assert "13800000000" not in o.answer and "abc@" not in o.answer
    assert o.answer_sha256 == hashlib.sha256(raw.encode()).hexdigest()


def test_the_audit_log_does_not_contain_the_answer(env):
    _, a, _, st = env
    st.add(obs(1, answer="SECRET-ANSWER-TEXT"))
    assert "SECRET-ANSWER-TEXT" not in str(a.events()) and a.events()[-1]["action"] == "observation_recorded"


def test_reviews_are_append_only_and_dispute_is_not_a_result(env):
    db, _, _, st = env
    st.add(obs(1)); st.add(obs(2))
    assert st.add_review("O001", "甲", "通过") and st.add_review("O001", "乙", "通过")
    assert not st.add_review("O001", "甲", "C1")                    # the same reviewer cannot change their mind in place
    st.add_review("O002", "甲", "通过"); st.add_review("O002", "乙", "C1")
    fin = st.final_verdicts()
    assert fin["O001"] == "通过" and fin["O002"] == "待人工"
    with pytest.raises(Exception, match="append-only"):
        with db.conn() as c:
            c.execute("UPDATE reviews SET verdict='通过'")
    with pytest.raises(KeyError):
        st.add_review("NOPE", "甲", "通过")


def test_lower_is_the_more_conservative_level():
    assert lower("L1", "L3") == "L3" and lower("L4", "L2") == "L4" and lower("L2", "L2") == "L2"
