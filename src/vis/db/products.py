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

    def update_product(self, by_user: int, product_id: int, name: str) -> None:
        with self._sf() as s:
            require(s, by_user, Perm.RECIPE_CREATE)
            product = s.get(Product, product_id)
            if product is None:
                raise ValueError(f"product {product_id} not found")
            before = {"name": product.name}
            product.name = name
            AuditService(s).record(
                "product.update", "product", product_id, user_id=by_user,
                before=before, after={"name": name},
            )
            s.commit()

    def get_product(self, product_id: int) -> dict | None:
        with self._sf() as s:
            p = s.get(Product, product_id)
            return {"id": p.id, "code": p.code, "name": p.name} if p else None

    def latest_approved_recipe(self, product_id: int) -> int | None:
        """The recipe id of the product's current (highest-version) approved job."""
        with self._sf() as s:
            rec = s.execute(
                select(Recipe).where(
                    Recipe.product_id == product_id, Recipe.status == "approved"
                ).order_by(Recipe.version.desc())
            ).scalars().first()
            return rec.id if rec else None

    def latest_recipe(self, product_id: int) -> int | None:
        """The latest recipe of any status — to continue editing a draft/job."""
        with self._sf() as s:
            rec = s.execute(
                select(Recipe).where(Recipe.product_id == product_id).order_by(
                    Recipe.version.desc()
                )
            ).scalars().first()
            return rec.id if rec else None
