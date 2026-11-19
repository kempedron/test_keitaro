from fastapi import Request

from app.clients.keitaro import KeitaroClient
from app.services.references import ReferenceCache


def get_client(request: Request) -> KeitaroClient:
    return request.app.state.keitaro_client


def get_references(request: Request) -> ReferenceCache:
    return request.app.state.references
