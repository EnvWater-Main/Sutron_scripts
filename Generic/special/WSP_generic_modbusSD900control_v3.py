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
    # Time Pacing Units should be minutes, just need to know how many so you konw how many minutes to count down by (subtract)
    time_pacing_increment = int(setup_read("M5 MEAS INTERVAL").split(":")[1]) #time is formatted '00:01:00'
    return time_pacing_increment

## Pacing Weighting
pacing_weighting = get_pacing_weighting()

## Flow Units
flow_pacing_data_source_units, flow_pacing_units = get_flow_units()

## Time Pacing Increment
time_pacing_increment = get_time_pacing_increment() ## how many minutes between measurements is how many minutes to subtract/count down

# SampleOn - start/stop sampling
sampling_on = False

# Event Number (not recorded when Sutron not In Alarm)
event_num = int(gp_read_value_by_label("event_num")) # this is entered manually prior to storm

#defines if program will have 24 bottle carousel (bottle_num goes up with each aliquot)
carousel_or_comp = float(gp_read_value_by_label("carousel_or_comp")) ## 0 = carousel, 1 = composite

# Bottle Number (if composite, bottle number is changed manually, if carousel bottle number encrements up with aliquot num)
bottle_num = float(gp_read_value_by_label("bottle_num"))

# We count how many aliquots have been collected in each bottle
tot_aliquots = 0
aliquots_in_bottle = 0
# Bottle volume - running total of volume in bottle
aliquot_vol = 0
vol_in_bottle = 0.0

# Sample pacing - keep a global one to check if there are any changes
sample_pacing = float(gp_read_value_by_label("sample_pacing")) # SamplePacin is GenPurp variables

# Running total increment (time minutes or volume in flow units)
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

def grab_sample_modbus():
    """
    Using a SD900 sampler
    only can use over RS232, baud rate is 115200
    RTU mode: # of data bits is 8
    ASCII mode: # of data bits is 7
    parity fixed at none. stop bits is 1 or 2
    """
    grab_aok = False
    result_aok = False
    modbus_address = 2 #first byte below
    function_code = 10 #hex for 16-write registers
    grab_sample = b'\x02\x10\x26\xCF\x00\x02\x04\x00\x64\x80\x07\x63\x47' ## 00 64 is hex for 100mL
    #grab_sample = b'\x02\x10\x26\xCF\x00\x02\x04\x00\xFA\x80\x07\xA9\x02' ## 00 FA is hex for 250mL
    grab_sample = b'\x02\x10\x26\xCF\x00\x02\x04\x01\xF4\x80\x07\x62\x96' ## 01 F4 is hex for 500mL
    #grab_sample = b'\x02\x10\x26\xCF\x00\x02\x04\x03\xE8\x80\x07\x63\x47' ## 00 64 is hex for 1000mL
    grab_sample = b'\x02\x10\x26\xCF\x00\x02\x04\x07\xD0\x80\x07\xC2\x17' ## 07 DO is hex for 2000mL
    grab_sample = b'\x02\x10\x26\xCF\x00\x02\x04\x0F\xA0\x80\x07\x21\xAE' ## 07 DO is hex for 4000mL

    with serial.Serial("RS232",115200, stopbits=1) as sampler:
        sampler.port = "RS232" #i think this is redundant by why not
        sampler.timeout = 1
        sampler.inter_byte_timeout = 0.2 #not sure but going with what was programmed for AV900, maybe something to do with baudrate?
        sampler.delay_before_tx = .5  # if you only get intermittent data, increase this value
        max_retries = 3
        retries = 0
        #trigger sampler
        for i in range(max_retries): #retry
            if grab_aok == False or max_retries < retries:
                sampler.write(grab_sample)
                buff = sampler.read(8) # 8 or 16? the response message is 021026CF00027A8C (length=16)
                sampler.flush()
                if len(buff) >= 8 and buff[0] == 2: # our only verification is that first return byte matches modbus address
                    grab_aok = True
                    print('Attempt: '+str(i+1))
                    print ('grab aok')
                    print(buff)
                    print('Length buff: '+str(len(buff)))
                    print ('Buff[0]: '+str(buff[0]))
                    print ('  ')
                    #read result register-does not say if sample was successfully collected, just that command successfully executed
                    utime.sleep(1)
                    result_code_max_retries = 5
                    result_code_tries = 1
                    result_register = b'\x02\x03\x26\xCE\x00\x01\xEE\x8E'
                    for i in range(result_code_max_retries):
                        print ('result code try: '+str(result_code_tries))
                        sampler.write(result_register)
                        buff = sampler.read(8) # 8 or 16? the response message is 021026CF00027A8C (length=16)
                        sampler.flush()
                        if len(buff) >= 7 and buff[0] == 2: # our only verification is that first return byte matches modbus address
                            result_aok = True
                            result_code = buff[3]
                            print (buff)
                            print('Length buff: '+str(len(buff)))
                            print ('buff[0]: '+str(buff[0]))
                            print("result code buff[4]: "+str(buff[4]))
                            print ('  ')
                            if result_code == 2 or result_code ==5 or result_code_tries>result_code_max_retries:
                                break ## stop if code is different than 2 or 5
                            else:
                                pass                           
                        else:
                            print ('unsuccessful read')
                            print (buff)
                        utime.sleep(2)
                        result_code_tries+=1    
                    break
                else:
                    print('Attempt: '+str(i+1))
                    print ('grab NOT aok')
                    print(buff)
                    print('Length buff: '+str(len(buff)))
                    print ('  ')
                    ## WAit 2 sec til retry
                    utime.sleep(2)
                retries+=1
            
    if not grab_aok:
        raise ValueError("Could not trigger sampler")
    if not result_aok:
        raise ValueError("Could not get result")
    if result_aok==True:
        result = 1
    elif result_aok==False:
        result = 0
    return result

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
        if carousel_or_comp == 0: ## 0 = carousel, 1 = composite
            print("Increment aliquot and bottle by 1")
            tot_aliquots += 1
            bottle_num += 1
            gp_write_value_by_label("bottle_num",bottle_num)
        elif carousel_or_comp ==1: ## 0 = carousel, 1 = composite
            tot_aliquots += 1
            aliquots_in_bottle += 1
            vol_in_bottle = vol_in_bottle + aliquot_vol_mL
        # update the time of the last trigger
        time_last_sample = utime.time()
        # trigger sampler by modbus instruction
        result = grab_sample_modbus() ## this will run the grab_sample_modbus definition and return if the result was good (=1) or bad (=0)
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

def differential_reading(meas_label, period_sec, allow_negative):
    """
    Computes the difference between the most recent reading of the specified measurement,
    and an older reading of the same measurement.
    Routine reads the log looking for the older reading.

    :param meas_label: the label of the measurement in question
    :type meas_label: str
    :param period_sec: how long ago the old reading was made in seconds
    :type period_sec: int
    :param allow_negative: should a negative difference be allowed?  set to False for rain accumulation
    :type allow_negative: bool
    :return: the difference between the two readings
    :rtype: float
    """

    # current reading
    current = measure(meas_as_index(meas_label))

    # compute previous time based on current reading and period_sec
    time_old = current.time - period_sec

    # Read the log, looking for the measurement starting with the newest
    # and going backwards until we find the oldest reading within the time bounds.
    oldest_reading = Reading(value=0.0)
    try:
        logthing = Log(oldest=time_old,
                       newest=current.time,
                       match=meas_label,
                       pos=LOG_NEWEST)

        for itero in logthing:
            oldest_reading = itero

    except LogAccessError:
        print('No logged readings found.  Normal until recording starts.')
        return 0.0

    # if both readings are valid, compute the difference
    if (current.quality == 'G') and (oldest_reading.quality == 'G'):
        result = current.value - oldest_reading.value

        if (result < 0.0) and (not allow_negative):
            # If the difference is negative, the measurement has been reset.
            print('Negative change not allowed')
            return current.value
        else:
            print('Change computed successfully')
            return result

    else:
        print('Readings were not valid')
        return 0.0


@MEASUREMENT
def rain_5_min(inval):
    """
    Computes the rainfall during the last 5 minutes.
        Another measurement labeled Rain_950 must be recording precip accumulation.
    """
    return differential_reading("Rain_950", 300, False)  # 300 sec = 1 minute.  False means no negative readings.

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
    STAGETBL = ((46.0, 0.00),
(46.3, 0.00),
(46.5, 0.02),
(46.8, 0.03),
(47.0, 0.03),
(47.3, 0.03),
(47.5, 0.03),
(47.8, 0.03),
(48.0, 0.03),
(48.3, 0.03),
(48.5, 0.03),
(48.8, 0.03),
(49.0, 0.05),
(49.3, 0.10),
(49.5, 0.15),
(49.8, 0.23),
(50.0, 0.35),
(50.3, 0.41),
(50.5, 0.54),
(50.8, 0.74),
(51.0, 0.96),
(51.3, 1.20),
(51.5, 1.49),
(51.8, 1.50),
(52.0, 1.74),
(52.3, 2.07),
(52.5, 2.19),
(52.8, 2.60),
(53.0, 2.78),
(53.3, 3.20),
(53.5, 3.64),
(53.8, 4.18),
(54.0, 4.41),
(54.3, 4.97),
(54.5, 5.63),
(54.8, 6.33),
(55.0, 7.06),
(55.3, 7.82),
(55.5, 8.61),
(55.8, 9.43),
(56.0, 10.28),
(56.3, 10.45),
(56.5, 11.29),
(56.8, 12.16),
(57.0, 12.31),
(57.3, 13.17),
(57.5, 14.06),
(57.8, 14.97),
(58.0, 15.91),
(58.3, 16.86),
(58.5, 17.84),
(58.8, 18.83),
(59.0, 19.85),
(59.3, 21.01),
(59.5, 22.21),
(59.8, 23.71),
(60.0, 25.36),
(60.3, 27.23),
(60.5, 29.15),
(60.8, 31.27),
(61.0, 33.61),
(61.3, 35.12),
(61.5, 36.84),
(61.8, 38.58),
(62.0, 40.36),
(62.3, 42.16),
(62.5, 43.98),
(62.8, 45.83),
(63.0, 47.71),
(63.3, 49.61),
(63.5, 51.54),
(63.8, 53.50),
(64.0, 55.48),
(64.3, 57.48),
(64.5, 59.51),
(64.8, 61.56),
(65.0, 63.64),
(65.3, 65.75),
(65.5, 67.87),
(65.8, 70.03),
(66.0, 72.20),
(66.3, 74.40),
(66.5, 76.63),
(66.8, 78.88),
(67.0, 80.76),
(67.3, 83.15),
(67.5, 85.57),
(67.8, 88.01),
(68.0, 90.48),
(68.3, 92.98),
(68.5, 95.50),
(68.8, 98.04),
(69.0, 100.61),
(69.3, 103.20),
(69.5, 105.82),
(69.8, 108.46),
(70.0, 111.13),
(70.3, 113.82),
(70.5, 116.53),
(70.8, 119.27),
(71.0, 122.02),
(71.3, 124.81),
(71.5, 127.61),
(71.8, 130.44),
(72.0, 133.29),
(72.3, 136.16),
(72.5, 139.05),
(72.8, 141.97),
(73.0, 144.90),
(73.3, 147.86),
(73.5, 150.84),
(73.8, 153.84),
(74.0, 156.87),
(74.3, 159.91),
(74.5, 162.98),
(74.8, 166.06),
(75.0, 169.17),
(75.3, 172.29),
(75.5, 175.44),
(75.8, 178.61),
(76.0, 181.80),
(76.3, 185.00),
(76.5, 188.23),
(76.8, 191.48),
(77.0, 194.74),
(77.3, 198.03),
(77.5, 201.33),
(77.8, 204.66),
(78.0, 208.00),
(78.3, 211.37),
(78.5, 214.75),
(78.8, 218.15),
(79.0, 221.57),
(79.3, 225.00),
(79.5, 228.46),
(79.8, 231.93),
(80.0, 235.43),
(80.3, 238.94),
(80.5, 242.47),
(80.8, 246.01),
(81.0, 249.58),
(81.3, 253.16),
(81.5, 256.76),
(81.8, 260.38),
(82.0, 264.01),
(82.3, 267.66),
(82.5, 271.33),
(82.8, 275.02),
(83.0, 278.72),
(83.3, 282.44),
(83.5, 286.18),
(83.8, 289.93),
(84.0, 293.71),
(84.3, 297.49),
(84.5, 301.30),
(84.8, 305.12),
(85.0, 308.95),
(85.3, 312.81),
(85.5, 316.67),
(85.8, 320.56),
(86.0, 324.46),
(86.3, 328.38),
(86.5, 332.31),
(86.8, 336.26),
(87.0, 340.22),
(87.3, 344.20),
(87.5, 348.20),
(87.8, 352.21),
(88.0, 356.23),
(88.3, 360.28),
(88.5, 364.33),
(88.8, 368.40),
(89.0, 372.49),
(89.3, 376.59),
(89.5, 380.71),
(89.8, 384.84),
(90.0, 388.99),
(90.3, 393.15),
(90.5, 397.32),
(90.8, 401.51),
(91.0, 405.72),
(91.3, 409.94),
(91.5, 414.17),
(91.8, 418.42),
(92.0, 422.68),
(92.3, 426.95),
(92.5, 431.24),
(92.8, 435.55),
(93.0, 439.87),
(93.3, 444.20),
(93.5, 448.54),
(93.8, 452.90),
(94.0, 457.28),
(94.3, 461.66),
(94.5, 466.06),
(94.8, 470.48),
(95.0, 474.90),
(95.3, 479.34),
(95.5, 483.80),
(95.8, 488.26),
(96.0, 492.74),
(96.3, 497.24),
(96.5, 501.74),
(96.8, 506.26),
(97.0, 510.80),
(97.3, 515.34),
(97.5, 519.90),
(97.8, 524.47),
(98.0, 529.06),
(98.3, 533.65),
(98.5, 538.26),
(98.8, 542.88),
(99.0, 547.52),
(99.3, 552.16),
(99.5, 556.82),
(99.8, 561.49),
(100.0, 566.18),
(100.3, 570.87),
(100.5, 575.58),
(100.8, 580.30),
(101.0, 585.04),
(101.3, 589.78),
(101.5, 594.54),
(101.8, 599.31),
(102.0, 604.09),
(102.3, 608.88),
(102.5, 613.68),
(102.8, 618.50),
(103.0, 623.33),
(103.3, 628.17),
(103.5, 633.02),
(103.8, 637.88),
(104.0, 642.75),
(104.3, 647.64),
(104.5, 652.54),
(104.8, 657.44),
(105.0, 662.36),
(105.3, 667.29),
(105.5, 672.24),
(105.8, 677.19),
(106.0, 682.15),
(106.3, 687.13),
(106.5, 692.12),
(106.8, 697.11),
(107.0, 702.12),
(107.3, 707.14),
(107.5, 712.17),
(107.8, 717.21),
(108.0, 722.27),
(108.3, 727.33),
(108.5, 732.40),
(108.8, 737.49),
(109.0, 742.58),
(109.3, 747.69),
(109.5, 732.08),
(109.8, 737.24),
(110.0, 742.41),
(110.3, 747.59),
(110.5, 752.78),
(110.8, 757.99),
(111.0, 763.20),
(111.3, 768.43),
(111.5, 773.66),
(111.8, 778.91),
(112.0, 784.16),
(112.3, 789.43),
(112.5, 794.71),
(112.8, 800.00),
(113.0, 805.30),
(113.3, 810.61),
(113.5, 815.93),
(113.8, 821.26),
(114.0, 826.60),
(114.3, 831.96),
(114.5, 837.32),
(114.8, 842.69),
(115.0, 848.08),
(115.3, 853.47),
(115.5, 858.88),
(115.8, 864.29),
(116.0, 869.72),
(116.3, 875.15),
(116.5, 880.60),
(116.8, 886.05),
(117.0, 891.52),
(117.3, 896.99),
(117.5, 902.48),
(117.8, 907.97),
(118.0, 913.48),
(118.3, 918.99),
(118.5, 924.52),
(118.8, 930.05),
(119.0, 935.59),
(119.3, 941.15),
(119.5, 946.71),
(119.8, 952.29),
(120.0, 957.87),
(120.3, 963.46),
(120.5, 969.06),
(120.8, 974.68),
(121.0, 980.30),
(121.3, 985.93),
(121.5, 991.57),
(121.8, 997.22),
(122.0, 1002.88),
(122.3, 1008.54),
(122.5, 1014.22),
(122.8, 1019.91),
(123.0, 1025.61),
(123.3, 1031.31),
(123.5, 1037.03),
(123.8, 1042.75),
(124.0, 1048.48),
(124.3, 1054.22),
(124.5, 1059.97),
(124.8, 1065.73),
(125.0, 1071.50),
(125.3, 1077.28),
(125.5, 1083.07),
(125.8, 1088.86),
(126.0, 1094.67),
(126.3, 1100.48),
(126.5, 1106.30),
(126.8, 1112.14),
(127.0, 1117.98),
(127.3, 1123.82),
(127.5, 1129.68),
(127.8, 1135.55),
(128.0, 1141.42),
(128.3, 1147.31),
(128.5, 1153.20),
(128.8, 1159.10),
(129.0, 1165.01),
(129.3, 1170.92),
(129.5, 1176.85),
(129.8, 1182.78),
(130.0, 1188.73),
(130.3, 1194.68),
(130.5, 1200.64),
(130.8, 1206.60),
(131.0, 1212.58),
(131.3, 1218.57),
(131.5, 1224.56),
(131.8, 1230.56),
(132.0, 1236.57),
(132.3, 1242.59),
(132.5, 1248.61),
(132.8, 1254.64),
(133.0, 1260.69),
(133.3, 1266.74),
(133.5, 1272.79),
(133.8, 1278.86),
(134.0, 1284.93),
(134.3, 1291.02),
(134.5, 1297.11),
(134.8, 1303.20),
(135.0, 1309.31),
(135.3, 1315.42),
(135.5, 1321.54),
(135.8, 1327.67),
(136.0, 1333.81),
(136.3, 1339.95),
(136.5, 1346.11),
(136.8, 1352.27),
(137.0, 1358.43),
(137.3, 1364.61),
(137.5, 1370.79),
(137.8, 1376.98),
(138.0, 1383.18),
(138.3, 1389.39),
(138.5, 1395.60),
(138.8, 1401.82),
(139.0, 1408.05),
(139.3, 1414.29),
(139.5, 1420.53),
(139.8, 1426.78),
(140.0, 1433.04),
(140.3, 1439.31),
(140.5, 1445.58),
(140.8, 1451.86),
(141.0, 1458.15),
(141.3, 1464.45),
(141.5, 1470.75),
(141.8, 1477.06),
(142.0, 1483.38),
(142.3, 1489.70),
(142.5, 1496.03),
(142.8, 1502.37),
(143.0, 1508.72),
(143.3, 1515.07),
(143.5, 1521.43),
(143.8, 1527.80),
(144.0, 1534.17),
(144.3, 1540.55),
(144.5, 1546.94),
(144.8, 1553.34),
(145.0, 1559.74),
(145.3, 1566.15),
(145.5, 1572.56),
(145.8, 1578.99),
(146.0, 1585.42),
(146.3, 1591.85),
(146.5, 1598.30),
(146.8, 1604.75),
(147.0, 1611.21),
(147.3, 1617.67),
(147.5, 1624.14),
(147.8, 1630.62),
(148.0, 1637.10),
(148.3, 1643.60),
(148.5, 1650.09),
(148.8, 1656.60),
(149.0, 1663.11),
(149.3, 1669.63),
(149.5, 1676.15),
(149.8, 1682.69),
(150.0, 1689.22),
(150.3, 1695.77),
(150.5, 1702.32),
(150.8, 1708.88),
(151.0, 1715.44),
(151.3, 1722.01),
(151.5, 1728.59),
(151.8, 1735.17),
(152.0, 1741.76),
(152.3, 1748.36),
(152.5, 1754.96),
(152.8, 1761.57),
(153.0, 1768.19),
(153.3, 1774.81),
(153.5, 1781.44),
(153.8, 1788.07),
(154.0, 1794.71),
(154.3, 1801.36),
(154.5, 1808.01),
(154.8, 1814.67),
(155.0, 1821.34),
(155.3, 1828.01),
(155.5, 1834.69),
(155.8, 1841.37),
(156.0, 1848.07),
(156.3, 1854.76),
(156.5, 1861.47),
(156.8, 1868.17),
(157.0, 1874.89),
(157.3, 1881.61),
(157.5, 1888.34),
(157.8, 1895.07),
(158.0, 1901.81),
(158.3, 1908.56),
(158.5, 1915.31),
(158.8, 1922.06),
(159.0, 1928.83),
(159.3, 1935.60),
(159.5, 1942.37),
(159.8, 1949.15),
(160.0, 1955.94),
(160.3, 1962.73),
(160.5, 1969.53),
(160.8, 1976.34),
(161.0, 1983.15),
(161.3, 1989.96),
(161.5, 1996.79),
(161.8, 2003.61),
(162.0, 2010.45),
(162.3, 2017.29),
(162.5, 2024.13),
(162.8, 2030.98),
(163.0, 2037.84),
(163.3, 2044.70),
(163.5, 2051.57),
(163.8, 2058.44),
(164.0, 2065.32),
(164.3, 2072.21),
(164.5, 2079.10),
(164.8, 2085.99),
(165.0, 2092.89),
(165.3, 2099.80),
(165.5, 2106.71),
(165.8, 2113.63),
(166.0, 2120.55),
(166.3, 2127.48),
(166.5, 2134.42),
(166.8, 2141.36),
(167.0, 2148.30),
(167.3, 2155.26),
(167.5, 2162.21),
(167.8, 2169.17),
(168.0, 2176.14),
(168.3, 2183.11),
(168.5, 2190.09),
(168.8, 2197.08),
(169.0, 2204.06),
(169.3, 2211.06),
(169.5, 2218.06),
(169.8, 2225.06),
(170.0, 2232.07),
(170.3, 2239.09),
(170.5, 2246.11),
(170.8, 2253.13),
(171.0, 2260.17),
(171.3, 2267.20),
(171.5, 2274.24),
(171.8, 2281.29),
(172.0, 2288.34),
(172.3, 2295.40),
(172.5, 2302.46),
(172.8, 2309.53),
(173.0, 2316.60),
(173.3, 2323.68),
(173.5, 2330.76),
(173.8, 2337.85),
(174.0, 2344.94),
(174.3, 2352.04),
(174.5, 2359.14),
(174.8, 2366.25),
(175.0, 2373.36),
(175.3, 2380.48),
(175.5, 2387.61),
(175.8, 2394.73),
(176.0, 2401.87),
(176.3, 2409.01),
(176.5, 2416.15),
(176.8, 2423.30),
(177.0, 2430.45),
(177.3, 2437.61),
(177.5, 2444.77),
(177.8, 2451.94),
(178.0, 2459.11),
(178.3, 2466.29),
(178.5, 2473.47),
(178.8, 2480.66),
(179.0, 2487.85),
(179.3, 2495.04),
(179.5, 2502.25),
(179.8, 2509.45),
(180.0, 2516.66),
(180.3, 2523.88),
(180.5, 2531.10),
(180.8, 2538.32),
(181.0, 2545.55),
(181.3, 2552.79),
(181.5, 2560.03),
(181.8, 2567.27),
(182.0, 2574.52),
(182.3, 2581.77),
(182.5, 2589.03),
(182.8, 2596.29),
(183.0, 2603.56),
(183.3, 2610.83),
(183.5, 2618.11),
(183.8, 2625.39),
(184.0, 2632.68),
(184.3, 2639.97),
(184.5, 2647.26),
(184.8, 2654.56),
(185.0, 2661.87),
(185.3, 2669.17),
(185.5, 2676.49),
(185.8, 2683.81),
(186.0, 2691.13),
(186.3, 2698.45),
(186.5, 2705.79),
(186.8, 2713.12),
(187.0, 2720.46),
(187.3, 2727.81),
(187.5, 2735.15),
(187.8, 2742.51),
(188.0, 2749.87),
(188.3, 2757.23),
(188.5, 2764.59),
(188.8, 2771.96),
(189.0, 2779.34),
(189.3, 2786.72),
(189.5, 2794.10),
(189.8, 2801.49),
(190.0, 2808.88),
(190.3, 2816.28),
(190.5, 2823.68),
(190.8, 2831.09),
(191.0, 2838.50),
(191.3, 2845.91),
(191.5, 2853.33),
(191.8, 2860.75),
(192.0, 2868.18),
(192.3, 2875.61),
(192.5, 2883.05),
(192.8, 2890.49),
(193.0, 2897.93),
(193.3, 2905.38),
(193.5, 2912.83),
(193.8, 2920.29),
(194.0, 2927.75),
(194.3, 2935.21),
(194.5, 2942.68),
(194.8, 2950.15),
(195.0, 2957.63),
(195.3, 2965.11),
(195.5, 2972.60),
(195.8, 2980.09),
(196.0, 2987.58),
(196.3, 2995.08),
(196.5, 3002.58),
(196.8, 3010.09),
(197.0, 3017.59),
(197.3, 3025.11))

    # Test for out of bounds stage values
    if stage_in < STAGETBL[0][0]:  # if measured stage is BELOW the FIRST stage value in the FIRST stage,flow pair
        flow = STAGETBL[0][1] # Use lowest flow value in the stage,flow pairs
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
        
        bottle_num = gp_read_value_by_label("bottle_num")
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
    bottle_num = int(gp_read_value_by_label("bottle_num"))
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

#@MEASUREMENT
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
    ## Check if sampling is on
    gp_sampling_on = gp_read_value_by_label("sampling_on") ## Read value in GP
    if gp_sampling_on == 1:
        sampling_on =  True
    elif gp_sampling_on == 0:
        sampling_on = False
    ## If sampling_on=0 (sampling not started yet)
    if sampling_on== False:
        print("Start sampling!")
        for i in [i for i in range(1,30,1)]: #0-29 = M1-M30
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
    elif sampling_on==True:
        print("Alarm triggered but sampling was already started. No action")
    else:
        pass
    return

@TASK
def turn_off_sampling():
    print ("Stopped sampling")
    # Stop sampling when level triggered
    gp_write_value_by_label("sampling_on", 0)  # 0=False
    setup_write("!M31 log reading", "Off") #stop logging event number
    ## Set data collection back to 5 min
    for i in [i for i in range(1, 30, 1)]: #0-29 = M1-M30
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

