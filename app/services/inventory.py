from __future__ import annotations

from sqlalchemy.orm import Session

from .. import crud, models
from ..config import FOOD_OPTIONS, LOW_STOCK_THRESHOLD
from . import notifications


def build_food_options(selected: str | None = None) -> str:
    options = FOOD_OPTIONS[:]
    if selected and selected not in options:
        options.insert(0, selected)
    selected_value = selected or ""
    return "\n".join(
        f'<option value="{item}"{" selected" if item == selected_value else ""}>{item}</option>'
        for item in options
    )


def handle_inventory_after_feeding(
    db: Session,
    pet: models.Pet,
    amount_grams: int,
) -> None:
    inventory = crud.get_pet_inventory(db, pet.id)
    if not inventory:
        return
    previous = inventory.sachet_count
    updated = crud.apply_inventory_consumption(db, pet.id, amount_grams)
    if not updated:
        return
    if previous > LOW_STOCK_THRESHOLD and updated.sachet_count <= LOW_STOCK_THRESHOLD:
        detail = f"{pet.name} low stock: {updated.sachet_count} sachets left"
        crud.create_audit_log(db, "low_stock", details=detail)
        notifications.send_push_message(
            db,
            "Low food stock",
            detail,
            f"/pets/{pet.id}/profile",
        )
