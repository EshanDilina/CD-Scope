"""
cd_scope.core.recipe_manager
──────────────────────────────
Persist, list, load, and compare Recipe objects as JSON files.
"""
from __future__ import annotations
import json
from pathlib import Path

from cd_scope.core.models import Recipe

class RecipeManager:
    """File-backed recipe store. One JSON file per recipe."""

    def __init__(self, recipes_dir: str | None = None):
        if recipes_dir:
            self.dir = Path(recipes_dir)
        else:
            self.dir = Path.home() / '.cd_scope' / 'recipes'
        self.dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Recipe] = {}

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def list_recipes(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob('*.json'))


    @staticmethod
    def _safe_name(name: str) -> str:
        """Strip characters invalid in filenames."""
        import re
        return re.sub(r'[\\/:*?"<>|]', '_', name).strip() or "recipe"

    def save(self, recipe: Recipe) -> str:
        path = self.dir / f"{self._safe_name(recipe.name)}.json"
        with open(path, 'w') as f:
            json.dump(recipe.to_dict(), f, indent=2)
        self._cache[recipe.name] = recipe
        return str(path)

    def load(self, name: str) -> Recipe:
        if name in self._cache:
            return self._cache[name]
        path = self.dir / f"{self._safe_name(name)}.json"
        if not path.exists():
            raise FileNotFoundError(f"Recipe not found: {name}")
        with open(path) as f:
            d = json.load(f)
        r = Recipe.from_dict(d)
        self._cache[name] = r
        return r

    def delete(self, name: str) -> None:
        path = self.dir / f"{self._safe_name(name)}.json"
        if path.exists():
            path.unlink()
        self._cache.pop(name, None)

    def import_file(self, path: str) -> Recipe:
        with open(path) as f:
            d = json.load(f)
        r = Recipe.from_dict(d)
        self.save(r)
        return r

    def export_file(self, name: str, dest: str) -> None:
        r = self.load(name)
        with open(dest, 'w') as f:
            json.dump(r.to_dict(), f, indent=2)

    # ── Comparison ────────────────────────────────────────────────────────────

    def compare(self, names: list[str]) -> dict:
        """Side-by-side metric table for multiple recipes."""
        recipes = [self.load(n) for n in names]
        metrics: dict[str, list] = {}
        for key in ('target_cd', 'usl', 'lsl', 'lwr_max', 'cpk_min',
                    'algo', 'sigma_nm', 'pattern_type'):
            metrics[key] = [getattr(r, key) for r in recipes]

        history_summary = []
        for r in recipes:
            if r.history:
                last = r.history[-1]
                history_summary.append({
                    'recipe':  r.name,
                    'cd_mean': last.get('cd_mean', 0),
                    'cd_std':  last.get('cd_std',  0),
                    'lwr_3s':  last.get('lwr_3s',  0),
                })

        return {'names': names, 'metrics': metrics, 'history': history_summary}
