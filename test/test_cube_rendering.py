from PIL import Image

from rubik.cube import Cube
from rubik.draw import draw_rubiks_cube
from rubik.utils import rotate_90_clockwise, rotate_90_counterClockwise


def test_rotation_helpers_are_inverses():
    face = [[1, 2], [3, 4]]
    assert rotate_90_counterClockwise(rotate_90_clockwise(face)) == face


def test_cube_four_quarter_turns_restore_solved_state():
    cube = Cube()
    original = {name: [row[:] for row in face] for name, face in cube.faces.items()}
    cube.scrambleCube("R R R R")
    assert cube.faces == original


def test_scramble_parser_supports_prime_double_and_wide_moves():
    cube = Cube(4)
    cube.scrambleCube("Rw U2 3Fw'")
    assert all(len(face) == 4 and len(face[0]) == 4 for face in cube.faces.values())


def test_draw_cube_returns_png_with_stable_dimensions():
    result = draw_rubiks_cube(Cube())
    with Image.open(result) as image:
        assert image.format == "PNG"
        assert image.size == (615, 460)
