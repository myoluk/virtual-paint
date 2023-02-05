"""
Painting With Identified Colored Object : Step 1
"""

"""
This project tracks the object whose color is defined from webcam.
First of all, the color values of the object to be tracked are set.
Second, the drawing is made by following this object.

Python use 3 channels BGR colors that equals RGB.
HSV coloring is used to set the color of the object.
Setting up with HSV is easier than others.
"""

# Libraries
import cv2
import numpy as np

# 1) Color range of object that be tracked

# Show shortcuts information
print("\n 1) Identifying object's color\n")
print("#####################################")
print("# Press 's' to save adjusted ranges #")
print("# Press 'q' to exit the program     #")
print("#####################################")
print("\n")

# Required callback method for trackbars
def nothing():
    pass

# Initializing the webcam
cap = cv2.VideoCapture(1)         # 0, 1, 2, ... are used webcam no
cap.set(3,1280)                   # Setting width of camera
cap.set(4,720)                    # Setting height of camera

# Create a window for trackbars which adjust object's color
cv2.namedWindow("Identifying")

# Creating 6 trackbars that will adjust the lower and upper range of
# H,S and V channels.
# Hue range is 0-179, S and V range is 0-255
cv2.createTrackbar("Min H", "Identifying", 0, 179, nothing)
cv2.createTrackbar("Min S", "Identifying", 0, 255, nothing)
cv2.createTrackbar("Min V", "Identifying", 0, 255, nothing)
cv2.createTrackbar("Max H", "Identifying", 179, 179, nothing)
cv2.createTrackbar("Max S", "Identifying", 255, 255, nothing)
cv2.createTrackbar("Max V", "Identifying", 255, 255, nothing)

# Showing webcam in a loop
while True:
    # Read from webcam frame by frame.
    ret, frame = cap.read()
    if not ret:
        break
    
    # Flip the frame horizontally (That makes mirror effect).
    frame = cv2.flip(frame, 1)
    
    # Convert to BGR image to HSV image.
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    
    # Get the trackbars's values that user changing
    minH = cv2.getTrackbarPos("Min H", "Identifying")
    minS = cv2.getTrackbarPos("Min S", "Identifying")
    minV = cv2.getTrackbarPos("Min V", "Identifying")
    maxH = cv2.getTrackbarPos("Max H", "Identifying")
    maxS = cv2.getTrackbarPos("Max S", "Identifying")
    maxV = cv2.getTrackbarPos("Max V", "Identifying")
    
    # Set the minimum and maximum HSV range
    minRange = np.array([minH, minS, minV])
    maxRange = np.array([maxH, maxS, maxV])
    
    # Filter the image and get binary mask (white represents object's color)
    mask = cv2.inRange(hsv, minRange, maxRange)
    
    # Also show real color of object
    coloredObject = cv2.bitwise_and(frame, frame, mask=mask)
    
    # Convert the binary mask to 3 channels image
    mask3channels = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    
    # Stack mask frame, normal frame, coloredObject frame
    stacked = np.hstack((mask3channels, frame, coloredObject))
    
    # Show stacked frames as 60%
    cv2.imshow("Identifying", cv2.resize(stacked, None, fx=0.6, fy=0.6))
    
    # If 'q' pressed then exit
    key = cv2.waitKey(1)
    if (key == ord('q') or key == ord('Q')):
        break
    
    #Save adjusted HSV ranges as hsvval.npy when 's' pressed
    if (key == ord('s') or key == ord('S')):
        hsvValues = [[minH, minS, minV],[maxH, maxS, maxV]]
        print(hsvValues)
        np.save('hsvVal', hsvValues)
        print("Saved as 'hsvVal.npy'...")
        break

# Release the camera and destroy all windows
cap.release()
cv2.destroyAllWindows()
