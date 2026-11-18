"""Capture the isolated Linux X11 display rather than Chromium's viewport."""

import os
import sys

from PIL import Image
from Xlib import X, display


def main():
    connection = display.Display()
    try:
        screen = connection.screen()
        assert os.environ["DISPLAY"] == sys.argv[1]
        assert screen.root_depth == 24
        geometry = screen.root.get_geometry()
        size = (geometry.width, geometry.height)
        pixels = screen.root.get_image(0, 0, *size, X.ZPixmap, 0xFFFFFFFF)
        Image.frombytes("RGB", size, pixels.data, "raw", "BGRX").save(sys.argv[2])
    finally:
        connection.close()


if __name__ == "__main__":
    main()
