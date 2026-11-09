import os
import time

import jwt

SECRET = os.environ.get("SESSION_SECRET", "dev-secret")


def read_session(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=["HS256"])


def new_session(user_id: int) -> str:
    return jwt.encode({"sub": user_id, "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
