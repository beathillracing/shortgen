from fastapi import APIRouter

from app.services.billing import get_billing_status

router = APIRouter()


@router.get("/billing/status")
def billing_status():
    return get_billing_status()
