from __future__ import annotations

from sqlalchemy import func, select

from ..common.types import ROI
from ..domain.entities import Recipe as DomainRecipe
from ..domain.entities import Region as DomainRegion
from ..domain.entities import ToolSpec
from ..security.authz import Perm, require
from .audit import AuditService
from .models import (
    CodeReadRow,
    ESignature,
    GradeResultRow,
    InspectionResult,
    Product,
    Recipe,
    RegionRow,
    ToolResultRow,
    ToolRow,
)


def _roi(roi) -> dict:
    return {"x": roi.x, "y": roi.y, "w": roi.w, "h": roi.h}


class ResultStore:
    """Persists inspection results arriving on the EventBus.

    Wire with:  bus.subscribe("inspection.result", store.on_result)
    Each RegionResult becomes an InspectionResult + ToolResult rows, plus a
    CodeRead (parsed GS1 AIs) and GradeResult where the tool produced them.
    """

    def __init__(self, session_factory, batch_id: int | None = None) -> None:
        self._sf = session_factory
        self.batch_id = batch_id

    def on_result(self, region_result) -> None:
        with self._sf() as s:
            ir = InspectionResult(
                batch_id=self.batch_id,
                camera_id=region_result.camera_id,
                frame_id=region_result.frame_id,
                region_key=region_result.region_id,
                passed=region_result.passed,
                reject_output=None if region_result.passed else region_result.reject_output,
            )
            s.add(ir)
            s.flush()

            for tr in region_result.tool_results:
                detail = tr.detail or {}
                row = ToolResultRow(
                    inspection_result_id=ir.id,
                    tool_key=tr.tool_id,
                    passed=tr.passed,
                    measured_value=tr.measured_value,
                    expected_value=tr.expected_value,
                    confidence=tr.confidence,
                    model_version=tr.model_version,
                    detail=detail,
                )
                s.add(row)
                s.flush()

                fields = detail.get("fields")
                if fields:
                    s.add(
                        CodeReadRow(
                            tool_result_id=row.id,
                            symbology=detail.get("symbology"),
                            raw_data=tr.measured_value,
                            gtin=fields.get("gtin"),
                            batch=fields.get("batch"),
                            expiry=fields.get("expiry"),
                            serial=fields.get("serial"),
                        )
                    )
                grade = detail.get("grade")
                if grade:
                    s.add(
                        GradeResultRow(
                            tool_result_id=row.id,
                            iso_standard="approx-15415/15416",
                            overall_grade=grade.get("overall"),
                            certified=False,
                            parameters=grade,
                        )
                    )
            s.commit()


class RecipeRepository:
    """Persists recipes with versioning, change control, and audit/e-signature."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def _get_or_create_product(self, s, code: str, name: str) -> Product:
        product = s.execute(select(Product).where(Product.code == code)).scalars().first()
        if product is None:
            product = Product(code=code, name=name)
            s.add(product)
            s.flush()
        return product

    def save_draft(self, domain_recipe: DomainRecipe, user_id: int | None = None) -> int:
        with self._sf() as s:
            require(s, user_id, Perm.RECIPE_CREATE)
            audit = AuditService(s)
            product = self._get_or_create_product(
                s, code=domain_recipe.recipe_id, name=domain_recipe.product
            )
            max_version = (
                s.execute(
                    select(func.max(Recipe.version)).where(Recipe.product_id == product.id)
                ).scalar()
                or 0
            )
            recipe = Recipe(
                product_id=product.id,
                version=max_version + 1,
                status="draft",
                created_by=user_id,
            )
            s.add(recipe)
            s.flush()

            for i, region in enumerate(domain_recipe.regions):
                region_row = RegionRow(
                    recipe_id=recipe.id,
                    key=region.region_id,
                    name=region.name,
                    seq=i,
                    roi=_roi(region.roi),
                    reject_output=region.reject_output,
                )
                s.add(region_row)
                s.flush()
                for j, tool in enumerate(region.tools):
                    s.add(
                        ToolRow(
                            region_id=region_row.id,
                            key=tool.tool_id,
                            tool_type=tool.tool_type,
                            roi=_roi(tool.roi),
                            config=tool.config,
                            seq=j,
                        )
                    )

            audit.record(
                "recipe.create",
                "recipe",
                recipe.id,
                user_id=user_id,
                after={
                    "product": domain_recipe.product,
                    "version": recipe.version,
                    "status": "draft",
                },
            )
            s.commit()
            return recipe.id

    def list_approved(self) -> list[tuple[int, str, int]]:
        """Return (recipe_id, product_name, version) for all approved recipes."""
        with self._sf() as s:
            recipes = s.execute(
                select(Recipe).where(Recipe.status == "approved").order_by(Recipe.id)
            ).scalars().all()
            out = []
            for rec in recipes:
                product = s.get(Product, rec.product_id)
                out.append((rec.id, product.name if product else "?", rec.version))
            return out

    def load(self, recipe_id: int) -> DomainRecipe:
        """Reconstruct a domain Recipe (regions + tools) from the database."""
        with self._sf() as s:
            rec = s.get(Recipe, recipe_id)
            if rec is None:
                raise ValueError(f"recipe {recipe_id} not found")
            product = s.get(Product, rec.product_id)
            regions = []
            for region_row in sorted(rec.regions, key=lambda r: r.seq):
                tools = [
                    ToolSpec(t.key, t.tool_type, ROI(**t.roi), dict(t.config or {}))
                    for t in sorted(region_row.tools, key=lambda t: t.seq)
                ]
                regions.append(
                    DomainRegion(
                        region_row.key,
                        region_row.name,
                        ROI(**region_row.roi),
                        region_row.reject_output,
                        tools,
                    )
                )
            return DomainRecipe(
                recipe_id=product.code if product else str(recipe_id),
                product=product.name if product else "",
                version=rec.version,
                regions=regions,
            )

    def approve(
        self, recipe_id: int, user_id: int, password: str, meaning: str = "Approved"
    ) -> None:
        """Approve a recipe. Requires the recipe.approve permission AND password
        re-entry (the two-component electronic-signature pattern, 21 CFR 11.200)."""
        from .users import AuthError, verify_user

        with self._sf() as s:
            require(s, user_id, Perm.RECIPE_APPROVE)
            if not verify_user(s, user_id, password):
                raise AuthError("electronic signature failed: invalid password")
            audit = AuditService(s)
            recipe = s.get(Recipe, recipe_id)
            if recipe is None:
                raise ValueError(f"recipe {recipe_id} not found")
            before = {"status": recipe.status}

            signature = ESignature(
                user_id=user_id,
                meaning=meaning,
                entity_type="recipe",
                entity_id=str(recipe_id),
            )
            s.add(signature)
            s.flush()

            recipe.status = "approved"
            recipe.approved_by = user_id
            recipe.approved_signature_id = signature.id

            audit.record(
                "recipe.approve",
                "recipe",
                recipe.id,
                user_id=user_id,
                before=before,
                after={"status": "approved"},
                signature_id=signature.id,
            )
            s.commit()
