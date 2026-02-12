from sl3 import *
import utime
import math
from serial import Serial
from time import sleep, time, localtime
from os import ismount, exists, mkdir, rename, statvfs
from binascii import crc32

# Camera485.py (C) 2021 Ott Hydromet, version 2.1 (modified for lower compression, and added maxPictureSize setting)
#
# Purpose:
#
# This script will capture still jpeg images from a Camera485 camera using the RS485 port of the XL2 and the camera and
# archive them to an SDHC card and also store them for transmission. Power to the camera is automatically controlled
# by the XL2 using switched power. The images are stored in daily folders created under /sd/Sutron/Camera485 and in
# the /sd/TX1 folder for transmission and automatic deletion. The way the images are named and stored can
# be modified by editing the imageFolder, txFolder, and imageFileName global variables. You may also select whether
# you want the power to the camera to always be on, whether to sync time to the camera, and whether to modify the
#
# The script will not try to capture an image if an SDHC card is not inserted. The SDHC card will also eventually
# fill up if not periodically replaced or the pictures on the card deleted.
#
# Using the script is very simple. Just schedule it to run as frequently as you wish to capture a picture.
# The fastest it can be scheduled is about once per minute in order to leave time to power on the camera,
# and transfer the image.
#
# Tested with:
#
# Camera485
#   with the RS485 port of the XLink500 connected to the RS485 port of the Camera485
#   and Switched Power 1 of the XLink500 connected to the DC12V input of the camera.
#
#   XLink           Camera485
#   =========       ============
#   SW'D +12V  ...  Red Wire
#   GND        ...  Black Wire
#   RS485-A    ...  Yellow Wire
#   RS485-B    ...  White Wire
#
#


# where to store each snapshot
imageFolder = "/sd/Sutron/Camera485/{YYYY}{MM}{DD}"

# what to name each snapshot
imageFileName = "Camera485_{YY}{MM}{DD}{hh}{mm}{ss}.jpg"

# where to store images for transmission (None means do to store for tx)
txFolder = "/sd/TX2"

# option to leave the camera on (except in case of an error) to permit capturing pictures more often
leavePowerOn = False

# how the camera is powered: None, "SW1", "SW2", "PROT12", "SDI1" or "SDI2"
#portPower = "SW1"
portPower = "PROT12"

# how to use the IR LED's of the camera: "ON" for on all the time, None for auto switching
ledMode = None

# provide a text overlay to the camera to add to each image to display station name and a time stamp
useTextOverlay = True

# text overlay settings (when useTextOverlay is True)
overlayX = 10          # horizontal pixel position of overlay text
overlayY = 10          # vertical pixel position of overlay text
overlayFontSize = 16   # font height for overlay text

# address of camera on the RS-485 bus
defaultAddress = 1

# resolution to take pictures (see resolutionOptions below)
# - higher resolutions may fail to snap if the resulting image is bigger than the camera's buffer
#   and you will need to apply compression
defaultResolution = "1280x720"

# compression ratio(0 - 5) larger value is more compressed, 0 is the highest quality
defaultCompression = 3

# resolutions and compression levels to attempt in case the `defaultResolution` creates too large of an image for the camera
# ex: [("1920x1080", 3), ("1280x720", 1)]
retrySettings = []

# how many times to try an operation before failing
# (if one retry doesn't work, the camera probably needs to be power cycled)
defaultTries = 2

# how many times to cycle power before failing
defaultPowerCycles = 3

# how much data to request from the camera at a time
defaultPacketSize = 8192

# how long to wait for a reply to a command
defaultTimeout = 8.0

# number of seconds to wait after power on before trying to communicate with the camera
cameraWarmup = 3.5

# do not take a picture unless there are 64MB or more bytes free on the SDHC card
free_space_limit_take = 64

# do not archive a picture unless there are 256MB or more bytes free on the SDHC card
free_space_limit_archive = 256

# when using an auto setting, the s/w will repeat snapshots until it 
# finds the highest quality picture of less than this size
maxPictureSize = 450000

totalPictures = 0
totalFails = 0
totalRetries = 0
totalRepower = 0
totalNoSD = 0

resolutionOptions = {
    "640x480":5,"1280x960":6,"800x600":7,"1024x768":8,"1600x1024":10,"1600x1200":11,"1280x720":15,
    "1920x1080":16,"1280x1024":17,"480x270":30,"640x360":31,"800x450":32,"960x540":33,"1024x576":34,
    "1280x720_NEW":35,"1366x768":36,"1440x810":37,"1600x900":38 }

# what the camera sends when a snapshot is taken and the camera cannot hold it
out_of_memory = b"Len>JpegBufMaxLen\r\n"

class SDCardNotMountedError(Exception):
    pass

class SDCardLowOnSpace(Exception):
    pass

class CameraError(Exception):
    pass

class CameraMemoryError(CameraError):
    pass

def TurnCamera(state):
    """
    Turn the camera on/off

    :param state: True turns the camera on, False turns it off
    :return: True if the camera is on
    """
    if not portPower:
        return True
    s = "On" if state else "Off"
    if portPower == "SDI1":
        cmd = "SDI PORT1 POWER "
    elif portPower == "SDI2":
        cmd = "SDI PORT2 POWER "
    else:
        cmd = "POWER {} ".format(portPower)
    return s in command_line(cmd + s)

def IsCameraOn():
    """
    Returns the state of power to the camera

    :return: True if the camera is on
    """
    if not portPower:
        return True
    if portPower == "SDI1":
        cmd = "SDI PORT1 POWER "
    elif portPower == "SDI2":
        cmd = "SDI PORT2 POWER "
    else:
        cmd = "POWER " + portPower
    return "On" in command_line(cmd)

def FormattedTimeStamp(timeStamp, dateTimeString):
    """
    Add time and data information to a string

    :param timeStamp: a time to use to format the string s
    :param dateTimeString: a string with key fields like {YYYY}{YY}{MM}{DD}{hh}{mm}{ss}
    :return: dateTimeString with the key fields replaced with the actual date/time information from timeStamp
    """
    t = list(localtime(timeStamp))
    # build up a dictionary we can use to translate from time / date keys to actual formatted values
    d = {"YYYY": "{:04}".format(t[0]) }
    t[0] %= 100
    for i,j in zip(["YY","MM","DD","hh","mm","ss","dow","julian"], t):
        d[i] = "{:02}".format(j)
    # time stamp the string by converting text fields like {YY} in the string to the 2-digit year, etc
    # with the help of the dictionary we setup to help us
    return dateTimeString.format(**d)

def GetOverlayText(timeStamp):
    """
    Get the text to be showed on the camera overlay

    :return: The default overlay setting with the station's name at the beginning
    """
    # customize the overlay displayed on the camera
    return " {} {} ".format(command_line("station name").strip(),FormattedTimeStamp(timeStamp, "{MM}/{DD}/{YYYY} {hh}:{mm}:{ss}"))    # mm/dd/yyyy hh:mm:ss            

def PurgeInput(port, timeout=0.01):
    try:
        t = port.timeout
        port.timeout = timeout
        while port.read(256):
            pass
    finally:
        port.timeout = t

def FormatCommand(addr, cmd, data):
    """
    Formats a command to the camera

    :param addr: address of camera (default is 1, 0 and 255 are the broadcast address)
    :param cmd: a camera protocol command byte
    :param data: data to be sent with the command (bytes)
    :return:
    """
    l = len(data)
    msg = bytes((addr, cmd)) + int.to_bytes(l, 2) + data
    crc = crc_xmodem(msg)
    return b"\x90\xeb" + msg + int.to_bytes(crc, 2)
    
def FormatSnapshot(addr=1, resolution="1920x1080", compression=1):
    """
    Creates a snapshot packet given the resolution and compression level

    :param addr:        camera address (default 1)
    :param resolution:  a valid resolution for the camera (ex: "1920x1080") see resolutionOptions
    :param compression: compression ratio (1-5) larger value is more compressed
    :return:            True if the overlay was updated
    """
    return FormatCommand(addr, 0x40, int.to_bytes(defaultPacketSize, 2) + bytes((resolutionOptions[resolution], compression)))

def CheckCrc(pkt):
    """
    Checks the CRC of a packet

    :param pkt: bytes of data
    :returns: True if the CRC was correct
    """
    return len(pkt) > 4 and crc_xmodem(pkt[2:-2]) == int.from_bytes(pkt[-2:])

def SendCommand(port, pkt, expectedLen=0, tries=3, is_snapshot=False):
    """
    Send a command to the camera and get the reply

    :param port: serial port with pre-configured timeout
    :param pkt: message to send
    :param expectedLen: the number of bytes in the message if known
    :param tries: how many attempts to make
    :return: the reply from the camera or None if a timeout or bad message
    """
    global totalRetries
    for _ in range(tries):
        port.reset_input_buffer()
        port.write(pkt)
        if expectedLen:
            msg = port.read(expectedLen)
        else:
            msg = port.read(6)
            if msg and msg[:2] == b"\x90\xeb" and msg[3] == pkt[3]:
                len = min(defaultPacketSize, int.from_bytes(msg[4:6]))
                msg += port.read(len+2)
        if msg and CheckCrc(msg):
            return msg
        elif is_snapshot and msg == out_of_memory:
            return msg
        elif tries > 1: # do not count tries when waiting for power up
            totalRetries += 1
    return None

def IsCameraReady(port, addr=1, timeout=10):
    """
    Check to see if the camera is powered up and ready to communicate

    :param port: serial port
    :param addr: address of camera (default is 1, 0 and 255 are the broadcast address)
    :param timeout: maximum time to wait
    :return: True if the camera is ready for communications
    """
    test_command = FormatCommand(addr, 0x01, b"\x55\xaa")
    old = port.timeout
    try:
        port.timeout = 0.25
        t = time()
        result = False
        while True:
            PurgeInput(port, 0.25)
            if SendCommand(port, test_command, 11, 1):
                result = True
                break
            if (time()-t) >= timeout:
                break
    finally:
        port.timeout = old
    return result

def SendSnapshot(port, snapshot, tries=3):
    """
    Sends a command to take a picture and returns the expected total length of the image

    :param port: serial port with pre-configured timeout
    :param snapshot: message to send
    :param tries: how many attempts to make
    :return: the number of bytes in the image or else None
    """
    pkt = SendCommand(port, snapshot, 19, tries, True)
    if pkt == out_of_memory:
        return pkt
    return int.from_bytes(pkt[7:11]) if pkt else None

def GetPartOfImage(port, addr, pos, numBytes, tries=3):
    """
    Retrieves part of an image that was snapped.

    :param port: serial port with pre-configured timeout
    :param addr: address of camera (default is 1, 0 and 255 are the broadcast address)
    :param pos: index in to the image to retrieve (32-bits)
    :param numBytes: number of bytes to retrieve
    :param tries: how many attempts to make
    :return: the piece of the image or None
    """
    pkt = SendCommand(port, FormatCommand(addr, 0x48, int.to_bytes(pos, 4) + int.to_bytes(numBytes, 2)),
                     8+numBytes, tries)
    return pkt[6:-2] if pkt else None

def UpdateOverlay(port, addr, x, y, font_size, text, tries=3):
    """
    Update the overlay displayed over the camera image

    :param port:        serial port
    :param addr:        address of camera (default is 1, 0 and 255 are the broadcast address)
    :param x:           horizontal pixel position of text overlay (0 is left)
    :param y:           vertical pixel position of the test overlay (0 is right)
    :param font_size:   pixel height of text font
    :param text:        string to be displayed (not bytes)
    :param tries: how many attempts to make
    :return:            True if the overlay was updated
    """
    cmd = FormatCommand(addr, 0x52, int.to_bytes(x, 2) + int.to_bytes(y, 2) + int.to_bytes(font_size, 1) + str_to_bytes(text))
    pkt = SendCommand(port, cmd, 8, tries)
    return True if pkt else False

def TurnLED(port, addr, state, tries=3):
    """
    Control's the LED of the camera

    :param port:        serial port
    :param state:       "ON", "OFF", or "AUTO" (is the default, and does not have a reply).
                        Unfortunately "OFF" only deactives an "ON", the LED will still turn
                        on automatically if there isn't enough light.
    :param tries:       how many attempts to make
    :return:            True if the overlay was updated
    """
    if state == "ON":
        data = b"\x33\x00"
    elif state == "OFF":
        data = b"\xcc\x00"
    elif state == "AUTO":
        data = b"\x33\x01"
    else:
        return False
    cmd = FormatCommand(addr, 0x07, data)
    pkt = SendCommand(port, cmd, 8, tries)
    return True if pkt or (state == "AUTO") else False

def AdjustDelay(port, addr, tries=3):
    """
    Adjust's the LED timing for the new camera model

    :param port:      serial port
    :param tries:     how many attempts to make
    :return:          True if the command was accepted
    """
    cmd = FormatCommand(addr, 0x78, b"\x78\x78\x1a\x1a")
    pkt = SendCommand(port, cmd, 10, tries)
    return True if pkt or (state == "AUTO") else False

def GetPicture(port, t, outputFile):
    if not IsCameraReady(port):
        raise CameraError("Camera is not communicating, is it connected?")
    if ledMode:
        if TurnLED(port, defaultAddress, ledMode, defaultTries):
            print("Turned LED", ledMode)
        else:
            print("Unable to turn LED", ledMode)
    if useTextOverlay:
        if UpdateOverlay(port, defaultAddress, overlayX, overlayY, overlayFontSize, GetOverlayText(t), defaultTries):
            print("Updated the camera's overlay")
        else:
            print("Failed to set the camera's text overlay")
    if AdjustDelay(port, defaultAddress, defaultTries):
        print("LED delay adjusted")
    else:
        print("Failed to adjust LED delay")

    # request the camera to take a snapshot
    imageLength = 0
    totalLength = SendSnapshot(port, FormatSnapshot(defaultAddress, defaultResolution, defaultCompression),
                               defaultTries)

    # if the snapshot was too big for the camera's RAM or just too big in general,
    # try backup resolution and compression levels
    if retrySettings:
        if totalLength == out_of_memory:
            ran_out = True
        else:
            ran_out = False
        if totalLength == out_of_memory or totalLength > maxPictureSize:
            for resolution, compression in retrySettings:
                totalLength = SendSnapshot(port, FormatSnapshot(defaultAddress, resolution, compression),
                                           defaultTries)
                if totalLength and totalLength != out_of_memory and totalLength <= maxPictureSize:
                    if ran_out:
                        print("Using {} with compression {} due to lack of memory in camera to capture image".format(
                              resolution, compression))
                    else:
                        print("Using {} with compression {} to reduce the size of the image".format(
                              resolution, compression))
                    break

    if totalLength == out_of_memory:
        raise CameraMemoryError("Camera lacks memory to take snapshot, decrease resolution or increase compression")
    elif not totalLength:
        raise CameraError("Unable to snap image from camera")

    # receive the file in 8KB chunks
    while imageLength < totalLength:
        data = GetPartOfImage(port, defaultAddress, imageLength, min(totalLength - imageLength, defaultPacketSize),
                              defaultTries)
        if data:
            outputFile.write(data)
            imageLength += len(data)
        else:
            raise CameraError("Failed to retrieve camera image, received: " + str(imageLength))
    return imageLength

def CrcFile(name):
    """"
    Compute the CRC32 for a file

    :param name: the name of the file
    """
    result = 0
    with open(name, "rb") as f:
        while True:
            block = f.read(4096)
            if not block:
                break
            result = crc32(block, result)
    return result

def TakePicture(resolution, compression, retry_settings):
    global totalPictures, totalFails, totalRepower, totalRetries, totalNoSD
    global defaultResolution, defaultCompression, retrySettings

    if not ismount("/sd"):
        totalNoSD += 1
        raise SDCardNotMountedError("SD card must be inserted to take pictures")

    vfs = statvfs("/sd")
    free_space_mb = vfs[3] * vfs[0] / 1024 / 1024

    if free_space_mb < free_space_limit_take:
        raise SDCardLowOnSpace("SD card is too low on space to take a picture, {}MB free".format(free_space_mb))

    if not txFolder and (free_space_mb < free_space_limit_archive):
        raise SDCardLowOnSpace("SD card is too low on space to archive a picture, {}MB free".format(free_space_mb))

    defaultResolution = resolution
    defaultCompression = compression
    retrySettings = retry_settings

    # capture the start time so we can provide some performance information
    t1 = time()
    t2 = t1
    t3 = None
    ok = False
    imageLength = 0
    try:
        t = time()
        folder = FormattedTimeStamp(t, imageFolder)
        # the {CRC} field has to be post-processed, so, we need to rename it temporarily so as not to confuse FormattedTimeStamp
        fileName = FormattedTimeStamp(t, imageFileName.replace("{CRC}","\x01CRC\x01")).replace("\x01CRC\x01","{CRC}")
        imagePath = folder + "/" + fileName

        if not exists(folder):
            command_line('FILE MKDIR "{}"'.format(folder))

        with Serial("RS485", 115200) as port:
            port.rs485 = True
            port.timeout = defaultTimeout
            # size the input buffer a bit bigger than we need to reserve space for DMA buffers and other bytes
            port.set_buffer_size(defaultPacketSize * 11 // 8, None)

            exc = None
            for _ in range(defaultPowerCycles):
                with open(imagePath, "wb") as outputFile:
                    try:
                        t1 = time()
                        exc = None
                        # was the camera left powered up?
                        if not IsCameraOn():
                            TurnCamera(True)
                            sleep(cameraWarmup)
                        t2 = time()
                        imageLength = GetPicture(port, t, outputFile)
                        if imageLength:
                            ok = True
                            break
                    except CameraError as e:
                        exc = e
                    except CameraMemoryError as e:
                        # no reason to keep trying if the camera doesn't have enough RAM for the image
                        exc = e
                        break
                    finally:
                        if not leavePowerOn or not ok:
                            TurnCamera(False)
                    totalRepower += 1

        t3 = time()

        # we've exhausted all the power cycles and couldn't get a picture through, so re-raise the
        # exception related to the problem
        if exc:
            raise exc

        if ok:

            # replace "{CRC}" in the image path with the actual CRC32 of the image file
            if "{CRC}" in imagePath:
                crc = CrcFile(imagePath)
                newPath = imagePath.replace("{CRC}", hex(crc)[2:])
                rename(imagePath, newPath)
                imagePath = newPath
                fileName = fileName.replace("{CRC}", hex(crc)[2:])

            totalPictures += 1
            print("Camera imaged stored to ", imagePath, imageLength, "bytes")

            # copy the image to the transmission folder
            if txFolder:
                if not exists(txFolder):
                    command_line('FILE MKDIR "{}"'.format(txFolder))
                command_line('FILE COPY "{}" "{}"'.format(imagePath, txFolder + "/" + fileName))
                if free_space_mb < free_space_limit_archive:
                    command_line('FILE DEL "{}"'.format(imagePath))
                    raise SDCardLowOnSpace("SD card is too low on space to archive a picture, {}MB free".format(free_space_mb))

    except Exception as e:
        totalFails += 1
        raise e

    finally:
        if not t3:
            t3 = time()
        t4 = time()
        print("Total Pictures", totalPictures, "Failures", totalFails, "Repower", totalRepower, "Retries", totalRetries, "No SD Card", totalNoSD)
        print("Startup Time {:1.1f} secs".format(t2-t1))
        print("Transfer Time {:1.1f} secs".format(t3-t2))
        print("Total Time {:1.1f} secs".format(t4-t1))
        if t2 != t3:
            print("Throughput {:1.1f} bytes per sec".format(imageLength/(t3-t2)))

""" code below is copied from general_purpose.py """
gp_count = 32  # how many general purpose variable sets there are

def gp_index_valid(gp_index):
    """ returns True if the provided general purpose variable index is valid"""
    if (gp_index >= 1) and (gp_index <= gp_count):
        return True
    else:
        return False
def gp_read_label(gp_index):
    """Returns Label of the general purpose variable.
    :param gp_index: A number between 1 and gp_count
    :type gp_index: int
    :return: the Label of the specified gp
    :rtype: str """
    if gp_index_valid(gp_index):
        return setup_read("GP{} label".format(gp_index))
    else:
        raise ValueError("GP index invalid: ", gp_index)
def gp_find_index(label):
    """ Tells you the index of the general purpose with said label
    Returns zero if no such label is found
    :param label: the customer set label for the gp
    :type label: string
    :return: gp index if a match is found.  zero if no match is found
    :rtype: int """
    for gp_index in range(1, gp_count + 1):
        if label.upper() == gp_read_label(gp_index).upper():
            return gp_index
    return 0  # no gp with that label found
def gp_read_value_by_index(gp_index):
    """ Returns the customer set Value of the general purpose variable.
    :param gp_index: A number between 1 and gp_count
    :type gp_index: int
    :return: the Value of the specified p
    :rtype: float """
    if gp_index_valid(gp_index):
        return float(setup_read("GP{} value".format(gp_index)))
    else:
        raise ValueError("GP index invalid: ", gp_index)
def gp_read_value_by_label(label):
    """ Returns the Value associated with the Label of the general purpose variable.
    :param label: the user set Label of the general purpose variable
    :type label: str
    :return: the Value of the general purpose variable
    :rtype: float  """
    gp_index = gp_find_index(label)
    if gp_index_valid(gp_index):
        # we found a match.  return associated value
        gp_value = "GP{} value".format(gp_index)
        return float(setup_read(gp_value))
    else:
        raise ValueError("GP Label not found: ", label)
        return -999.9  # return this if no match is found
def gp_write_value_by_label(label, value):
    """ Writes a new Value to the general purpose variable associated with the label
    :param label: the user set Label of the general purpose variable
    :type label: str
    :param value: the new Value of the general purpose variable
    :type value: float """
    gp_index = gp_find_index(label)
    if gp_index_valid(gp_index):
        # we found a match.  return associated value
        gp_value = "GP{} value".format(gp_index)
        setup_write(gp_value, value)
    else:
        raise ValueError("GP Label not found: ", label)

def get_pacing_weighting():
    if setup_read("M4 ACTIVE") == "On":
        pacing = "FLOW"
    elif setup_read("M5 ACTIVE") == "On":
        pacing = "TIME"
    else:
        pacing = "NONE"
    return pacing

def get_flow_units():
    # Flow units - cfs or gpm usually
    flow_pacing_data_source = setup_read("M4 META INDEX")
    flow_pacing_data_source_units = setup_read("M"+str(flow_pacing_data_source )+" UNITS")
    if flow_pacing_data_source_units == 'cfs':
        flow_pacing_units = 'cf'
    elif flow_pacing_data_source_units == 'gpm':
        flow_pacing_units = 'gal'
    elif flow_pacing_data_source_units == 'm3s':
        flow_pacing_units = 'm3'
    else:
        print('Flow pacing units no present')
        pass
    return flow_pacing_data_source_units, flow_pacing_units

def get_time_pacing_increment():
    # Time Pacing Units should be minutes, just need to know how many
    time_pacing_increment = int(setup_read("M5 MEAS INTERVAL").split(":")[1]) #time is formatted '00:01:00'
    return time_pacing_increment

## Pacing Weighting
pacing_weighting = get_pacing_weighting()

## Flow Units
flow_pacing_data_source_units, flow_pacing_units = get_flow_units()

## Time Pacing Increment
time_pacing_increment = get_time_pacing_increment()

# SampleOn - start/stop sampling
sampling_on = False

# Event Number (is 0 when not during storm, gp value for event_num when in alarm)
event_num = 0

# Bottle Number (if pacing is changed bottle number will need to update)
bottle_num = float(gp_read_value_by_label("bottle_num"))
carousel_or_comp = float(gp_read_value_by_label("carousel_or_comp")) #defines if program will have 24 bottle carousel (bottle_num goes up with each aliquot)

# Bottle volume - running total of volume in bottle
vol_in_bottle = 0.0

# We count how many aliquots have been collected in each bottle
tot_aliquots = 0
aliquots_in_bottle = 0

# Sample pacing - keep a global one to check if there are any changes
#sample_pacing = gp_read_value_by_label("sample_pacing")  # or with Alarm: setup_read("M{} Alarm 1 Threshold".format(index()))
sample_pacing = float(gp_read_value_by_label("sample_pacing")) # SamplePacin is GenPurp variables

# Running total increment (time or volume)
if pacing_weighting == "FLOW":
    g_running_total = 0.0 # start at 0 and count up to pacing
elif pacing_weighting == "TIME":
    g_running_total = sample_pacing # start at time pacing and count down
else:
    g_running_total = sample_pacing

# Time sampler was triggered last.
time_last_sample = 0.0 ## good to know

# Sample log
sample_log = {'SampleEvent':{'IncrTotal':'','Bottle#':'','Aliquot#':'','SampleTime':''}}

## Get pacing
def get_sample_pacing():
    """ Returns the threshold at which the volume/time difference triggers the sampler.
    :return: sample_pacing, bottle_num
    :rtype: float, int """
    ## Get current bottle number and pacing
    global sample_pacing
    global bottle_num
    global tot_aliquots
    global aliquots_in_bottle
    global vol_in_bottle
    global flow_pacing_data_source_units
    global flow_pacing_units
    ## Flow units
    flow_pacing_data_source_units, flow_pacing_units = get_flow_units()
    # Check General Purpose Variables (which holds the desired pacing and bottle number) for changes
    # a change in  pacing may or may not also have a bottle change
    pacing_input = float(gp_read_value_by_label("sample_pacing")) # SamplePacin is GenPurp variables
    bottle_input = int(gp_read_value_by_label("bottle_num"))
    # Compare
    print("checking for pacing change...")
    # IF pacing is changed, go to bottle_and_pacing_change
    if sample_pacing != pacing_input:
        sample_pacing, bottle_num  = bottle_and_pacing_change(pacing_input,bottle_input) #returns new bottle number and pacing from change function
    # IF pacing is same, check if bottle num is changed
    else:
        print ("No pacing change...Current pacing: "+ "%.0f"%sample_pacing)
        print("")
        # Check for new bottle but without pacing change (just full bottle)
        # Bottle number is input manually so just use the manual entry
        print("checking for bottle number change...")
        if carousel_or_comp == 1: # 1 = composite; 0 = carousel
            if bottle_num != bottle_input:
                aliquots_in_bottle = 0  # reset aliquot counter to zero
                vol_in_bottle = 0
                print("New Bottle!")
                print("Previous bottle number: " + '%.0f' % bottle_num)
                bottle_num = bottle_input  # update global bottle_num from BottleNum 3 Offset
                print("New bottle number: " + '%.0f' % bottle_input)
                print("................Aliquots in bottle: " + "%.0f" % aliquots_in_bottle)
                print("................Volume in bottle: " + "%.0f" % vol_in_bottle + "mL")
            else:
                print("No bottle change...Current Bottle number: " + '%.0f' % bottle_num)
                print("................Total Aliquots: " + "%.0f" % tot_aliquots)
                print("................Aliquots in bottle: " + "%.0f" % aliquots_in_bottle)
                print("................Volume in bottle: " + "%.0f" % vol_in_bottle + "mL")
                # bottle number should always be whatever is in the GP variable
    return sample_pacing, bottle_num # return new/current pacing volume and new/current bottle number to main function

def bottle_and_pacing_change(pacing_input,bottle_input):
    """ Updates the bottle number (composite) and resets aliquot counts etc
    :return: bottle_num, sample_pacing"""
    global sample_pacing
    global bottle_num
    global tot_aliquots
    global aliquots_in_bottle
    global vol_in_bottle
    global flow_pacing_data_source_units
    global flow_pacing_units
    # Update global values
    sample_pacing = float(pacing_input) # update global sample_pacing from GP variable
    bottle_num = bottle_input  # update global bottle_num from BottleNum M2 Offset
    ## Reset aliquot count and volume (may only be dumping out some volume and changing pacing but reset anyway)
    aliquots_in_bottle = 0.
    vol_in_bottle = 0.0
    # Print new parameters
    print("Pacing changed! New Pacing: " + "%.0f"%sample_pacing + flow_pacing_units) # should be updated above
    print("................New Bottle number: "+ "%.0f" % bottle_num) # should be updated above
    print("................Total Aliquots: " + "%.0f" % tot_aliquots)
    print("................Aliquots in bottle: " + "%.0f" %aliquots_in_bottle)
    print("................Volume in bottle: " + "%.0f" % vol_in_bottle +"mL")
    print("")
    # write a log entry
    event_label = " NewPacing: "+"%.0f"%sample_pacing+"  NewBottle: "+ "%.0f" % bottle_num
    reading = Reading(label=event_label, time=utime.time(),etype='E', value=bottle_num,right_digits=0)
    reading.write_log()
    return sample_pacing, bottle_num


def trigger_sampler():
    """ Call to attempt to trigger the sampler.
    Certain conditions may prevent the triggering.
    :return: True if sampler was triggered."""
    global bottle_capacity
    global bottle_num
    global tot_aliquots
    global aliquot_vol_mL
    global aliquots_in_bottle
    global vol_in_bottle
    global time_last_sample
    ## Set trigger to True
    trigger = True

    # DO NOT SAMPLE conditions
    # if aliquots_in_bottle >= bottle_capacity:
    #     trigger = False  # out of capacity - won't overfill bottle
    # elif is_being_tested():
    #     trigger = False  # script is being tested
    # elif setup_read("Recording").upper() == "OFF":
    #     trigger = False  # if recording is off, do not sample

    # If conditions are met, then trigger the sampler
    if trigger == True:
        print ('Sampler Triggered')
        # increment the number of bottles used
        if carousel_or_comp == 0:
            tot_aliquots += 1
            bottle_num += 1
            gp_write_value_by_label("bottle_num",bottle_num)
        elif carousel_or_comp ==1:
            tot_aliquots += 1
            aliquots_in_bottle += 1
            vol_in_bottle = vol_in_bottle + aliquot_vol_mL
        # update the time of the last trigger
        time_last_sample = utime.time()
        # trigger sampler by pulsing output for 0.5 seconds
        power_control('SW1', True)
        utime.sleep(0.5)
        power_control('SW1', False)
        # write a log entry
        t = utime.localtime(time_scheduled())
        day, minute = str(t[2]), str(t[4])
        if len(day) == 1:
            day = '0' + day
        if len(minute) == 1:
            minute = '0' + minute
        sample_time = str(t[1]) + '/' + day + '/' + str(t[0]) + ' ' + str(t[3]) + ':' + minute
        reading = Reading(label="Triggered Sampler", time=time_scheduled(),
                          etype='E', value=tot_aliquots,
                          right_digits=0, quality='G')  # 'E' = event, 'M' = measurement, 'D' = debug
        reading.write_log()
        ## Write display log entries
        global sample_log
        global bottle_num
        global tot_aliquots
        global aliquots_in_bottle
        global sample_pacing

        pacing_units = setup_read("M2 Units")
        sample_log[sample_time] = {'Pacing': '%.0f' % sample_pacing+pacing_units, 'Bottle#': str(int(bottle_num)),
                                   'Aliquot#': str(int(aliquots_in_bottle)), 'SampleTime': sample_time}
        return True
    # If conditions are NOT met, then DONOT trigger the sampler
    else:
        return False  # Sampler was NOT triggered.

@MEASUREMENT
def HvF_table(stage_in):
    """
    Given stage reading, this script will find the closest stage/discharge pair in
    rating table that is less than the input stage reading, and then perform a linear
    interpolation on the discharge values on either side of the stage reading to
    determine the discharge value at the current stage. For example, a stage value
    of 4" would output 32.0 CFS discharge because 4 is between (3, 22) and (5, 42).

    User will need to define the values for the rating table based on their application.
    The example below assumes an input stage value in inches and outputs discharge in cubic feet
    per second (CFS).

    To configure this script, attach this function to a Stage measurement
    or second meta referring to stage and make sure your stage units match your rating
    table stage values.
    """
    # stage, flow pairs
    STAGETBL = ((0.0, 0.31),
(0.3, 0.46),
(0.5, 0.78),
(0.8, 1.07),
(1.0, 1.59),
(1.3, 2.05),
(1.5, 2.59),
(1.8, 3.61),
(2.0, 4.33),
(2.3, 5.74),
(2.5, 6.98),
(2.8, 9.05),
(3.0, 10.56),
(3.3, 13.01),
(3.5, 14.87),
(3.8, 17.90),
(4.0, 20.04),
(4.5, 27.05),
(5.0, 33.51),
(5.5, 40.52),
(6.0, 48.05),
(6.5, 56.08),
(7.0, 64.61),
(7.5, 73.62),
(8.0, 83.09),
(8.5, 93.02),
(9.0, 103.39),
(9.5, 114.20),
(10.0, 125.44),
(10.5, 137.10),
(11.0, 149.17),
(11.5, 161.66),
(12.0, 174.54),
(12.5, 187.82),
(13.0, 201.50),
(13.5, 215.57),
(14.0, 230.01),
(14.5, 244.84),
(15.0, 260.03),
(15.5, 275.60),
(16.0, 291.52),
(16.5, 307.81),
(17.0, 324.45),
(17.5, 341.45),
(18.0, 358.80),
(18.5, 376.49),
(19.0, 394.53),
(19.5, 409.20),
(20.0, 427.85),
(20.5, 446.83),
(21.0, 466.15),
(21.5, 485.80),
(22.0, 505.78),
(22.5, 526.08),
(23.0, 546.71),
(23.5, 567.66),
(24.0, 588.93),
(24.5, 610.54),
(25.0, 632.47),
(25.5, 654.72),
(26.5, 700.15),
(27.5, 746.81),
(28.5, 794.70),
(29.5, 843.80),
(30.5, 894.10),
(31.5, 945.59),
(32.5, 998.25),
(33.5, 1052.09),
(34.5, 1107.08),
(35.5, 1163.23),
(36.5, 1220.54),
(37.5, 1279.13),
(38.5, 1338.84),
(39.5, 1399.67),
(40.5, 1461.62),
(41.5, 1524.66),
(42.5, 1588.03),
(43.5, 1648.08),
(44.5, 1709.25),
(45.5, 1771.55),
(46.5, 1834.99),
(47.5, 1899.56),
(48.5, 1965.26),
(49.5, 2032.12),
(50.5, 2100.02),
(51.5, 2174.38),
(52.5, 2249.88),
(53.5, 2326.53),
(54.5, 2404.33),
(55.5, 2483.27),
(56.5, 2570.09),
(57.5, 2658.86),
(58.5, 2748.83),
(59.5, 2840.00),
(60.5, 2932.35),
(61.5, 3025.88))

    # Test for out of bounds stage values
    if stage_in < STAGETBL[0][0]:  # if measured stage is BELOW the FIRST stage value in the FIRST stage,flow pair
        flow = STAGETBL[0][0] # Use lowest flow value in the stage,flow pairs
    elif stage_in > STAGETBL[-1][0]:  # if measured stage is ABOVE the LAST stage value in the LAST stage,flow pair
        flow = STAGETBL[-1][1] # Use last flow value in the stage,flow pairs
    else:
        # use for loop to walk through flow (discharge) table
        for flow_match in range(len(STAGETBL)):
            if stage_in < STAGETBL[flow_match][0]:
                break
        flow_match -= 1  # first pair
        # compute linear interpolation
        a_flow1 = STAGETBL[flow_match][1]
        b_diff_stage = stage_in - STAGETBL[flow_match][0]
        c_stage2 = STAGETBL[flow_match + 1][0]
        d_stage1 = STAGETBL[flow_match][0]
        e_flow2 = STAGETBL[flow_match + 1][1]
        flow = a_flow1 + (b_diff_stage / (c_stage2 - d_stage1)) * (e_flow2 - a_flow1)
    print ("")
    print("Stage: {}".format("%.2f" % stage_in) + ' in')
    print("Flow: {}".format("%.3f"%flow))
    print("")
    return flow

@MEASUREMENT
def AV_PipeFLow_cfs(vel_fps):
    """ Takes velocity as input; meta index should correspond to the velocity measurement.
    returns the flow based on the pipe diameter in the general purpose values
    :param vel_fps:
    :return: flow_gpm or flow_cfs depending on units """

    pipe_diam = gp_read_value_by_label("pipe_diameter_in")
    stage_in = measure("Level_PT", READING_LAST).value
    radius = pipe_diam/2.
    angle = 2. * math.acos((radius - stage_in) / radius)
    area_sq_in = (radius ** 2 * (angle - math.sin(angle))) / 2
    area_sq_ft = area_sq_in * 0.00694444
    flow_cfs = area_sq_ft * vel_fps
    return flow_cfs

@MEASUREMENT
def AV_PipeFLow_gpm(vel_fps):
    """ Takes velocity as input; meta index should correspond to the velocity measurement.
    returns the flow based on the pipe diameter in the general purpose values
    :param vel_fps:
    :return: flow_gpm or flow_cfs depending on units """

    pipe_diam = gp_read_value_by_label("pipe_diameter_in")
    stage_in = measure("Level_PT", READING_LAST).value
    radius = pipe_diam/2.
    angle = 2. * math.acos((radius - stage_in) / radius)
    area_sq_in = (radius ** 2 * (angle - math.sin(angle))) / 2
    area_sq_ft = area_sq_in * 0.00694444
    flow_cfs = area_sq_ft * vel_fps
    flow_gpm = flow_cfs * 448.8325660485
    return flow_gpm


@MEASUREMENT
def flow_weighted_sampling(flow):
    """ This function needs to be associated with the total volume measurement.
    It will compute the total volume based on the current flow rate and past volume.
    The script will trigger the sampler if appropriate.
    :param flow: current flow rate
    :return: the current volume reading"""
    global sampling_on
    global sample_pacing
    global g_running_total
    global bottle_capacity
    global aliquot_vol_mL
    global bottle_num
    global tot_aliquots
    global aliquots_in_bottle
    global pacing_weighting
    ## Check if sampling is on
    gp_sampling_on = gp_read_value_by_label("sampling_on") ## Read value in GP
    if gp_sampling_on == 1:
        sampling_on =  True
    elif gp_sampling_on == 0:
        sampling_on = False

    # Aliquot volume
    aliquot_vol_mL = gp_read_value_by_label("aliquot_vol_mL")
    # The container can hold a maximum number of aliquots
    bottle_size_L = gp_read_value_by_label("bottle_size_L")
    # aliquots; 19L / 250mL = 76
    bottle_capacity = bottle_size_L / (aliquot_vol_mL/1000)

    ## Check if program is flow weighted
    pacing_weighting = get_pacing_weighting()
    ## FLow Units
    flow_pacing_data_source_units, flow_pacing_units = get_flow_units()

    if sampling_on == False and  pacing_weighting == "FLOW":
        print ('Sampling is OFF, Sample pacing is FLOW weighted')
        print('Flow:' + "%.2f" % flow + flow_pacing_data_source_units)
        print ("Current bottle number: "+"%.0f"%bottle_num)
        print ("Current pacing: "+"%.0f"%sample_pacing + flow_pacing_units)
        print ("Total aliquots: "+"%.0f"% tot_aliquots)
        print("Aliquots in bottle: " + "%.0f"%aliquots_in_bottle)
        print("Bottle capacity: " + "%.0f"%bottle_capacity)

    elif sampling_on == True and  pacing_weighting == "FLOW":
        print ('sampling is ON, Sample pacing is FLOW weighted')
        # Measurement is at 1 minute, flow in cfs * 60 sec = cfm
        # flow = measure("Flow_cfs", READING_LAST).value  # what is the current flow rate?
        if flow_pacing_data_source_units == 'cfs' or flow_pacing_data_source_units == 'm3s':
            incremental_vol = flow * 60. # cfs x 60 sec = cf per minute
        elif flow_pacing_data_source_units == 'gpm':
            incremental_vol = flow

        # Add to running total volume
        g_running_total = g_running_total + incremental_vol # cf per minute, at minute intervals just total up

        print('Flow:' + "%.3f" % flow + flow_pacing_data_source_units, '  IncrVol:' + "%.2f" % incremental_vol + flow_pacing_units,
              '  RunningTotalVol:' + "%.2f" % g_running_total + flow_pacing_units)

        # Pacing - check pacing, if it's different this function will update everything
        sample_pacing, bottle_num = get_sample_pacing()

        # if the running total volume is higher than pacing volume, trigger sampler
        if g_running_total >= sample_pacing:
            print('Sample triggered by flow')
            if trigger_sampler():
                # sampler was triggered
                # Write a log entry indicating why sampler was triggered.
                reading = Reading(label="VolumeTrig", time=time_scheduled(),
                                  etype='E', value=g_running_total, quality='G')
                reading.write_log()

                # get remaining volume and keep in running total
                g_running_total = g_running_total - sample_pacing
                ## check to see if sampling is going too fast


        # add diagnostic info to the script status
        print ("Current bottle number: "+"%.0f"%bottle_num)
        print ("Current pacing: "+"%.0f"%sample_pacing)
        print ("Total aliquots: "+"%.0f"%tot_aliquots)
        print("Aliquots in bottle: " + "%.0f"%aliquots_in_bottle)
        print("Bottle capacity: " + "%.0f"%bottle_capacity)

    if time_last_sample:
        print("Last trigger: {}".format(ascii_time(time_last_sample)))
    else:
        print("Not triggered since bootup")

    # Display log of samples taken
    global sample_log
    print ('Sample Log: ')
    for k in sorted(sample_log):
        print(sample_log[k])
    return g_running_total  # return the total volume (before clearing it)

@MEASUREMENT
def time_weighted_sampling(input):
    """ This function runs a time-weighted sampling program
    The script will trigger the sampler if appropriate.
    :param
    :return: time to next sample"""
    global sampling_on
    global pacing_weighting
    global sample_pacing
    global g_running_total
    global bottle_capacity
    global aliquot_vol_mL
    global bottle_num
    global tot_aliquots
    global aliquots_in_bottle
    global vol_in_bottle

    ## Check if sampling is on
    gp_sampling_on = gp_read_value_by_label("sampling_on") ## Read value in GP
    if gp_sampling_on == 1:
        sampling_on =  True
    elif gp_sampling_on == 0:
        sampling_on = False

    # Aliquot volume
    aliquot_vol_mL = gp_read_value_by_label("aliquot_vol_mL")
    # The container can hold a maximum number of aliquots
    bottle_size_L = gp_read_value_by_label("bottle_size_L")
    # aliquots; 19L / 250mL = 76
    bottle_capacity = bottle_size_L / (aliquot_vol_mL/1000)

    ## Check if program is flow weighted
    pacing_weighting = get_pacing_weighting()
    sample_pacing = float(gp_read_value_by_label("sample_pacing")) # SamplePacin is GenPurp variables

    if sampling_on == False and  pacing_weighting == "TIME":
        print ('Sampling is OFF, Sample pacing is TIME weighted')
        print ("Current bottle number: "+"%.0f"%bottle_num)
        print ("Current pacing: "+str(sample_pacing) + "minutes")
        print ("Total aliquots: "+"%.0f"%tot_aliquots)
        print("Aliquots in bottle: " + "%.0f"%aliquots_in_bottle)
        print("Bottle capacity: " + "%.0f"%bottle_capacity)

    elif sampling_on == True and  pacing_weighting == "TIME":
        print ('sampling is ON, Sample pacing is TIME weighted')
        # Measurement is some # of minutes - time_pacing_increment==meas_interval
        time_pacing_increment = get_time_pacing_increment()

        # Subtract the time_pacing_increment from the total time pacing running_total
        g_running_total = g_running_total - int(time_pacing_increment)  #

        print('  Time Pacing Increment: ' + str(time_pacing_increment) + "minutes",
              '  Time to Next Sample:' + "%.0f" % g_running_total + "minutes")

        # if the running total of minutes is 0 (or less) trigger sampler
        print (type(sample_pacing))
        print(sample_pacing)
        print (type(g_running_total))
        print (g_running_total)
        ## running_total is counting down, when it gets to 0 trigger a sample
        ## and reset running_total to the sample_pacing for the next countdown
        if g_running_total <= 0:
            print ('Countdown timer below sample_pacing')
            if trigger_sampler():
                print ('Sampler triggered by time pacing')
                # sampler was triggered
                # Write a log entry indicating why sampler was triggered.
                reading = Reading(label="TimeTrig", time=time_scheduled(),
                                  etype='E', value=g_running_total, quality='G')
                reading.write_log()

                # reset Time pacing to sample_pacing
                g_running_total = sample_pacing #reset to Sample Pacing eg 30min

        # add diagnostic info to the script status
        print ("Current bottle number: "+"%.0f"%bottle_num)
        print ("Current pacing: "+"%.0f"%sample_pacing)
        print ("Total aliquots: "+"%.0f"%tot_aliquots)
        print("Aliquots in bottle: " + "%.0f"%aliquots_in_bottle)
        print("Bottle capacity: " + "%.0f"%bottle_capacity)
    else:
        print('sample not triggered yet')

    # Display log of samples taken
    global sample_log
    print ('Sample Log: ')
    for k in sorted(sample_log):
        print(sample_log[k])
    return g_running_total  # return the countdown timer

@MEASUREMENT
def display_sampling_on(input):
    global sampling_on
    sampling_on = int(gp_read_value_by_label("sampling_on"))
    if sampling_on == 0:
        sample_text = 'OFF'
    elif sampling_on == 1:
        sample_text = 'ON'
    else:
        pass
    print('Sampling is '+sample_text)
    return sampling_on

@MEASUREMENT
def display_sample_pacing(input):
    global sample_pacing
    sample_pacing = float(gp_read_value_by_label("sample_pacing"))
    print ('Sample Pacing: '+str(sample_pacing))
    return sample_pacing

@MEASUREMENT
def display_event_num(input):
    global event_num
    print ('Event number: ' +str(event_num))
    return event_num

@MEASUREMENT
def display_bottle_num(input):
    global bottle_num
    bottle_num = float(gp_read_value_by_label("bottle_num"))
    print ('Bottle number: '+str(bottle_num))
    return bottle_num

@MEASUREMENT
def display_tot_aliquots(input):
    global tot_aliquots
    print ("Total aliquots in bott: "+str(tot_aliquots))
    return tot_aliquots

@MEASUREMENT
def number_of_aliquots(input):
    global aliquots_in_bottle
    print ('Number of aliquots in bottle: '+str(aliquots_in_bottle))
    return aliquots_in_bottle

@MEASUREMENT
def Free_Space_MB(data):
    # allows the user to measure/log the free space on the SDHC card in megabytes
    if not ismount("/sd"):
        raise SDCardNotMountedError("SD card must be inserted to take pictures")
    vfs = statvfs("/sd")
    if not ismount("/sd"):
        raise SDCardNotMountedError("SD card must be inserted to take pictures")
    free_space_mb = vfs[3] * vfs[0] / 1024 / 1024
    return free_space_mb

@TASK
def turn_on_sampling():
    ## Reset all params for start of event
    global sample_pacing
    global event_num
    global g_running_total
    global bottle_num
    global tot_aliquots
    global aliquots_in_bottle
    global vol_in_bottle
    ## Check if station is already samplign (sampling_on would be == 1)
    already_sampling = gp_read_value_by_label("sampling_on")
    ## If sampling_on=0 (sampling not started yet)
    if already_sampling == 0:
        print("Start sampling!")
        for i in [i for i in range(1,31,1)]: #0-30 =M1-M31
            setup_write("!M"+str(i)+" meas interval", "00:01:00")

        # Start sampling when level triggered
        gp_write_value_by_label("sampling_on", 1)  # 1=True
        
        ## turn on Event Number logging
        event_num = int(gp_read_value_by_label("event_num"))
        setup_write("!M31 log reading", "On") #start logging event number, Event Number is hardcoded to M31
        ## get pacing
        sample_pacing = float(gp_read_value_by_label("sample_pacing")) # SamplePacin is GenPurp variables
        ## Reset parameters for event
        bottle_num = int(gp_read_value_by_label("bottle_num"))
        tot_aliquots = 0
        aliquots_in_bottle = 0
        vol_in_bottle = 0
        ## Check if program is flow weighted
        pacing_weighting = get_pacing_weighting()
        # Running total increment (time or volume)
        if pacing_weighting == "FLOW":
            g_running_total = 0.0  # start at 0 and count up to pacing
        if pacing_weighting == "TIME":
            ## Trigger a sample immediately when sampling is started (only in time-weighted program)
            trigger_sampler()
            g_running_total = sample_pacing  # start at time pacing and count down
    ## If sampling_on=1 (sampling alread started)
    elif already_sampling==1:
        print("Alarm triggered but sampling was already started. No action")
    else:
        pass
    return

@TASK
def turn_off_sampling():
    print ("Stopped sampling")
    # Stop sampling when level triggered
    gp_write_value_by_label("sampling_on", 0)  # 0=False
    setup_write("!M31 log reading", "Off") #start logging event number
    ## Set data collection back to 5 min
    for i in [i for i in range(1, 31, 1)]: #0-30 =M1-M31
        setup_write("!M" + str(i) + " meas interval", "00:05:00")

@TASK
def reset_sampling_params():
    print("Manually reset sampling parameters!")
    ## Reset all params for start of event
    global sampling_on
    global sample_pacing
    global event_num
    global g_running_total
    global bottle_num
    global tot_aliquots
    global aliquots_in_bottle
    global vol_in_bottle
    ##
    sampling_on = int(gp_read_value_by_label("sampling_on"))
    event_num = int(gp_read_value_by_label("event_num"))
    ## get pacing
    sample_pacing = float(gp_read_value_by_label("sample_pacing")) # SamplePacin is GenPurp variables
    bottle_num = int(gp_read_value_by_label("bottle_num"))
    ## Check if program is flow weighted
    pacing_weighting = get_pacing_weighting()
    # Running total increment (time or volume)
    if pacing_weighting == "FLOW":
        g_running_total = 0.0  # start at 0 and count up to pacing
    if pacing_weighting == "TIME":
        g_running_total = sample_pacing  # start at time pacing and count down

    tot_aliquots = 0
    aliquots_in_bottle = 0
    vol_in_bottle = 0

    # Sample log
    sample_log = {'SampleEvent': {'IncrTotal': '', 'Bottle#': '', 'Aliquot#': '', 'SampleTime': ''}}
    return

@TASK 
def reset_bottle_carousel():
    global bottle_num
    bottle_num = 1
    gp_write_value_by_label("bottle_num",1)
    return bottle_num

@TASK
def trigger_sampler_manually():
    """ Function triggers SW12 for two seconds in order to trigger a sampler"""

    # trigger sampler by pulsing output for 0.5 seconds
    power_control('SW1', True)
    utime.sleep(0.5)
    power_control('SW1', False)
    # write a log entry
    t = utime.localtime(time_scheduled())
    day, minute = str(t[2]), str(t[4])
    if len(day) == 1:
        day = '0' + day
    if len(minute) == 1:
        minute = '0' + minute
    sample_time = str(t[1]) + '/' + day + '/' + str(t[0]) + ' ' + str(t[3]) + ':' + minute
    reading = Reading(label="Trigger Manually", time=time_scheduled(),
                      etype='E', value=1,right_digits=0, quality='G')  # 'E' = event, 'M' = measurement, 'D' = debug
    reading.write_log()
    print ('Sampler triggered manually ' + sample_time)
    return True

@TASK
def Take_1920x1080_Auto():
    if is_being_tested():
        return
    # try 1920x1080 with compression 3 first, but if that fails due to not enough RAM in the camera
    # retry at 1920x1080 with compression level 0 to 5; 1600x900 with 0 to 5, and 1280x720 with 0 to 3:
    retry_settings = [("1920x1080", _) for _ in range(0, 6)] + \
                     [("1600x900",  _) for _ in range(0, 6)] + \
                     [("1280x720",  _) for _ in range(0, 6)]
    TakePicture("1920x1080", 3, retry_settings)

@TASK
def Take_1280x720_MostDetail():
    if is_being_tested():
        return
    TakePicture("1280x720", 0, [])

@TASK
def Take_1280x720_MediumDetail():
    if is_being_tested():
        return
    TakePicture("1280x720", 2, [])

@TASK
def Take_1280x720_LeastDetail():
    if is_being_tested():
        return
    TakePicture("1280x720", 5, [])

@TASK
def Take_480x270():
    if is_being_tested():
        return
    TakePicture("480x270", 3, [])

