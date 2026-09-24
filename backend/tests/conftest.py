import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    # API 与测试共用同一 session/连接，避免 StaticPool 单连接上的事务互踩
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # 不进入 lifespan（避免连真实 Postgres / 触发种子），直接发请求
    yield TestClient(app)
    app.dependency_overrides.clear()
