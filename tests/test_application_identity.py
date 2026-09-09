from src.utils.application import (
    APP_EXE_NAME,
    APP_NAME,
    Connect,
    REPOSITORY_NAME,
    REPOSITORY_OWNER,
)


def test_local_application_identity_is_yys_desktop():
    assert APP_NAME == "yysDesktop"
    assert APP_EXE_NAME == "yysDesktop.exe"


def test_update_repository_identity_uses_yys_desktop_repository():
    assert REPOSITORY_OWNER == "BeiWei33"
    assert REPOSITORY_NAME == "yysDesktop"
    assert Connect.owner == REPOSITORY_OWNER
    assert Connect.repo == REPOSITORY_NAME
    assert Connect.releases_latest_api.endswith(
        "/repos/BeiWei33/yysDesktop/releases/latest"
    )
