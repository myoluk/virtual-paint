## Virtual Painting with webcam

![stars](https://img.shields.io/github/stars/myoluk/virtual-painting)
![forks](https://img.shields.io/github/forks/myoluk/virtual-painting)
![licence](https://img.shields.io/github/license/myoluk/virtual-painting)
![last-commit](https://img.shields.io/github/last-commit/myoluk/virtual-painting)

:star: This project is based on **OpenCV** and allows you to do virtual painting using webcam.

:floppy_disk: The color range of the object to be tracked with `Identifying-Color-Range.py` is determined by the trackbars.

`Painting.py` paints by following the specified object. In addition, _3 different marker thicknesses_ can be adjusted, 
_5 different colors_ (purple, blue, green, red, yellow) can be used, paints can be _erased_ with the **Eraser** and the entire page can be _cleaned_ with **Clear**.

![Virtual Painting](https://github.com/myoluk/virtual-painting/blob/main/images/color-pick.jpg?raw=true)

### Features

- #### Identifying Color Range
> Color range can be adjusted with trackbars.

![Indentify Color Range](https://raw.githubusercontent.com/myoluk/virtual-painting/main/images/color-identify.gif)

> After determining the color range, save by pressing the 'S' key. It will save a numpy array as `hsvVal.npy`.

> Press 'Q' to exit.


- #### Paint Tools
> 3 thickness options (small, medium, large), 5 color options (purple, blue, green, red, yellow).

![Paint Tools](https://raw.githubusercontent.com/myoluk/virtual-painting/main/images/paint-tools.gif)


- #### Paint
> Draw whatever you want!

![Paint](https://raw.githubusercontent.com/myoluk/virtual-painting/main/images/paint.gif)


- #### Eraser & Clear
> **Eraser** for local cleaning, **Clear** for whole page cleaning.

![Eraser & Clear](https://raw.githubusercontent.com/myoluk/virtual-painting/main/images/paint-eraser.gif)


- #### Discrete Writing
> There is a small trick. Flip the other side of the tracked object to write discretely. This way the marker will not be detected.

![Marker Enable/Disable](https://raw.githubusercontent.com/myoluk/virtual-painting/main/images/marker-enable-disable.gif)

> Press 'Q' to exit.

### How to use?
1. Run the `Identifying-Color-Range.py` file to set the color range (just make sure the object is detected).
2. Save the adjusted values by pressing the 'S' key. Values will be saved as `hsvVal.npy` file.
3. Run the `painting.py` file. It will automatically open the `hsvVal.npy` file.

Enjoy painting!
