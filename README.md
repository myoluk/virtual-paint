# Virtual Paint via webcam

![stars](https://img.shields.io/github/stars/myoluk/virtual-painting)
![forks](https://img.shields.io/github/forks/myoluk/virtual-painting)
![licence](https://img.shields.io/github/license/myoluk/virtual-painting)
![last-commit](https://img.shields.io/github/last-commit/myoluk/virtual-painting)

:star: This project based on **OpenCV** and provides virtually paint via webcam.

:floppy_disk: `color_range.py` allows to enter the color range required to detect the object to be tracked.

:pencil2: `paint.py` tracks the specified object and enables painting.

![Virtual Painting](/images/paint.png)

## Table of Contents
- [Features](#features)
  - [Set Color Range](#rocket-set-color-range)
  - [Paint Tools](#rocket-paint-tools)
  - [Paint](#rocket-paint)
  - [Eraser & Clear](#rocket-eraser--clear)
  - [Discrete Writing](#rocket-discrete-writing)
- [How to use?](#how-to-use)

## Features

- :ballot_box_with_check: _3 different marker thicknesses_

- :ballot_box_with_check: _5 different colors (purple, blue, green, red, yellow)_

- :ballot_box_with_check: _paints can be erased and the entire page can be cleaned_

- :ballot_box_with_check: _possible to write discrete (with a small trick)_

### :rocket: Set Color Range
:white_check_mark: _Color range can be adjusted with trackbars._

:white_check_mark: _After determining the color range, save by pressing the 'S' key. It will save a numpy array as `hsvVal.npy`._

:white_check_mark: _Press 'Q' to exit._

![Set Color Range](/images/set-color-range.gif)


### :rocket: Paint Tools
:white_check_mark: _3 thickness options (small, medium, large), 5 color options (purple, blue, green, red, yellow)._

![Paint Tools](/images/paint-tools.gif)


### :rocket: Paint
:white_check_mark: _Draw whatever you want!_

![Paint](/images/paint.gif)


### :rocket: Eraser & Clear
:white_check_mark: _**Eraser** for area cleaning, **Clear** for whole page cleaning._

![Eraser & Clear](/images/paint-eraser.gif)


### :rocket: Discrete Writing
:white_check_mark: _There is a small trick. Flip the other side of the tracked object to write discretely. This way the marker will not be detected._

:white_check_mark: _Press 'Q' to exit._

![Marker Enable/Disable](/images/marker-enable-disable.gif)


## How to use?
:one: Run the `set_color_range.py` file to set the color range (just make sure the object is detected).

:two: Save the adjusted values by pressing the 'S' key. Values will be saved as `hsvVal.npy` file.

:three: Run the `paint.py` file. It will automatically open the `hsvVal.npy` file.

:100: Enjoy painting!
