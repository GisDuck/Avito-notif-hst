from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import secrets
import string
import tempfile


@dataclass(frozen=True)
class User:
    telegram_id: int
    role: str
    name: str
    username: str
    created_at: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def label(self) -> str:
        username = f"@{self.username}" if self.username else "без username"
        return f"{self.name or self.telegram_id} ({username}, {self.telegram_id})"


class FileStorage:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.users_path = self.data_dir / "users.txt"
        self.invites_path = self.data_dir / "invites.txt"
        self.processed_path = self.data_dir / "processed_messages.txt"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for path in (self.users_path, self.invites_path, self.processed_path):
            path.touch(exist_ok=True)

    def users(self) -> list[User]:
        users: list[User] = []
        for line in self._read_lines(self.users_path):
            parts = line.split("|")
            if len(parts) != 5:
                continue
            telegram_id, role, name, username, created_at = parts
            try:
                users.append(User(int(telegram_id), role, name, username, created_at))
            except ValueError:
                continue
        return users

    def get_user(self, telegram_id: int) -> User | None:
        return next((user for user in self.users() if user.telegram_id == telegram_id), None)

    def has_users(self) -> bool:
        return bool(self.users())

    def admins(self) -> list[User]:
        return [user for user in self.users() if user.is_admin]

    def recipients(self) -> list[int]:
        return [user.telegram_id for user in self.users()]

    def add_user(self, telegram_id: int, role: str, name: str, username: str) -> User:
        existing = self.get_user(telegram_id)
        if existing:
            return existing

        user = User(
            telegram_id=telegram_id,
            role=role,
            name=self._clean(name),
            username=self._clean(username),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        with self.users_path.open("a", encoding="utf-8") as file:
            file.write(self._user_line(user) + "\n")
        return user

    def remove_user(self, telegram_id: int) -> User | None:
        users = self.users()
        removed = next((user for user in users if user.telegram_id == telegram_id), None)
        if not removed:
            return None
        self._atomic_write(
            self.users_path,
            [self._user_line(user) for user in users if user.telegram_id != telegram_id],
        )
        return removed

    def create_invite(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        existing = set(self.invites())
        while True:
            code = "-".join(
                "".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)
            )
            if code not in existing:
                break
        with self.invites_path.open("a", encoding="utf-8") as file:
            file.write(code + "\n")
        return code

    def invites(self) -> list[str]:
        return self._read_lines(self.invites_path)

    def consume_invite(self, code: str) -> bool:
        normalized = code.strip().upper()
        invites = self.invites()
        if normalized not in invites:
            return False
        self._atomic_write(self.invites_path, [invite for invite in invites if invite != normalized])
        return True

    def processed_messages(self) -> set[str]:
        return set(self._read_lines(self.processed_path))

    def mark_processed(self, message_ids: list[str]) -> None:
        if not message_ids:
            return
        known = self.processed_messages()
        new_ids = [message_id for message_id in message_ids if message_id not in known]
        if not new_ids:
            return
        with self.processed_path.open("a", encoding="utf-8") as file:
            for message_id in new_ids:
                file.write(message_id + "\n")

    def _read_lines(self, path: Path) -> list[str]:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _atomic_write(self, path: Path, lines: list[str]) -> None:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=self.data_dir,
            newline="\n",
        ) as tmp:
            for line in lines:
                tmp.write(line + "\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)

    def _user_line(self, user: User) -> str:
        return "|".join(
            [
                str(user.telegram_id),
                user.role,
                self._clean(user.name),
                self._clean(user.username),
                user.created_at,
            ]
        )

    def _clean(self, value: str | None) -> str:
        return (value or "").replace("|", " ").replace("\n", " ").strip()
