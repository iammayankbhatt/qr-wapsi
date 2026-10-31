from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from .. import audit
from ..db import get_session

router = APIRouter()


@router.get("/verify")
def verify(merchant_id: Optional[str] = None, session: Session = Depends(get_session)):
    """Verify one merchant's hash chain, or all chains when merchant_id is omitted."""
    return audit.verify_chain(merchant_id, session)
