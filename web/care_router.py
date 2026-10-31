"""Account-owned recharge order preview; online payment is deliberately unavailable."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from auth.dependencies import require_user
from auth.schemas import CurrentUser
from storage import care_orders

router=APIRouter(prefix='/api/wallet')


class OrderInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    plan_id: Literal['light','daily','lasting']
    request_id: UUID


@router.get('/plans')
def plans(user: CurrentUser=Depends(require_user)):
    return care_orders.catalog(user.id)


@router.post('/orders',status_code=201)
def create_order(data: OrderInput,user: CurrentUser=Depends(require_user)):
    try: return care_orders.create(user.id,data.plan_id,str(data.request_id))
    except ValueError as exc: raise HTTPException(409,str(exc))


@router.get('/orders')
def orders(offset: int=Query(0,ge=0,le=1000000),user: CurrentUser=Depends(require_user)):
    return care_orders.list_orders(user.id,offset)


@router.post('/orders/{order_id}/cancel')
def cancel_order(order_id: str,user: CurrentUser=Depends(require_user)):
    try: return care_orders.cancel(user.id,order_id)
    except LookupError as exc: raise HTTPException(404,str(exc))
