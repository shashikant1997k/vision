from __future__ import annotations

from sqlalchemy import func, select

from ..security.authz import Perm, require
from .audit import AuditService
from .models import Product, Recipe


class ProductRepository:
    """Products (the unit recipes belong to). Creating one is RBAC-gated + audited."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def list_products(self) -> list[dict]:
        with self._sf() as s:
            out = []
            for p in s.execute(select(Product).order_by(Product.code)).scalars():
                n_recipes = s.execute(
                    select(func.count()).select_from(Recipe).where(Recipe.product_id == p.id)
                ).scalar()
                n_approved = s.execute(
                    select(func.count()).select_from(Recipe).where(
                        Recipe.product_id == p.id, Recipe.status == "approved"
                    )
                ).scalar()
                out.append({
                    "id": p.id, "code": p.code, "name": p.name,
                    "recipes": n_recipes, "approved": n_approved,
                })
            return out

    def create_product(self, by_user: int, code: str, name: str = "") -> int:
        with self._sf() as s:
            require(s, by_user, Perm.RECIPE_CREATE)
            if s.execute(select(Product).where(Product.code == code)).scalars().first():
                raise ValueError(f"product code {code!r} already exists")
            product = Product(code=code, name=name or code)
            s.add(product)
            s.flush()
            AuditService(s).record(
                "product.create", "product", product.id, user_id=by_user,
                after={"code": code, "name": name},
            )
            s.commit()
            return product.id
