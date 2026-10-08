"""Render NomNom's simple vector-style SD-card mark. Requires optional Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / 'src' / 'nomnom' / 'assets'


def render(size=1024, template=False):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    def box(values):
        return tuple(round(v * size / 1024) for v in values)
    if not template:
        draw.rounded_rectangle(box((36, 36, 988, 988)), radius=int(size * .22), fill='#F17832')
    color = '#000000' if template else '#FFF8EF'
    # A card with a clipped top corner and a friendly bite in its right edge.
    draw.polygon([box(point) for point in ((295, 178), (614, 178), (729, 293), (729, 846), (295, 846))], fill=color)
    cut = (0, 0, 0, 0) if template else '#F17832'
    for center in ((742, 550), (728, 620), (744, 690)):
        x, y = center
        draw.ellipse(box((x - 54, y - 54, x + 54, y + 54)), fill=cut)
    for x in (354, 420, 486, 552):
        draw.rounded_rectangle(box((x, 226, x + 32, 330)), radius=max(1, int(size * .009)), fill=cut)
    draw.ellipse(box((389, 431, 429, 471)), fill=cut)
    draw.ellipse(box((545, 431, 585, 471)), fill=cut)
    draw.arc(box((430, 445, 548, 557)), 15, 165, fill=cut, width=max(1, int(size * .019)))
    return image


if __name__ == '__main__':
    ASSETS.mkdir(exist_ok=True)
    render().save(ASSETS / 'NomNom.png')
    render().save(ASSETS / 'NomNom.icns', format='ICNS')
    render(template=True).save(ASSETS / 'menu-template.png')
