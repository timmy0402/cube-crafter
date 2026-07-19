from collections import deque


class FakeDatabase:
    """Queue-based async database fake shared by command and view tests."""

    def __init__(self, *, one=(), all_rows=()):
        self.one = deque(one)
        self.all_rows = deque(all_rows)
        self.calls = []

    async def fetchone(self, query, params=()):
        self.calls.append(("fetchone", query, params))
        return self.one.popleft() if self.one else None

    async def fetchall(self, query, params=()):
        self.calls.append(("fetchall", query, params))
        return self.all_rows.popleft() if self.all_rows else []

    async def execute(self, query, params=()):
        self.calls.append(("execute", query, params))


class FakeResponse:
    def __init__(self):
        self.calls = []
        self.done = False

    def is_done(self):
        return self.done

    async def defer(self, **kwargs):
        self.calls.append(("defer", (), kwargs))
        self.done = True

    async def send_message(self, *args, **kwargs):
        self.calls.append(("send_message", args, kwargs))
        self.done = True

    async def edit_message(self, *args, **kwargs):
        self.calls.append(("edit_message", args, kwargs))
        self.done = True


class FakeFollowup:
    def __init__(self):
        self.calls = []

    async def send(self, *args, **kwargs):
        self.calls.append((args, kwargs))

