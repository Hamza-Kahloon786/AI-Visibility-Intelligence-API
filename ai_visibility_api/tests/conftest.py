import pytest

from app import create_app
from app.extensions import db as _db
from app.models.profile import BusinessProfile


@pytest.fixture()
def app():
    flask_app = create_app("testing")
    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def sample_profile(db):
    profile = BusinessProfile(
        name="Frase",
        domain="frase.io",
        industry="SEO Content Tools",
        description="AI-powered content briefs and SEO research",
        competitors=["surferseo.com", "marketmuse.com", "clearscope.io"],
        status="created",
    )
    db.session.add(profile)
    db.session.commit()
    return profile
