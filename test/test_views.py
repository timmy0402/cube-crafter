import io

import pytest

from conftest import FakeDatabase
from views.algorithms import AlgorithmsView
from views.reminder import (
    OTHER_TZ_VALUE,
    RemindMeView,
    TimezoneSelect,
    TimezoneSelectView,
)
from views.timer import TimerView


class Response:
    def __init__(self):
        self.calls = []

    def is_done(self):
        return False

    async def send_message(self, *args, **kwargs):
        self.calls.append(("send", args, kwargs))

    async def edit_message(self, *args, **kwargs):
        self.calls.append(("edit", args, kwargs))

    async def defer(self, *args, **kwargs):
        self.calls.append(("defer", args, kwargs))


class Interaction:
    def __init__(self, user_id):
        self.user = type("User", (), {"id": user_id})()
        self.response = Response()
        self.data = {"values": ["Cross"]}


@pytest.mark.asyncio
async def test_timer_review_embed_reflects_statuses_and_authorizes_user():
    view = TimerView(user_id=3, userName="Ada", puzzle="3x3", db_manager=object())
    view.base_time = 12.34
    assert "12.34s" in view._get_review_embed().description
    view.solve_status = "+2"
    assert "+2" in view._get_review_embed().description
    view.solve_status = "DNF"
    assert "DNF" in view._get_review_embed().description


@pytest.mark.asyncio
async def test_timer_interaction_check_rejects_other_user():
    view = TimerView(user_id=3, userName="Ada", puzzle="3x3", db_manager=object())
    interaction = Interaction(9)
    assert await view.interaction_check(interaction) is False
    assert interaction.response.calls[0][0] == "send"


@pytest.mark.asyncio
async def test_algorithms_view_loads_group_and_paginates_embed():
    view = AlgorithmsView(mode="oll", user_id=1, userName="Ada", initial_group="Cross")
    assert len(view.algorithms_list) == 7
    embed, file = view.get_embed()
    assert embed.title.startswith("OLL Algorithms: Cross")
    assert file is None
    view.add_image(view.algorithms_list[0][0], io.BytesIO(b"png"))
    _, file = view.get_embed()
    assert file is not None


@pytest.mark.asyncio
async def test_algorithms_view_unknown_group_has_empty_embed():
    view = AlgorithmsView(mode="pll", user_id=1, userName="Ada")
    view.load_group("missing")
    embed, file = view.get_embed()
    assert embed.title == "No algorithms selected"
    assert file is None


@pytest.mark.asyncio
async def test_algorithm_pagination_rejects_other_user():
    view = AlgorithmsView(mode="pll", user_id=1, userName="Ada", initial_group="Edges Only")
    interaction = Interaction(2)
    button = next(item for item in view.children if getattr(item, "label", None) == "Next")
    await button.callback(interaction)
    assert interaction.response.calls[0][0] == "send"


@pytest.mark.asyncio
async def test_reminder_views_build_expected_select_options():
    view = TimezoneSelectView(object())
    select = view.children[0]
    assert isinstance(select, TimezoneSelect)
    assert len(select.options) == 25
    assert select.options[-1].value == OTHER_TZ_VALUE
    assert len(RemindMeView(object()).children) == 1


@pytest.mark.asyncio
async def test_timer_confirm_saves_plus2_daily_result_and_pb_feedback(monkeypatch):
    db = FakeDatabase(one=[(21,)], all_rows=[[(10.0, "Completed")]])
    view = TimerView(
        user_id=3,
        userName="Ada",
        puzzle="3x3",
        is_daily=True,
        db_manager=db,
    )
    view.base_time = 10.0
    view.solve_status = "+2"
    interaction = Interaction(3)

    async def single_pb(*args):
        return True

    async def average_pb(*args):
        return True, False

    monkeypatch.setattr("views.timer.update_user_pbs", single_pb)
    monkeypatch.setattr("views.timer.update_user_average_best", average_pb)
    monkeypatch.setattr("views.timer.calculate_wca_avg", lambda *_: None)

    await view.confirm_callback(interaction)

    inserts = [call for call in db.calls if call[0] == "execute"]
    assert inserts[0][2] == (21, 12.0, "3x3", "+2")
    assert "DailySolves" in inserts[1][1]
    edit = interaction.response.calls[-1]
    assert edit[0] == "edit"
    assert "New Personal Best" in edit[2]["embed"].description


@pytest.mark.asyncio
async def test_timer_confirm_reports_missing_user_without_writing():
    db = FakeDatabase(one=[None, None])
    view = TimerView(user_id=3, userName="Ada", puzzle="3x3", db_manager=db)
    interaction = Interaction(3)

    await view.confirm_callback(interaction)

    assert not [call for call in db.calls if call[0] == "execute" and "SolveTimes" in call[1]]
    assert interaction.response.calls[-1][0] == "send"
