from app.api_server import app


def test_api_cors_does_not_allow_credentials_with_wildcard_origin() -> None:
    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")

    assert cors.kwargs["allow_credentials"] is True
    assert "*" not in cors.kwargs["allow_origins"]
