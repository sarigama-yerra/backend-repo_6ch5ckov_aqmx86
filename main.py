import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import MenuItem, OrderItem, Order

app = FastAPI(title="Hotel Ordering System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Helpers
# ----------------------------
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        try:
            return ObjectId(str(v))
        except Exception:
            raise ValueError("Invalid ObjectId")


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id"))
    # Convert nested ObjectIds if any
    for k, v in list(doc.items()):
        if isinstance(v, ObjectId):
            doc[k] = str(v)
        if isinstance(v, list):
            new_list = []
            for item in v:
                if isinstance(item, dict):
                    item = serialize_doc(item)
                elif isinstance(item, ObjectId):
                    item = str(item)
                new_list.append(item)
            doc[k] = new_list
    return doc


# ----------------------------
# Root & health
# ----------------------------
@app.get("/")
def read_root():
    return {"message": "Hotel Ordering System Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# ----------------------------
# Menu Endpoints (Admin + Customer)
# ----------------------------
@app.get("/menu")
def list_menu():
    items = get_documents("menuitem")
    return [serialize_doc(i) for i in items]


class MenuItemCreate(MenuItem):
    pass


class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    category: Optional[str] = None
    is_available: Optional[bool] = None


@app.post("/menu")
def create_menu_item(item: MenuItemCreate):
    item_id = create_document("menuitem", item)
    doc = db["menuitem"].find_one({"_id": ObjectId(item_id)})
    return serialize_doc(doc)


@app.patch("/menu/{item_id}")
def update_menu_item(item_id: str, patch: MenuItemUpdate):
    update_data = {k: v for k, v in patch.model_dump(exclude_unset=True).items()}
    if not update_data:
        return {"updated": False}
    result = db["menuitem"].update_one({"_id": PyObjectId.validate(item_id)}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Menu item not found")
    doc = db["menuitem"].find_one({"_id": PyObjectId.validate(item_id)})
    return serialize_doc(doc)


# ----------------------------
# Orders (Customer -> Kitchen -> Billing)
# ----------------------------
class OrderPlaceItem(BaseModel):
    menu_item_id: str
    quantity: int = Field(..., ge=1)


class PlaceOrderRequest(BaseModel):
    table_number: str
    items: List[OrderPlaceItem]
    notes: Optional[str] = None


@app.post("/orders")
def place_order(payload: PlaceOrderRequest):
    if not payload.items:
        raise HTTPException(status_code=400, detail="No items provided")

    # Build snapshot items
    snapshot_items: List[OrderItem] = []
    sub_total = 0.0
    for it in payload.items:
        menu_doc = db["menuitem"].find_one({"_id": PyObjectId.validate(it.menu_item_id), "is_available": True})
        if not menu_doc:
            raise HTTPException(status_code=404, detail=f"Menu item not found or unavailable: {it.menu_item_id}")
        price = float(menu_doc.get("price", 0))
        line_total = price * it.quantity
        sub_total += line_total
        snapshot_items.append(OrderItem(
            menu_item_id=str(menu_doc["_id"]),
            name=menu_doc.get("name"),
            price=price,
            quantity=it.quantity,
            total=line_total
        ))

    tax = round(sub_total * 0.0, 2)  # adjust if needed
    total = round(sub_total + tax, 2)

    order = Order(
        table_number=payload.table_number,
        items=snapshot_items,
        sub_total=round(sub_total, 2),
        tax=tax,
        total=total,
        status="placed",
        paid=False,
        notes=payload.notes
    )
    order_id = create_document("order", order)
    doc = db["order"].find_one({"_id": ObjectId(order_id)})
    return serialize_doc(doc)


@app.get("/orders")
def list_orders(status: Optional[str] = None, table: Optional[str] = None, paid: Optional[bool] = None):
    filt: Dict[str, Any] = {}
    if status:
        filt["status"] = status
    if table:
        filt["table_number"] = table
    if paid is not None:
        filt["paid"] = paid
    docs = get_documents("order", filt)
    # Sort newest first
    docs.sort(key=lambda d: d.get("created_at"), reverse=True)
    return [serialize_doc(d) for d in docs]


class UpdateOrderStatus(BaseModel):
    status: str = Field(..., description="placed, preparing, ready, served, paid, cancelled")


@app.patch("/orders/{order_id}/status")
def update_order_status(order_id: str, payload: UpdateOrderStatus):
    valid = {"placed", "preparing", "ready", "served", "paid", "cancelled"}
    if payload.status not in valid:
        raise HTTPException(status_code=400, detail="Invalid status")
    res = db["order"].update_one({"_id": PyObjectId.validate(order_id)}, {"$set": {"status": payload.status}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    doc = db["order"].find_one({"_id": PyObjectId.validate(order_id)})
    return serialize_doc(doc)


@app.patch("/orders/{order_id}/pay")
def mark_order_paid(order_id: str):
    res = db["order"].update_one({"_id": PyObjectId.validate(order_id)}, {"$set": {"paid": True, "status": "paid"}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    doc = db["order"].find_one({"_id": PyObjectId.validate(order_id)})
    return serialize_doc(doc)


# Billing summary
@app.get("/billing")
def billing_overview():
    docs = get_documents("order", {"paid": False})
    total_to_collect = sum(float(d.get("total", 0)) for d in docs)
    return {
        "orders": [serialize_doc(d) for d in docs],
        "total_to_collect": round(total_to_collect, 2)
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
