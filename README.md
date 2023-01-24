# Virtual Painting with webcam

![stars](https://img.shields.io/github/stars/myoluk/virtual-painting)
![forks](https://img.shields.io/github/forks/myoluk/virtual-painting)
![licence](https://img.shields.io/github/license/myoluk/virtual-painting)
![last-commit](https://img.shields.io/github/last-commit/myoluk/virtual-painting)

:star: This project is based on **OpenCV** and provides virtual painting using webcam.

:floppy_disk: `color_range.py` allows to enter the color range required to detect the object to be tracked.

:ballot_box_with_check: `paint.py` tracks the specified object and enables painting.

- 3 different marker thicknesses
- 5 different colors (purple, blue, green, red, yellow)
- paints can be erased and the entire page can be cleaned

![Virtual Painting](/images/color-pick.jpg)

## Table of Contents
- [Features](#features)
  - [Identifying Color Range](#set-color-range)
  - [Paint Tools](#paint-tools)
  - [Paint](#paint)
  - [Eraser & Clear](#eraser--clear)
  - [Discrete Writing](#discrete-writing)
- [How to use?](#how-to-use)

## Features

- ### Set Color Range
_Color range can be adjusted with trackbars._

![Set Color Range](/images/set-color-range.gif)

_After determining the color range, save by pressing the 'S' key. It will save a numpy array as `hsvVal.npy`._

_Press 'Q' to exit._


- ### Paint Tools
_3 thickness options (small, medium, large), 5 color options (purple, blue, green, red, yellow)._

![Paint Tools](/images/paint-tools.gif)


- ### Paint
_Draw whatever you want!_

![Paint](/images/paint.gif)


- ### Eraser & Clear
_**Eraser** for local cleaning, **Clear** for whole page cleaning._

![Eraser & Clear](/images/paint-eraser.gif)


- ### Discrete Writing
_There is a small trick. Flip the other side of the tracked object to write discretely. This way the marker will not be detected._

![Marker Enable/Disable](/images/marker-enable-disable.gif)

_Press 'Q' to exit._

## How to use?
1. Run the `set_color_range.py` file to set the color range (just make sure the object is detected).
2. Save the adjusted values by pressing the 'S' key. Values will be saved as `hsvVal.npy` file.
3. Run the `paint.py` file. It will automatically open the `hsvVal.npy` file.

Enjoy painting!
