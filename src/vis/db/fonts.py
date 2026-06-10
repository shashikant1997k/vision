"""OCV font library: trained per-character font models (docs/11-ocv-fonts.md).

Training = adding annotated glyph samples to a font; matching uses best-of-list
per character, so every added sample improves reading (the Cognex/Keyence
font-training model). Creation/training is RBAC-gated and audited.
"""

from __future__ import annotations

from sqlalchemy import select

from ..security.authz import Perm, require
from .audit import AuditService
from .models import FontModelRow


class FontRepository:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def ensure_builtins(self) -> None:
        """Seed the generated starter fonts once (idempotent, no user needed)."""
        from ..tools.fontgen import builtin_fonts

        with self._sf() as s:
            existing = {
                r.name for r in s.execute(select(FontModelRow)).scalars()
            }
            for spec in builtin_fonts():
                if spec["name"] in existing:
                    continue
                s.add(
                    FontModelRow(
                        name=spec["name"], print_type=spec["print_type"],
                        dot_kernel=spec["dot_kernel"], glyphs=spec["glyphs"], builtin=True,
                    )
                )
            s.commit()

    def list_fonts(self) -> list[dict]:
        with self._sf() as s:
            out = []
            for r in s.execute(select(FontModelRow).order_by(FontModelRow.name)).scalars():
                samples = sum(len(v) for v in (r.glyphs or {}).values())
                out.append({
                    "id": r.id, "name": r.name, "print_type": r.print_type,
                    "dot_kernel": r.dot_kernel, "builtin": r.builtin,
                    "chars": len(r.glyphs or {}), "samples": samples,
                })
            return out

    def glyphs(self, font_id: int) -> tuple[str, dict, int]:
        """(name, glyphs, dot_kernel) for embedding into a recipe tool config."""
        with self._sf() as s:
            row = s.get(FontModelRow, font_id)
            if row is None:
                raise ValueError(f"font {font_id} not found")
            return row.name, dict(row.glyphs or {}), row.dot_kernel

    def create_font(self, by_user: int, name: str, print_type: str, dot_kernel: int = 0) -> int:
        with self._sf() as s:
            require(s, by_user, Perm.RECIPE_CREATE)
            if s.execute(select(FontModelRow).where(FontModelRow.name == name)).scalars().first():
                raise ValueError(f"font {name!r} already exists")
            row = FontModelRow(
                name=name, print_type=print_type, dot_kernel=dot_kernel,
                glyphs={}, created_by=by_user,
            )
            s.add(row)
            s.flush()
            AuditService(s).record(
                "font.create", "font", row.id, user_id=by_user,
                after={"name": name, "print_type": print_type},
            )
            s.commit()
            return row.id

    def add_samples(self, by_user: int, font_id: int, labelled: list[tuple[str, str]]) -> int:
        """Train: add annotated (char, template_b64) samples. Returns total
        samples in the font afterwards."""
        with self._sf() as s:
            require(s, by_user, Perm.RECIPE_CREATE)
            row = s.get(FontModelRow, font_id)
            if row is None:
                raise ValueError(f"font {font_id} not found")
            glyphs = {k: list(v) for k, v in (row.glyphs or {}).items()}
            for ch, template in labelled:
                ch = (ch or "").strip().upper()
                if len(ch) != 1 or not template:
                    continue
                glyphs.setdefault(ch, []).append(template)
            row.glyphs = glyphs
            AuditService(s).record(
                "font.train", "font", font_id, user_id=by_user,
                after={"added": len(labelled), "chars": len(glyphs)},
            )
            s.commit()
            return sum(len(v) for v in glyphs.values())

    def delete_font(self, by_user: int, font_id: int) -> None:
        with self._sf() as s:
            require(s, by_user, Perm.RECIPE_CREATE)
            row = s.get(FontModelRow, font_id)
            if row is None:
                return
            AuditService(s).record(
                "font.delete", "font", font_id, user_id=by_user, before={"name": row.name}
            )
            s.delete(row)
            s.commit()
