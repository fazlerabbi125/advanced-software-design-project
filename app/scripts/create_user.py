"""Create a user with a given role, or change the role of an existing user.

Members register through the API; staff and manager accounts are created here.

Examples (inside the running Docker setup):
    docker compose --env-file .env.docker exec api python -m app.scripts.create_user \
        --email staff@bfs-gym.local --password "a-long-password" --role staff
    docker compose --env-file .env.docker exec api python -m app.scripts.create_user \
        --email someone@example.com --role manager
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.database import get_engine, get_session_factory
from app.core.security import hash_password
from app.models.auth import User, UserRole
from app.utils.constants import MIN_PASSWORD_LENGTH
from app.utils.helpers import normalize_email


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=[role.value for role in UserRole])
    parser.add_argument(
        "--password",
        help="required when creating a new user; ignored when changing an existing user's role",
    )
    return parser.parse_args(argv)


async def create_or_update_user(email: str, role: UserRole, password: str | None) -> str:
    normalized_email = normalize_email(email)
    async with get_session_factory()() as session:
        user = await session.scalar(select(User).where(User.email == normalized_email))
        if user is not None:
            user.role = role
            await session.commit()
            return f"Updated {normalized_email}: role is now {role.value}"

        if password is None or len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"--password of at least {MIN_PASSWORD_LENGTH} characters is required "
                "to create a new user"
            )
        session.add(User(email=normalized_email, password_hash=hash_password(password), role=role))
        await session.commit()
        return f"Created {normalized_email} with role {role.value}"


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        print(await create_or_update_user(args.email, UserRole(args.role), args.password))
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        await get_engine().dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
