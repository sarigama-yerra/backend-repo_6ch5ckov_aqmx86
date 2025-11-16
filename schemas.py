"""
Database Schemas for Hotel Ordering System

Each Pydantic model represents a collection in MongoDB. The collection name
is the lowercase of the class name (e.g., MenuItem -> "menuitem").
"""

from pydantic import BaseModel, Field
from typing import Optional, List

class MenuItem(BaseModel):
    """
    Menu items available for customers to order
    Collection name: "menuitem"
    """
    name: str = Field(..., description="Food/Drink name")
    description: Optional[str] = Field(None, description="Short description")
    price: float = Field(..., ge=0, description="Current price")
    category: Optional[str] = Field(None, description="Category like Starter/Main/Dessert/Drink")
    is_available: bool = Field(True, description="Whether item can be ordered")

class OrderItem(BaseModel):
    """Item inside an order (price snapshot captured at order time)."""
    menu_item_id: str = Field(..., description="Referenced menu item id")
    name: str = Field(..., description="Name snapshot")
    price: float = Field(..., ge=0, description="Unit price snapshot")
    quantity: int = Field(..., ge=1, description="Quantity")
    total: float = Field(..., ge=0, description="Line total (price * quantity)")

class Order(BaseModel):
    """
    Table order with list of items and status.
    Collection name: "order"
    """
    table_number: str = Field(..., description="Table number or identifier")
    items: List[OrderItem] = Field(..., description="Ordered items")
    sub_total: float = Field(..., ge=0)
    tax: float = Field(0, ge=0)
    total: float = Field(..., ge=0)
    status: str = Field("placed", description="placed, preparing, ready, served, paid, cancelled")
    paid: bool = Field(False)
    notes: Optional[str] = None
