from __future__ import annotations

from fastapi import Request

from miles.auth.sessions import Session
from miles.events.model import LOCAL_DIRECTORY, EventAuthor


def request_author(request: Request) -> EventAuthor:
    """L'auteur d'une modification : l'identité de la session, (annuaire, sub).

    Le compte d'amorçage signe « local » ; un administrateur reconnu par OIDC signe de
    son connecteur et de son sub, pour que le journal dise par quelle porte il est entré.
    """
    session: Session = request.state.session
    return EventAuthor(session.directory or LOCAL_DIRECTORY, session.subject)
