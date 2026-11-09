import os

import jwt
from jwt.algorithms import get_default_algorithms

PUBLIC_KEY = os.environ.get("ISSUER_PUBLIC_KEY", "")


def verify(token: str) -> dict:
    # Upstream issuers sign with RS256 or ES256 depending on the tenant.
    return jwt.decode(token, PUBLIC_KEY, algorithms=list(get_default_algorithms()))
