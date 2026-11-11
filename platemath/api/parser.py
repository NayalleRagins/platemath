"""Turns ingredient lines like "1 1/2 cups flour, sifted" into structured data.

This module only reads the text. Matching an ingredient to a food and
converting its amount to grams happen in later steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

__all__ = ["ParsedIngredient", "parse_line", "parse_recipe"]


@dataclass(frozen=True)
class ParsedIngredient:
    text: str
    """The line as written, without surrounding spaces or a list bullet."""

    quantity: float | None
    """How much, e.g. 1.5 for "1 1/2". None when there's no amount ("salt to taste")."""

    quantity_max: float | None
    """Upper end of a range like "2-3 cloves". None otherwise."""

    unit: str | None
    """Standard unit name such as "cup", "tbsp" or "g". None for counted items ("2 eggs")."""

    size: str | None
    """"small", "medium", "large", ... when the line says so."""

    name: str
    """The ingredient to look up, e.g. "all-purpose flour"."""

    note: str | None
    """Everything else: prep ("finely chopped"), package size ("14.5 oz"), "to taste"."""


# --- Units -----------------------------------------------------------------

_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "cup": ("cup", "cups", "c"),
    "tbsp": ("tablespoon", "tablespoons", "tbsp", "tbsps", "tbs", "tbl", "tbls", "tblsp"),
    "tsp": ("teaspoon", "teaspoons", "tsp", "tsps"),
    "fl oz": ("floz",),  # the two-word spellings are in _TWO_WORD_UNITS
    "oz": ("ounce", "ounces", "oz"),
    "lb": ("pound", "pounds", "lb", "lbs"),
    "g": ("gram", "grams", "g", "gr", "grs"),
    "kg": ("kilogram", "kilograms", "kg", "kgs", "kilo", "kilos"),
    "mg": ("milligram", "milligrams", "mg"),
    "ml": ("milliliter", "milliliters", "millilitre", "millilitres", "ml", "mls"),
    "l": ("liter", "liters", "litre", "litres", "l"),
    "pint": ("pint", "pints", "pt", "pts"),
    "quart": ("quart", "quarts", "qt", "qts"),
    "gallon": ("gallon", "gallons", "gal", "gals"),
    "pinch": ("pinch", "pinches"),
    "dash": ("dash", "dashes"),
    "can": ("can", "cans", "tin", "tins"),
    "stick": ("stick", "sticks"),
    "clove": ("clove", "cloves"),
    "slice": ("slice", "slices"),
    "package": ("package", "packages", "pkg", "pkgs", "packet", "packets"),
    "jar": ("jar", "jars"),
    "bunch": ("bunch", "bunches"),
    "sprig": ("sprig", "sprigs"),
    "head": ("head", "heads"),
    "stalk": ("stalk", "stalks"),
    "piece": ("piece", "pieces"),
    "handful": ("handful", "handfuls"),
}
_UNITS = {alias: unit for unit, aliases in _UNIT_ALIASES.items() for alias in aliases}
_TWO_WORD_UNITS = {"fl oz": "fl oz", "fluid ounce": "fl oz", "fluid ounces": "fl oz"}
# Old cookbook shorthand where case matters: T is a tablespoon, t is a teaspoon.
_CASE_SENSITIVE_UNITS = {"T": "tbsp", "t": "tsp"}
# Units that make sense without a number in front ("pinch of salt").
_UNITS_WITHOUT_QUANTITY = {"pinch", "dash", "handful"}

_SIZES = {"small", "medium", "large", "extra-large", "extra large", "jumbo"}
_MODIFIERS = {
    "heaping", "heaped", "level", "scant", "rounded", "generous",
    "packed", "lightly packed", "firmly packed", "loosely packed",
}  # fmt: skip

# --- Numbers ---------------------------------------------------------------

_UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6",
    "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}  # fmt: skip
_UNICODE_FRACTION_RE = re.compile(rf"(\d)?\s*([{''.join(_UNICODE_FRACTIONS)}])")
# "1-1/2 cups" is the US way of writing one and a half, not a range.
_HYPHENATED_MIXED_RE = re.compile(r"(?<![\d/.])(\d+)-(\d+/\d+)")

_AMOUNT = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|\.\d+"  # "1 1/2", "1/2", "1.5", ".5"
_QUANTITY_RE = re.compile(rf"^(?P<low>{_AMOUNT})(?:\s*(?:-|to|or)\s*(?P<high>{_AMOUNT}))?")
# "2-inch piece", "8-ounce package": a measurement that describes the item.
_DIMENSION_RE = re.compile(rf"^(?:{_AMOUNT})-[a-z]+\b", re.IGNORECASE)

_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip
# "a few sprigs" and "a couple of eggs" aren't "1 of something".
_VAGUE_AFTER_A = {"few", "couple", "little", "bit"}

# --- Other text ------------------------------------------------------------

_BULLET_RE = re.compile(r"^(?:[•·▢□☐◦‣]\s*|[-*–—]\s+)")
_PARENS_RE = re.compile(r"\(([^()]*)\)")
_TRAILING_NOTE_RE = re.compile(
    r"\s+(to taste|as needed|optional|divided|for garnish|for serving|for frying)$",
    re.IGNORECASE,
)


def parse_recipe(text: str) -> list[ParsedIngredient]:
    """Parses an ingredient list, one ingredient per line.

    Blank lines and section headings such as "For the glaze:" are skipped.
    """
    ingredients = []
    for raw_line in text.splitlines():
        line = _strip_bullet(raw_line.strip())
        if not line or _is_heading(line):
            continue
        ingredients.append(parse_line(line))
    return ingredients


def parse_line(line: str) -> ParsedIngredient:
    """Parses a single ingredient line. Never raises; unknown parts end up in `name`."""
    text = _strip_bullet(line.strip())
    rest = _normalize(text)
    notes: list[str] = []

    # "1 (14.5 oz) can tomatoes": parentheses hold sizes and asides.
    notes.extend(part.strip() for part in _PARENS_RE.findall(rest) if part.strip())
    rest = _PARENS_RE.sub(" ", rest)

    # "1 onion, finely chopped": what comes after the first comma is prep.
    rest, _, after_comma = rest.partition(",")
    rest = " ".join(rest.split())

    # "2-inch piece ginger": the number is the piece's size, not how many.
    dimension, rest = _take_dimension(rest)
    if dimension:
        quantity, quantity_max = None, None
    else:
        quantity, quantity_max, rest = _take_quantity(rest)
        # "2 8-ounce packages cream cheese"
        dimension, rest = _take_dimension(rest)
    if dimension:
        notes.insert(0, dimension)

    size, rest = _take_phrase(rest, _SIZES)
    modifier, rest = _take_phrase(rest, _MODIFIERS)

    unit = None
    if quantity is not None or dimension or _peek_unit(rest)[0] in _UNITS_WITHOUT_QUANTITY:
        unit, unit_words, rest = _take_unit(rest)
        if unit and not _strip_of(rest):
            # "3 cloves" is the spice, not 3 cloves of nothing.
            rest, unit = unit_words, None
        rest = _strip_of(rest)

    if modifier is None:
        modifier, rest = _take_phrase(rest, _MODIFIERS)
    if modifier:
        notes.insert(0, modifier)

    if after_comma.strip():
        notes.append(" ".join(after_comma.split()))

    trailing = _TRAILING_NOTE_RE.search(rest)
    if trailing:
        notes.append(trailing.group(1).lower())
        rest = rest[: trailing.start()]

    name = rest.strip(" .;:-")
    return ParsedIngredient(
        text=text,
        quantity=quantity,
        quantity_max=quantity_max,
        unit=unit,
        size=size,
        name=name,
        note="; ".join(notes) or None,
    )


def _strip_bullet(line: str) -> str:
    return _BULLET_RE.sub("", line, count=1)


def _is_heading(line: str) -> bool:
    return line.endswith(":") or line.lower() == "ingredients"


def _normalize(text: str) -> str:
    """Spells fractions and dashes one way so the regexes stay simple."""
    text = text.replace("⁄", "/")  # fraction slash, as in "1⁄2"
    text = text.replace("–", "-").replace("—", "-")

    def expand(match: re.Match[str]) -> str:
        whole, fraction = match.group(1), _UNICODE_FRACTIONS[match.group(2)]
        return f"{whole} {fraction}" if whole else fraction

    text = _UNICODE_FRACTION_RE.sub(expand, text)
    text = _HYPHENATED_MIXED_RE.sub(r"\1 \2", text)
    return " ".join(text.split())


def _take_quantity(text: str) -> tuple[float | None, float | None, str]:
    match = _QUANTITY_RE.match(text)
    if match:
        low = _to_number(match.group("low"))
        high = _to_number(match.group("high")) if match.group("high") else None
        if low is not None:
            if high is not None and high <= low:
                high = None
            return low, high, text[match.end() :].lstrip()

    first, _, after = text.partition(" ")
    number = _WORD_NUMBERS.get(first.lower())
    if number is not None and after:
        next_word = after.split(maxsplit=1)[0].lower()
        if not (number == 1 and next_word in _VAGUE_AFTER_A):
            return float(number), None, after
    return None, None, text


def _take_dimension(text: str) -> tuple[str | None, str]:
    match = _DIMENSION_RE.match(text)
    if not match:
        return None, text
    return match.group(0), text[match.end() :].lstrip()


def _to_number(text: str) -> float | None:
    try:
        whole, _, fraction = text.strip().rpartition(" ")
        value = Fraction(fraction) + (int(whole) if whole else 0)
    except (ValueError, ZeroDivisionError):
        return None
    if value <= 0:
        return None
    return round(float(value), 4)


def _take_phrase(text: str, phrases: set[str]) -> tuple[str | None, str]:
    """Takes a one- or two-word phrase from `phrases` off the front of `text`."""
    words = text.split(maxsplit=2)
    for count in (2, 1):
        if len(words) >= count:
            candidate = " ".join(words[:count]).lower()
            if candidate in phrases:
                return candidate, " ".join(words[count:])
    return None, text


def _peek_unit(text: str) -> tuple[str | None, int]:
    """Returns (unit, number of words it uses) for the start of `text`."""
    words = [w.rstrip(".") for w in text.split(maxsplit=2)]
    if len(words) >= 2:
        two = f"{words[0]} {words[1]}".lower()
        if two in _TWO_WORD_UNITS:
            return _TWO_WORD_UNITS[two], 2
    if words:
        if words[0] in _CASE_SENSITIVE_UNITS:
            return _CASE_SENSITIVE_UNITS[words[0]], 1
        unit = _UNITS.get(words[0].lower())
        if unit:
            return unit, 1
    return None, 0


def _take_unit(text: str) -> tuple[str | None, str, str]:
    """Returns (unit, the words it was written as, the rest of the text)."""
    unit, count = _peek_unit(text)
    if not unit:
        return None, "", text
    words = text.split(maxsplit=count)
    return unit, " ".join(words[:count]), " ".join(words[count:])


def _strip_of(text: str) -> str:
    """'2 cups of flour' -> 'flour'."""
    return text[3:] if text.lower().startswith("of ") else text
