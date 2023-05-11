# Virtual Paint via webcam

![stars](https://img.shields.io/github/stars/myoluk/virtual-painting)
![forks](https://img.shields.io/github/forks/myoluk/virtual-painting)
![licence](https://img.shields.io/github/license/myoluk/virtual-painting)
![last-commit](https://img.shields.io/github/last-commit/myoluk/virtual-painting)

:star: Based on **OpenCV**

:floppy_disk: [`set_color_range.py`](set_color_range.py) allows to set the color range required to detect the object to be tracked

:pencil2: [`paint.py`](paint.py) tracks the object its color was set and enables the painting

![Virtual Painting](/images/paint.png)

## Contents
- [Features](#features)
  - [Set Color Range](#rocket-set-color-range)
  - [Paint Tools](#rocket-paint-tools)
  - [Paint](#rocket-paint)
  - [Eraser & Clear](#rocket-eraser--clear)
  - [Discrete Writing](#rocket-discrete-writing)
- [How to use?](#how-to-use)

## Features

- [x] 3 different marker thicknesses (small, medium, large)

- [x] 5 different colors (🟣purple, 🔵blue, 🟢green, 🔴red, 🟡yellow)

- [x] paints can be erased and the entire page can be cleaned

- [x] possible to write discrete (with a little trick)

### :rocket: Set Color Range
:white_check_mark: _Color range can be adjusted with trackbars_

:white_check_mark: _After determining the color range, save by pressing the 'S' key, it will save a numpy array as `hsvVal.npy`_

:white_check_mark: _Press 'Q' to exit_

![Set Color Range](/images/set-color-range.gif)


### :rocket: Paint Tools
:white_check_mark: _3 thickness options (small, medium, large), 5 color options (purple, blue, green, red, yellow)_

![Paint Tools](/images/paint-tools.gif)


### :rocket: Paint
:white_check_mark: _Draw whatever you want!_

![Paint](/images/paint.gif)


### :rocket: Eraser & Clear
:white_check_mark: _**Eraser** for area cleaning, **Clear** for whole page cleaning_

![Eraser & Clear](/images/paint-eraser.gif)


### :rocket: Discrete Writing
:white_check_mark: _There is a little trick, flip the other side of the tracked object to write discretely_

:white_check_mark: _Press 'Q' to exit_

![Marker Enable/Disable](/images/marker-enable-disable.gif)


## How to use?
:one: Run the `set_color_range.py` file to set the color range (just make sure the object is detected)

:two: Save the adjusted values by pressing the 'S' key, values will be saved as `hsvVal.npy` file

:three: Run the `paint.py` file, it will automatically open the `hsvVal.npy` file

:100: Enjoy painting!
