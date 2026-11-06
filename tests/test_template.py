import numpy as np
from PIL import Image, ImageDraw

from agent_play.perception.capture import Frame
from agent_play.perception.template import (
    Template,
    TemplateLibrary,
    TemplatePerceiver,
    match_template,
)


def _sprite() -> Image.Image:
    sprite = Image.new("RGB", (16, 16), (20, 20, 30))
    draw = ImageDraw.Draw(sprite)
    draw.rectangle((2, 2, 13, 13), fill=(60, 120, 230), outline=(240, 240, 255))
    draw.rectangle((8, 5, 10, 7), fill=(0, 0, 0))
    return sprite


def _scene(positions):
    scene = Image.new("RGB", (200, 120), (20, 20, 30))
    noise = np.random.default_rng(1).integers(0, 12, (120, 200, 3), dtype=np.uint8)
    scene = Image.fromarray(np.asarray(scene) + noise)
    for x, y in positions:
        scene.paste(_sprite(), (x, y))
    return scene


def test_ncc_peak_is_at_the_exact_position():
    scene = _scene([(50, 30)])
    scores = match_template(np.asarray(scene.convert("L"), dtype=np.float32), np.asarray(_sprite().convert("L"), dtype=np.float32))
    assert scores.shape == (120 - 16 + 1, 200 - 16 + 1)
    y, x = np.unravel_index(np.argmax(scores), scores.shape)
    assert (x, y) == (50, 30)
    assert scores[y, x] > 0.95
    assert scores.max() <= 1.0 and scores.min() >= -1.0


def test_perceiver_finds_twins_and_suppresses_duplicates():
    scene = _scene([(10, 10), (120, 60), (170, 90)])
    perceiver = TemplatePerceiver([Template.from_image(_sprite(), "slime", "enemy", threshold=0.9)])
    nodes = perceiver.perceive(Frame(scene)).nodes
    found = sorted((int(n.bounds.x), int(n.bounds.y)) for n in nodes)
    assert found == [(10, 10), (120, 60), (170, 90)]
    assert all(n.role == "enemy" and n.source == "template" and n.interactive for n in nodes)
    assert all(n.identity_key() == nodes[0].identity_key() for n in nodes), "twins share identity; position tells them apart"


def test_solid_template_never_matches_and_tiny_image_is_safe():
    solid = np.full((8, 8), 100.0, dtype=np.float32)
    assert match_template(np.zeros((20, 20), dtype=np.float32), solid).max() == 0.0
    assert match_template(np.zeros((4, 4), dtype=np.float32), solid).size == 0


def test_threshold_rejects_a_different_sprite():
    other = Image.new("RGB", (16, 16), (20, 20, 30))
    ImageDraw.Draw(other).ellipse((2, 2, 13, 13), fill=(200, 40, 40))
    scene = _scene([])
    scene.paste(other, (60, 60))
    perceiver = TemplatePerceiver([Template.from_image(_sprite(), "slime", "enemy", threshold=0.9)])
    assert perceiver.perceive(Frame(scene)).nodes == []


def test_library_naming_convention(tmp_path):
    _sprite().save(tmp_path / "button__start_game.png")
    _sprite().save(tmp_path / "coin.png")
    (tmp_path / "templates.json").write_text('{"coin": {"role": "pickup", "threshold": 0.8}}')
    templates = {t.name: t for t in TemplateLibrary.load_dir(tmp_path)}
    assert templates["start game"].role == "button"
    assert templates["coin"].role == "pickup" and templates["coin"].threshold == 0.8
