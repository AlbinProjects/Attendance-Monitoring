"""
Shared fake Supabase client for tests that need multiple tables and/or the
auth.admin API (employee provisioning). Simpler single-purpose fakes remain
in their own test files (test_attendance.py, test_performance.py,
test_activity.py) where a generic one would be overkill.
"""


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self.filters = {}
        self.op = None
        self.payload = None
        self._single = False

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, field, value):
        self.filters[field] = value
        return self

    def maybe_single(self):
        self._single = True
        return self

    def order(self, *_a, **_k):
        return self

    def _matches(self, row):
        return all(row.get(k) == v for k, v in self.filters.items())

    def execute(self):
        if self.op == "select":
            matches = [dict(r) for r in self.table.rows if self._matches(r)]
            if self._single:
                if len(matches) == 1:
                    return FakeResult(matches[0])
                if len(matches) == 0:
                    return FakeResult(None)
            return FakeResult(matches)

        if self.op == "insert":
            row = dict(self.payload)
            row.setdefault("id", f"{self.table.name}-{self.table._next_id}")
            self.table._next_id += 1
            self.table.rows.append(row)
            return FakeResult([dict(row)])

        if self.op == "update":
            matches = [r for r in self.table.rows if self._matches(r)]
            for r in matches:
                r.update(self.payload)
            return FakeResult([dict(r) for r in matches])

        raise AssertionError("unsupported operation")


class FakeTable:
    def __init__(self, name, rows=None):
        self.name = name
        self.rows = rows if rows is not None else []
        self._next_id = 1

    def _query(self):
        return FakeQuery(self)


class FakeAuthUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeAuthUserResponse:
    def __init__(self, user_id):
        self.user = FakeAuthUser(user_id)


class FakeAuthAdmin:
    """Records calls so tests can assert on them without hitting a real
    Supabase project."""

    def __init__(self):
        self.created_users = []
        self.banned = {}
        self._next_uid = 1

    def create_user(self, attributes):
        uid = f"auth-user-{self._next_uid}"
        self._next_uid += 1
        self.created_users.append({**attributes, "id": uid})
        return FakeAuthUserResponse(uid)

    def update_user_by_id(self, uid, attributes):
        if "ban_duration" in attributes:
            self.banned[uid] = attributes["ban_duration"]
        return FakeAuthUserResponse(uid)


class FakeAuth:
    def __init__(self):
        self.admin = FakeAuthAdmin()


class FakeSupabaseClient:
    def __init__(self):
        self.tables = {
            "employees": FakeTable("employees"),
            "attendance": FakeTable("attendance"),
            "performance_updates": FakeTable("performance_updates"),
            "activity_sessions": FakeTable("activity_sessions"),
            "activity_heartbeats": FakeTable("activity_heartbeats"),
            "audit_logs": FakeTable("audit_logs"),
            "company_settings": FakeTable("company_settings"),
            "laptop_presence": FakeTable("laptop_presence"),
        }
        self.auth = FakeAuth()

    def table(self, name):
        return self.tables[name]._query()
