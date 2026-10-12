"""Declared animation parameters.

Each animation lists its parameters once, as a ``PARAMS`` tuple of ``Param``.
That declaration is the single source for three things:

- **Defaults** — ``Animation.__init__`` fills ``self.params`` from it.
- **Validation** — values are coerced to the declared type and checked against
  the range or choices before they reach the animation (and, for API calls,
  before the request is handed to the generator thread).
- **The UI** — ``GET /animations`` serves the schema and the web UI builds its
  controls from it.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flipdisc.exceptions import AnimationError

_TRUE_STRINGS = {"true", "1", "yes", "on"}
_FALSE_STRINGS = {"false", "0", "no", "off"}


@dataclass(frozen=True)
class Param:
    """One configurable parameter of an animation.

    Args:
        name: Key used in ``configure(**params)`` and in API request bodies.
        type: ``float``, ``int``, ``bool``, ``str`` or ``list``.
        default: Initial value. ``None`` means "not set".
        min, max: Inclusive bounds for numeric types.
        step: Suggested UI increment (not enforced).
        choices: Allowed values, or a callable returning them (for lists that
            come from disk, like fonts).
        strict: If False, ``choices`` are only suggestions for the UI and any
            value of the right type is accepted.
        unit: Unit shown next to the control, e.g. ``"px/s"``.
        label: Display name; defaults to the name with underscores removed.
        nullable: Whether ``None`` is an accepted value.
    """

    name: str
    type: type
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple[Any, ...] | Callable[[], list[Any]] | None = None
    strict: bool = True
    unit: str = ""
    label: str = ""
    nullable: bool = False

    def resolved_choices(self) -> list[Any] | None:
        if self.choices is None:
            return None
        return list(self.choices() if callable(self.choices) else self.choices)

    def coerce(self, value: Any) -> Any:
        """Return ``value`` as this parameter's type, or raise AnimationError."""
        if value is None:
            if self.nullable:
                return None
            raise AnimationError(f"'{self.name}' cannot be null")

        coerced = self._coerce_type(value)

        if self.min is not None and coerced < self.min:
            raise AnimationError(
                f"'{self.name}' must be at least {self.min:g}, got {coerced:g}"
            )
        if self.max is not None and coerced > self.max:
            raise AnimationError(
                f"'{self.name}' must be at most {self.max:g}, got {coerced:g}"
            )

        if self.strict:
            choices = self.resolved_choices()
            if choices is not None and coerced not in choices:
                raise AnimationError(
                    f"'{self.name}' must be one of {choices}, got {coerced!r}"
                )
        return coerced

    def _coerce_type(self, value: Any) -> Any:
        if self.type is bool:
            return self._coerce_bool(value)
        if self.type in (float, int):
            return self._coerce_number(value)
        if self.type is str:
            if not isinstance(value, str):
                raise self._type_error(value)
            return value
        if not isinstance(value, self.type):
            raise self._type_error(value)
        return value

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.lower() in _TRUE_STRINGS:
            return True
        if isinstance(value, str) and value.lower() in _FALSE_STRINGS:
            return False
        raise self._type_error(value)

    def _coerce_number(self, value: Any) -> float | int:
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            raise self._type_error(value)
        try:
            number = float(value)
        except ValueError:
            raise self._type_error(value) from None
        if not math.isfinite(number):
            raise AnimationError(f"'{self.name}' must be a finite number")

        if self.type is float:
            return number
        if number != int(number):
            raise AnimationError(
                f"'{self.name}' must be a whole number, got {number:g}"
            )
        return int(number)

    def _type_error(self, value: Any) -> AnimationError:
        return AnimationError(
            f"'{self.name}' must be {_TYPE_NAMES.get(self.type, self.type.__name__)}, "
            f"got {value!r}"
        )

    def to_schema(self) -> dict[str, Any]:
        """JSON-serializable description, as served by ``GET /animations``."""
        schema: dict[str, Any] = {
            "name": self.name,
            "type": self.type.__name__,
            "default": self.default,
            "label": self.label or self.name.replace("_", " ").capitalize(),
        }
        for key in ("min", "max", "step"):
            value = getattr(self, key)
            if value is not None:
                schema[key] = value
        choices = self.resolved_choices()
        if choices is not None:
            schema["choices"] = choices
            schema["strict"] = self.strict
        if self.unit:
            schema["unit"] = self.unit
        if self.nullable:
            schema["nullable"] = True
        return schema


_TYPE_NAMES = {
    float: "a number",
    int: "a whole number",
    bool: "true or false",
    str: "a string",
    list: "a list",
}
