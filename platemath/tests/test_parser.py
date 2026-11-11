import pytest

from api.parser import parse_line, parse_recipe


def fields(line):
    p = parse_line(line)
    return (p.quantity, p.quantity_max, p.unit, p.size, p.name, p.note)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # quantity, quantity_max, unit, size, name, note
        ("2 cups all-purpose flour", (2, None, "cup", None, "all-purpose flour", None)),
        ("1 1/2 cups sugar", (1.5, None, "cup", None, "sugar", None)),
        ("1-1/2 cups sugar", (1.5, None, "cup", None, "sugar", None)),
        ("½ tsp salt", (0.5, None, "tsp", None, "salt", None)),
        ("1½ cups milk", (1.5, None, "cup", None, "milk", None)),
        ("10½ oz dark chocolate", (10.5, None, "oz", None, "dark chocolate", None)),
        ("1⁄2 cup sugar", (0.5, None, "cup", None, "sugar", None)),
        (".5 cup oil", (0.5, None, "cup", None, "oil", None)),
        ("1/3 cup honey", (0.3333, None, "cup", None, "honey", None)),
    ],
)
def test_quantities(line, expected):
    assert fields(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("2-3 cloves garlic, minced", (2, 3, "clove", None, "garlic", "minced")),
        ("2 to 3 tbsp olive oil", (2, 3, "tbsp", None, "olive oil", None)),
        ("2 – 3 cups stock", (2, 3, "cup", None, "stock", None)),
        ("1/2-3/4 cup milk", (0.5, 0.75, "cup", None, "milk", None)),
        ("1 or 2 eggs", (1, 2, None, None, "eggs", None)),
    ],
)
def test_ranges(line, expected):
    assert fields(line) == expected


@pytest.mark.parametrize(
    ("line", "unit"),
    [
        ("400g plain flour", "g"),
        ("1.5kg potatoes", "kg"),
        ("8 oz cream cheese", "oz"),
        ("1 lb ground beef", "lb"),
        ("250 ml milk", "ml"),
        ("1 L milk", "l"),
        ("3 C flour", "cup"),
        ("1 Tbsp. butter", "tbsp"),
        ("1 T sugar", "tbsp"),  # capital T is a tablespoon
        ("1 t salt", "tsp"),  # small t is a teaspoon
        ("8 fl. oz. milk", "fl oz"),
        ("2 fluid ounces cream", "fl oz"),
        ("1 pint strawberries", "pint"),
        ("1 stick butter", "stick"),
        ("1 can chickpeas", "can"),
    ],
)
def test_units(line, unit):
    assert parse_line(line).unit == unit


def test_unit_must_be_a_whole_word():
    # "g" must not be read off the front of "garlic".
    assert fields("2 garlic cloves") == (2, None, None, None, "garlic cloves", None)


def test_unit_word_alone_is_the_ingredient():
    # Whole cloves, the spice.
    assert fields("3 cloves") == (3, None, None, None, "cloves", None)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("a pinch of salt", (1, None, "pinch", None, "salt", None)),
        ("Pinch of salt", (None, None, "pinch", None, "salt", None)),
        ("one cup rice", (1, None, "cup", None, "rice", None)),
        ("an onion", (1, None, None, None, "onion", None)),
        ("A few sprigs thyme", (None, None, None, None, "A few sprigs thyme", None)),
        ("2 cups of water", (2, None, "cup", None, "water", None)),
    ],
)
def test_words(line, expected):
    assert fields(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("3 large eggs", (3, None, None, "large", "eggs", None)),
        ("2 extra large eggs", (2, None, None, "extra large", "eggs", None)),
        ("1 medium onion, diced", (1, None, None, "medium", "onion", "diced")),
    ],
)
def test_sizes(line, expected):
    assert fields(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("1 onion, finely chopped", (1, None, None, None, "onion", "finely chopped")),
        ("Salt and pepper, to taste", (None, None, None, None, "Salt and pepper", "to taste")),
        ("salt and pepper to taste", (None, None, None, None, "salt and pepper", "to taste")),
        ("2 tbsp butter, divided", (2, None, "tbsp", None, "butter", "divided")),
        ("fresh basil leaves, for garnish", (None, None, None, None, "fresh basil leaves", "for garnish")),
        ("1 cup packed brown sugar", (1, None, "cup", None, "brown sugar", "packed")),
        ("1 heaping cup flour", (1, None, "cup", None, "flour", "heaping")),
        ("1 (14.5 oz) can diced tomatoes", (1, None, "can", None, "diced tomatoes", "14.5 oz")),
        # The comma inside the parentheses doesn't split the line.
        ("1 (8 oz, softened) package cream cheese", (1, None, "package", None, "cream cheese", "8 oz, softened")),
        ("2 8-ounce packages cream cheese", (2, None, "package", None, "cream cheese", "8-ounce")),
        ("1 2-inch piece ginger", (1, None, "piece", None, "ginger", "2-inch")),
        ("2 1/2-inch piece ginger", (None, None, "piece", None, "ginger", "2 1/2-inch")),
    ],
)
def test_notes(line, expected):
    assert fields(line) == expected


@pytest.mark.parametrize(
    "line",
    ["2 oranges", "2 tomatoes", "1 cup half and half"],
)
def test_words_that_start_like_keywords(line):
    # "or" and "to" (ranges) and "half" mustn't be read out of ingredient names.
    p = parse_line(line)
    assert p.quantity_max is None
    assert p.name in {"oranges", "tomatoes", "half and half"}


@pytest.mark.parametrize("line", ["1/0 cup flour", "0 cups flour", "", "   ", "(", ",", "-", "1 cup"])
def test_odd_input_never_raises(line):
    p = parse_line(line)
    assert p.quantity is None or p.quantity > 0


def test_keeps_the_original_text():
    assert parse_line("  - 1½ cups milk ").text == "1½ cups milk"


def test_parse_recipe_skips_blanks_headings_and_bullets():
    text = """
    Ingredients

    For the dough:
    - 2 cups flour
    ▢ 1 cup water
    • 1 egg

    For the glaze:
    * 1 cup powdered sugar
    """
    names = [p.name for p in parse_recipe(text)]
    assert names == ["flour", "water", "egg", "powdered sugar"]
