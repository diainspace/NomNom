"""Encode the approved NomNom app artwork as macOS ICNS. Requires Pillow.

NomNom.png and menu-template.png are the approved original artwork. Keep
these source assets intact; the menu template is scaled by AppKit.
"""
from pathlib import Path
from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / 'src' / 'nomnom' / 'assets'

if __name__ == '__main__':
    Image.open(ASSETS / 'NomNom.png').save(ASSETS / 'NomNom.icns', format='ICNS')
