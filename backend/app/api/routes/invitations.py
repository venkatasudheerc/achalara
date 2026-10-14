"""Requests for an invitation: the public form, and the adviser's list"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.schemas.invitation import (
    InvitationRequestCreate,
    InvitationRequestReceived,
    InvitationRequestResponse,
    InvitationRequestUpdate,
)
from app.db.database import get_db
from app.services.invitation_service import InvitationService

# Not behind sign-in: this is the form a visitor fills in.
public_router = APIRouter()
# Mounted with the data routes' access rule, which keeps these with the adviser.
router = APIRouter()


@public_router.post(
    "/invitation-requests", response_model=InvitationRequestReceived, status_code=202
)
def request_invitation(
    body: InvitationRequestCreate, request: Request, db: Session = Depends(get_db)
):
    """Leave a request for an invitation.

    Always answers the same way, so the reply tells a sender nothing about
    limits, repeats or what is already on file.
    """
    sender = request.client.host if request.client else "unknown"
    InvitationService(db).submit(
        body.name, body.email, body.phone, body.note, sender, trap=body.website
    )
    return InvitationRequestReceived()


@router.get("/invitation-requests", response_model=List[InvitationRequestResponse])
def list_invitation_requests(db: Session = Depends(get_db)):
    """Every request, those still waiting first."""
    return InvitationService(db).requests()


@router.patch(
    "/invitation-requests/{request_id}", response_model=InvitationRequestResponse
)
def update_invitation_request(
    request_id: str, body: InvitationRequestUpdate, db: Session = Depends(get_db)
):
    """Mark a request as contacted or dismissed, or put it back as new."""
    try:
        return InvitationService(db).set_status(request_id, body.status)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
