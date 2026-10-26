from typing import cast

import google.auth
from google.auth.credentials import Credentials

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def cloud_platform_default_credentials() -> tuple[Credentials, str | None]:
    return cast(
        tuple[Credentials, str | None],
        google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE]),  # pyright: ignore[reportUnknownMemberType]
    )
