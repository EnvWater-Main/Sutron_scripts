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

def get_pacing_mode():
    if setup_read("M4 ACTIVE") == "On":
        pacing_mode = "FLOW"
    elif setup_read("M5 ACTIVE") == "On":
        pacing_mode = "TIME"
    else:
        pacing_mode = "NONE"
    return pacing_mode

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

# SampleOn - start/stop sampling
sampling_on = False

# Event Number (not recorded when Sutron not In Alarm)
event_num = int(gp_read_value_by_label("event_num")) # this is entered manually prior to storm

#defines if program will have 24 bottle carousel (bottle_num goes up with each aliquot)
carousel_or_comp = float(gp_read_value_by_label("carousel_or_comp")) ## 0 = carousel, 1 = composite

# Bottle Number (if composite, bottle number is changed manually, if carousel bottle number increments up with aliquot num)
bottle_num = float(gp_read_value_by_label("bottle_num"))

# We count how many aliquots have been collected in each bottle
tot_aliquots = 0
aliquots_in_bottle = 0
# Bottle volume mL - running total of volume in bottle
aliquot_vol = int(gp_read_value_by_label("aliquot_vol_mL"))
vol_in_bottle = 0.0

## Pacing Weighting Mode - Flow or Time-weighted
pacing_mode = get_pacing_mode()

## Flow Units
flow_pacing_data_source_units, flow_pacing_units = get_flow_units()

## Time Pacing Increment
time_pacing_increment = get_time_pacing_increment() ## how many minutes between measurements is how many minutes to subtract/count down

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

    ## Two scenarios: pacing change and new, empty bottle OR pacing change with same bottle (AKA "dump and double")
    ## Pacing change and new bottle:
    if bottle_num != bottle_input:
        bottle_num = bottle_input  # update global bottle_num to new bottle_num (ie 1 to 2, 2 to 3 etc)
        ## Reset aliquot count and volume (may only be dumping out some volume and changing pacing but reset anyway)
        aliquots_in_bottle = 0.
        vol_in_bottle = 0.0
    ## Pacing change and same bottle (ie "dump and double")
    elif bottle_num == bottle_input:
        volume_ratio = pacing_input / sample_pacing # ex if pacing doubles, 100cf / 50 cf = 2
        vol_in_bottle = vol_in_bottle / volume_ratio # if pacing doubles, then divide by ratio. should be dumping out 1/2 in this example
        # aliquots_in_bottle = aliquots_in_bottle ## keep aliquot number the same

    # Update global values
    sample_pacing = float(pacing_input) # update global sample_pacing from GP variable

    # Print new parameters
    print("Pacing changed! New Pacing: " + "%.0f" % sample_pacing + flow_pacing_units) # should be updated above
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

def pulse_sampler():
    # Switched Power - DO NOT USE IF USING SDI12 WARMUP OR ANY ANALOG MEASUREMENTS
    power_control('SW1', True)
    utime.sleep(0.5)
    power_control('SW1', False)

    # Digital Out 1 - NEEDS TO BE USED WITH RELAY OR PULL-UP RESISTOR
    power_control('OUTPUT1', True)
    utime.sleep(0.5)
    power_control('OUTPUT1', False)

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
        # trigger sampler by pulsing output for 0.5 seconds
        pulse_sampler()
        # write a log entry
        t = utime.localtime(time_scheduled())
        day, minute = str(t[2]), str(t[4])
        if len(day) == 1:
            day = '0' + day
        if len(minute) == 1:
            minute = '0' + minute
        sample_time = str(t[1]) + '/' + day + '/' + str(t[0]) + ' ' + str(t[3]) + ':' + minute
        reading = Reading(label="Triggered Sampler", time=time_scheduled(),etype='E', value=tot_aliquots,
                          right_digits=0, quality='G')  # 'E' = event, 'M' = measurement, 'D' = debug
        reading.write_log()
        ## Write display log entries
        #global sample_log
        #global bottle_num
        #global tot_aliquots
        #global aliquots_in_bottle
        #global sample_pacing

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
    STAGETBL = ((0.0, 0.0),
    (0.2, 0.025),
    (0.4, 0.05),
    (0.6, 0.075),
    (0.8, 0.1),
    (1.0, 0.125),
    (1.2, 0.208),
    (1.4, 0.291),
    (1.6, 0.375),
    (1.8, 0.458),
    (2.0, 0.541),
    (2.2, 0.708),
    (2.4, 0.875),
    (2.6, 1.041),
    (2.8, 1.208),
    (3.0, 1.375),
    (3.2, 1.597),
    (3.4, 1.819),
    (3.6, 2.04),
    (3.8, 2.262),
    (4.0, 2.484),
    (4.2, 2.854),
    (4.4, 3.224),
    (4.6, 3.593),
    (4.8, 3.963),
    (5.0, 4.333),
    (5.2, 4.745),
    (5.4, 5.158),
    (5.6, 5.57),
    (5.8, 5.983),
    (6.0, 6.395),
    (6.2, 6.921),
    (6.4, 7.446),
    (6.6, 7.972),
    (6.8, 8.498),
    (7.0, 9.023),
    (7.2, 9.615),
    (7.4, 10.206),
    (7.6, 10.798),
    (7.8, 11.389),
    (8.0, 11.981),
    (8.2, 12.559),
    (8.4, 13.137),
    (8.6, 13.716),
    (8.8, 14.294),
    (9.0, 14.872),
    (9.2, 15.6),
    (9.4, 16.329),
    (9.6, 17.057),
    (9.8, 17.785),
    (10.0, 18.513),
    (10.2, 19.298),
    (10.4, 20.084),
    (10.6, 20.869),
    (10.8, 21.655),
    (11.0, 22.441),
    (11.2, 23.28),
    (11.4, 24.12),
    (11.6, 24.96),
    (11.8, 25.799),
    (12.0, 26.639),
    (12.2, 27.53),
    (12.4, 28.42),
    (12.6, 29.311),
    (12.8, 30.202),
    (13.0, 31.093),
    (13.2, 31.859),
    (13.4, 32.626),
    (13.6, 33.392),
    (13.8, 34.159),
    (14.0, 34.925),
    (14.2, 35.937),
    (14.4, 36.948),
    (14.6, 37.96),
    (14.8, 38.972),
    (15.0, 39.983),
    (15.2, 40.842),
    (15.4, 41.701),
    (15.6, 42.561),
    (15.8, 43.42),
    (16.0, 44.279),
    (16.2, 45.413),
    (16.4, 46.547),
    (16.6, 47.681),
    (16.8, 48.815),
    (17.0, 49.949),
    (17.2, 51.13),
    (17.4, 52.312),
    (17.6, 53.494),
    (17.8, 54.675),
    (18.0, 55.857),
    (18.2, 56.803),
    (18.4, 57.75),
    (18.6, 58.696),
    (18.8, 59.643),
    (19.0, 60.589),
    (19.2, 61.574),
    (19.4, 62.559),
    (19.6, 63.544),
    (19.8, 64.529),
    (20.0, 65.514),
    (20.2, 66.892),
    (20.4, 68.271),
    (20.6, 69.65),
    (20.8, 71.029),
    (21.0, 72.407),
    (21.2, 73.834),
    (21.4, 75.26),
    (21.6, 76.687),
    (21.8, 78.113),
    (22.0, 79.54),
    (22.2, 81.013),
    (22.4, 82.485),
    (22.6, 83.958),
    (22.8, 85.431),
    (23.0, 86.903),
    (23.2, 88.42),
    (23.4, 89.938),
    (23.6, 91.455),
    (23.8, 92.972),
    (24.0, 94.489),
    (24.2, 96.049),
    (24.4, 97.61),
    (24.6, 99.17),
    (24.8, 100.73),
    (25.0, 102.291),
    (25.2, 103.892),
    (25.4, 105.494),
    (25.6, 107.096),
    (25.8, 108.698),
    (26.0, 110.3),
    (26.2, 111.943),
    (26.4, 113.585),
    (26.6, 115.227),
    (26.8, 116.87),
    (27.0, 118.512),
    (27.2, 119.641),
    (27.4, 120.769),
    (27.6, 121.897),
    (27.8, 123.026),
    (28.0, 124.154),
    (28.2, 125.368),
    (28.4, 126.582),
    (28.6, 127.796),
    (28.8, 129.01),
    (29.0, 130.224),
    (29.2, 132.065),
    (29.4, 133.905),
    (29.6, 135.745),
    (29.8, 137.585),
    (30.0, 139.425),
    (30.2, 141.308),
    (30.4, 143.19),
    (30.6, 145.072),
    (30.8, 146.954),
    (31.0, 148.836),
    (31.2, 150.76),
    (31.4, 152.683),
    (31.6, 154.606),
    (31.8, 156.529),
    (32.0, 158.452),
    (32.2, 160.415),
    (32.4, 162.378),
    (32.6, 164.34),
    (32.8, 166.303),
    (33.0, 168.266),
    (33.2, 169.578),
    (33.4, 170.89),
    (33.6, 172.203),
    (33.8, 173.515),
    (34.0, 174.827),
    (34.2, 176.912),
    (34.4, 178.996),
    (34.6, 181.081),
    (34.8, 183.166),
    (35.0, 185.251),
    (35.2, 187.375),
    (35.4, 189.5),
    (35.6, 191.624),
    (35.8, 193.748),
    (36.0, 195.873),
    (36.2, 197.239),
    (36.4, 198.605),
    (36.6, 199.971),
    (36.8, 201.337),
    (37.0, 202.703),
    (37.2, 204.951),
    (37.4, 207.199),
    (37.6, 209.447),
    (37.8, 211.695),
    (38.0, 213.943),
    (38.2, 215.421),
    (38.4, 216.9),
    (38.6, 218.378),
    (38.8, 219.856),
    (39.0, 221.335),
    (39.2, 223.71),
    (39.4, 226.085),
    (39.6, 228.46),
    (39.8, 230.835),
    (40.0, 233.21),
    (40.2, 235.626),
    (40.4, 238.042),
    (40.6, 240.458),
    (40.8, 242.873),
    (41.0, 245.289),
    (41.2, 247.745),
    (41.4, 250.2),
    (41.6, 252.656),
    (41.8, 255.111),
    (42.0, 257.567),
    (42.2, 259.091),
    (42.4, 260.616),
    (42.6, 262.141),
    (42.8, 263.666),
    (43.0, 265.191),
    (43.2, 266.853),
    (43.4, 268.516),
    (43.6, 270.179),
    (43.8, 271.842),
    (44.0, 273.505),
    (44.2, 276.18),
    (44.4, 278.855),
    (44.6, 281.53),
    (44.8, 284.206),
    (45.0, 286.881),
    (45.2, 289.598),
    (45.4, 292.315),
    (45.6, 295.032),
    (45.8, 297.749),
    (46.0, 300.466),
    (46.2, 303.224),
    (46.4, 305.982),
    (46.6, 308.74),
    (46.8, 311.498),
    (47.0, 314.255),
    (47.2, 315.966),
    (47.4, 317.677),
    (47.6, 319.387),
    (47.8, 321.098),
    (48.0, 322.809),
    (48.2, 324.664),
    (48.4, 326.52),
    (48.6, 328.375),
    (48.8, 330.231),
    (49.0, 332.087),
    (49.2, 335.074),
    (49.4, 338.061),
    (49.6, 341.049),
    (49.8, 344.036),
    (50.0, 347.023),
    (50.2, 350.053),
    (50.4, 353.083),
    (50.6, 356.114),
    (50.8, 359.144),
    (51.0, 362.174),
    (51.2, 364.101),
    (51.4, 366.028),
    (51.6, 367.955),
    (51.8, 369.882),
    (52.0, 371.809),
    (52.2, 374.979),
    (52.4, 378.149),
    (52.6, 381.319),
    (52.8, 384.489),
    (53.0, 387.659),
    (53.2, 390.871),
    (53.4, 394.084),
    (53.6, 397.297),
    (53.8, 400.51),
    (54.0, 403.723),
    (54.2, 406.978),
    (54.4, 410.234),
    (54.6, 413.489),
    (54.8, 416.744),
    (55.0, 419.999),
    (55.2, 423.296),
    (55.4, 426.593),
    (55.6, 429.889),
    (55.8, 433.186),
    (56.0, 436.482),
    (56.2, 437.23),
    (56.4, 437.978),
    (56.6, 438.725),
    (56.8, 439.473),
    (57.0, 440.221),
    (57.2, 443.718),
    (57.4, 447.215),
    (57.6, 450.712),
    (57.8, 454.209),
    (58.0, 457.705),
    (58.2, 461.247),
    (58.4, 464.788),
    (58.6, 468.329),
    (58.8, 471.87),
    (59.0, 475.411),
    (59.2, 478.996),
    (59.4, 482.581),
    (59.6, 486.165),
    (59.8, 489.75),
    (60.0, 493.335),
    (60.2, 496.962),
    (60.4, 500.59),
    (60.6, 504.217),
    (60.8, 507.845),
    (61.0, 511.472),
    (61.2, 515.142),
    (61.4, 518.812),
    (61.6, 522.481),
    (61.8, 526.151),
    (62.0, 529.82),
    (62.2, 532.065),
    (62.4, 534.31),
    (62.6, 536.555),
    (62.8, 538.8),
    (63.0, 541.045),
    (63.2, 544.861),
    (63.4, 548.677),
    (63.6, 552.493),
    (63.8, 556.309),
    (64.0, 560.125),
    (64.2, 563.983),
    (64.4, 567.842),
    (64.6, 571.7),
    (64.8, 575.559),
    (65.0, 579.417),
    (65.2, 581.722),
    (65.4, 584.027),
    (65.6, 586.332),
    (65.8, 588.637),
    (66.0, 590.942),
    (66.2, 593.338),
    (66.4, 595.733),
    (66.6, 598.128),
    (66.8, 600.524),
    (67.0, 602.919),
    (67.2, 607.034),
    (67.4, 611.148),
    (67.6, 615.263),
    (67.8, 619.377),
    (68.0, 623.492),
    (68.2, 627.651),
    (68.4, 631.81),
    (68.6, 635.969),
    (68.8, 640.128),
    (69.0, 644.287),
    (69.2, 648.489),
    (69.4, 652.692),
    (69.6, 656.895),
    (69.8, 661.097),
    (70.0, 665.3),
    (70.2, 667.797),
    (70.4, 670.294),
    (70.6, 672.792),
    (70.8, 675.289),
    (71.0, 677.787),
    (71.2, 682.143),
    (71.4, 686.499),
    (71.6, 690.855),
    (71.8, 695.211),
    (72.0, 699.567),
    (72.2, 703.967),
    (72.4, 708.367),
    (72.6, 712.767),
    (72.8, 717.167),
    (73.0, 721.567),
    (73.2, 726.011),
    (73.4, 730.455),
    (73.6, 734.898),
    (73.8, 739.342),
    (74.0, 743.786),
    (74.2, 748.272),
    (74.4, 752.759),
    (74.6, 757.245),
    (74.8, 761.731),
    (75.0, 766.217),
    (75.2, 767.098),
    (75.4, 767.979),
    (75.6, 768.859),
    (75.8, 769.74),
    (76.0, 770.621),
    (76.2, 775.335),
    (76.4, 780.048),
    (76.6, 784.761),
    (76.8, 789.475),
    (77.0, 794.188),
    (77.2, 798.947),
    (77.4, 803.706),
    (77.6, 808.465),
    (77.8, 813.224),
    (78.0, 817.983),
    (78.2, 822.787),
    (78.4, 827.591),
    (78.6, 832.395),
    (78.8, 837.199),
    (79.0, 842.002),
    (79.2, 846.851),
    (79.4, 851.699),
    (79.6, 856.547),
    (79.8, 861.395),
    (80.0, 866.243),
    (80.2, 871.135),
    (80.4, 876.027),
    (80.6, 880.919),
    (80.8, 885.81),
    (81.0, 890.702),
    (81.2, 893.512),
    (81.4, 896.321),
    (81.6, 899.131),
    (81.8, 901.941),
    (82.0, 904.751),
    (82.2, 909.803),
    (82.4, 914.855),
    (82.6, 919.906),
    (82.8, 924.958),
    (83.0, 930.01),
    (83.2, 935.106),
    (83.4, 940.202),
    (83.6, 945.298),
    (83.8, 950.394),
    (84.0, 955.49),
    (84.2, 960.63),
    (84.4, 965.769),
    (84.6, 970.909),
    (84.8, 976.048),
    (85.0, 981.188),
    (85.2, 986.37),
    (85.4, 991.553),
    (85.6, 996.735),
    (85.8, 1001.917),
    (86.0, 1007.1),
    (86.2, 1012.325),
    (86.4, 1017.549),
    (86.6, 1022.774),
    (86.8, 1027.999),
    (87.0, 1033.223),
    (87.2, 1036.206),
    (87.4, 1039.188),
    (87.6, 1042.171),
    (87.8, 1045.154),
    (88.0, 1048.137),
    (88.2, 1053.524),
    (88.4, 1058.912),
    (88.6, 1064.3),
    (88.8, 1069.687),
    (89.0, 1075.075),
    (89.2, 1080.505),
    (89.4, 1085.936),
    (89.6, 1091.367),
    (89.8, 1096.797),
    (90.0, 1102.228),
    (90.2, 1107.7),
    (90.4, 1113.173),
    (90.6, 1118.646),
    (90.8, 1124.119),
    (91.0, 1129.592),
    (91.2, 1135.107),
    (91.4, 1140.621),
    (91.6, 1146.136),
    (91.8, 1151.65),
    (92.0, 1157.165),
    (92.2, 1162.721),
    (92.4, 1168.277),
    (92.6, 1173.833),
    (92.8, 1179.389),
    (93.0, 1184.944),
    (93.2, 1190.541),
    (93.4, 1196.138),
    (93.6, 1201.734),
    (93.8, 1207.331),
    (94.0, 1212.928),
    (94.2, 1218.564),
    (94.4, 1224.201),
    (94.6, 1229.838),
    (94.8, 1235.475),
    (95.0, 1241.112),
    (95.2, 1246.788),
    (95.4, 1252.465),
    (95.6, 1258.141),
    (95.8, 1263.818),
    (96.0, 1269.495),
    (96.2, 1275.21),
    (96.4, 1280.926),
    (96.6, 1286.642),
    (96.8, 1292.358),
    (97.0, 1298.074),
    (97.2, 1303.828),
    (97.4, 1309.583),
    (97.6, 1315.337),
    (97.8, 1321.092),
    (98.0, 1326.847),
    (98.2, 1332.64),
    (98.4, 1338.432),
    (98.6, 1344.225),
    (98.8, 1350.018),
    (99.0, 1355.811),
    (99.2, 1361.642),
    (99.4, 1367.473),
    (99.6, 1373.303),
    (99.8, 1379.134),
    (100.0, 1384.965),
    (100.2, 1390.833),
    (100.4, 1396.701),
    (100.6, 1402.569),
    (100.8, 1408.437),
    (101.0, 1414.305),
    (101.2, 1420.21),
    (101.4, 1426.115),
    (101.6, 1432.021),
    (101.8, 1437.926),
    (102.0, 1443.831),
    (102.2, 1449.772),
    (102.4, 1455.714),
    (102.6, 1461.655),
    (102.8, 1467.597),
    (103.0, 1473.539),
    (103.2, 1479.516),
    (103.4, 1485.494),
    (103.6, 1491.472),
    (103.8, 1497.449),
    (104.0, 1503.427),
    (104.2, 1509.44),
    (104.4, 1515.454),
    (104.6, 1521.467),
    (104.8, 1527.481),
    (105.0, 1533.494),
    (105.2, 1539.543),
    (105.4, 1545.591),
    (105.6, 1551.64),
    (105.8, 1557.688),
    (106.0, 1563.737),
    (106.2, 1569.82),
    (106.4, 1575.904),
    (106.6, 1581.987),
    (106.8, 1588.071),
    (107.0, 1594.154),
    (107.2, 1600.272),
    (107.4, 1606.39),
    (107.6, 1612.508),
    (107.8, 1618.626),
    (108.0, 1624.744),
    (108.2, 1630.896),
    (108.4, 1637.048),
    (108.6, 1643.2),
    (108.8, 1649.352),
    (109.0, 1655.504),
    (109.2, 1661.69),
    (109.4, 1667.876),
    (109.6, 1674.062),
    (109.8, 1680.247),
    (110.0, 1686.433),
    (110.2, 1692.652),
    (110.4, 1698.871),
    (110.6, 1705.09),
    (110.8, 1711.309),
    (111.0, 1717.528),
    (111.2, 1723.78),
    (111.4, 1730.032),
    (111.6, 1736.284),
    (111.8, 1742.536),
    (112.0, 1748.788),
    (112.2, 1755.073),
    (112.4, 1761.357),
    (112.6, 1767.642),
    (112.8, 1773.927),
    (113.0, 1780.211),
    (113.2, 1786.528),
    (113.4, 1792.845),
    (113.6, 1799.162),
    (113.8, 1805.479),
    (114.0, 1811.795),
    (114.2, 1818.144),
    (114.4, 1824.493),
    (114.6, 1830.841),
    (114.8, 1837.19),
    (115.0, 1843.539),
    (115.2, 1849.919),
    (115.4, 1856.299),
    (115.6, 1862.68),
    (115.8, 1869.06),
    (116.0, 1875.44),
    (116.2, 1881.852),
    (116.4, 1888.263),
    (116.6, 1894.674),
    (116.8, 1901.086),
    (117.0, 1907.497),
    (117.2, 1913.94),
    (117.4, 1920.382),
    (117.6, 1926.824),
    (117.8, 1933.267),
    (118.0, 1939.709),
    (118.2, 1946.182),
    (118.4, 1952.655),
    (118.6, 1959.127),
    (118.8, 1965.6),
    (119.0, 1972.073),
    (119.2, 1978.576),
    (119.4, 1985.079),
    (119.6, 1991.582),
    (119.8, 1998.085),
    (120.0, 2004.588),
    (120.2, 2011.121),
    (120.4, 2017.654),
    (120.6, 2024.187),
    (120.8, 2030.72),
    (121.0, 2037.253),
    (121.2, 2043.816),
    (121.4, 2050.378),
    (121.6, 2056.941),
    (121.8, 2063.503),
    (122.0, 2070.066),
    (122.2, 2076.658),
    (122.4, 2083.25),
    (122.6, 2089.841),
    (122.8, 2096.433),
    (123.0, 2103.025),
    (123.2, 2109.646),
    (123.4, 2116.267),
    (123.6, 2122.887),
    (123.8, 2129.508),
    (124.0, 2136.129),
    (124.2, 2142.778),
    (124.4, 2149.428),
    (124.6, 2156.077),
    (124.8, 2162.727),
    (125.0, 2169.376),
    (125.2, 2176.054),
    (125.4, 2182.732),
    (125.6, 2189.41),
    (125.8, 2196.088),
    (126.0, 2202.766),
    (126.2, 2209.471),
    (126.4, 2216.177),
    (126.6, 2222.883),
    (126.8, 2229.589),
    (127.0, 2236.295),
    (127.2, 2243.029),
    (127.4, 2249.763),
    (127.6, 2256.496),
    (127.8, 2263.23),
    (128.0, 2269.964),
    (128.2, 2276.725),
    (128.4, 2283.486),
    (128.6, 2290.248),
    (128.8, 2297.009),
    (129.0, 2303.77),
    (129.2, 2310.559),
    (129.4, 2317.347),
    (129.6, 2324.136),
    (129.8, 2330.924),
    (130.0, 2337.713),
    (130.2, 2344.528),
    (130.4, 2351.344),
    (130.6, 2358.159),
    (130.8, 2364.975),
    (131.0, 2371.79),
    (131.2, 2378.633),
    (131.4, 2385.475),
    (131.6, 2392.317),
    (131.8, 2399.159),
    (132.0, 2406.001),
    (132.2, 2412.87),
    (132.4, 2419.739),
    (132.6, 2426.607),
    (132.8, 2433.476),
    (133.0, 2440.345),
    (133.2, 2447.24),
    (133.4, 2454.134),
    (133.6, 2461.029),
    (133.8, 2467.924),
    (134.0, 2474.819),
    (134.2, 2481.74),
    (134.4, 2488.66),
    (134.6, 2495.581),
    (134.8, 2502.502),
    (135.0, 2509.423),
    (135.2, 2516.369),
    (135.4, 2523.316),
    (135.6, 2530.262),
    (135.8, 2537.208),
    (136.0, 2544.155),
    (136.2, 2551.127),
    (136.4, 2558.099),
    (136.6, 2565.071),
    (136.8, 2572.042),
    (137.0, 2579.014),
    (137.2, 2586.011),
    (137.4, 2593.008),
    (137.6, 2600.005),
    (137.8, 2607.002),
    (138.0, 2614.0),
    (138.2, 2621.022),
    (138.4, 2628.043),
    (138.6, 2635.065),
    (138.8, 2642.087),
    (139.0, 2649.109),
    (139.2, 2656.156),
    (139.4, 2663.203),
    (139.6, 2670.249),
    (139.8, 2677.296),
    (140.0, 2684.343),
    (140.2, 2691.414),
    (140.4, 2698.485),
    (140.6, 2705.556),
    (140.8, 2712.627),
    (141.0, 2719.699),
    (141.2, 2726.794),
    (141.4, 2733.889),
    (141.6, 2740.985),
    (141.8, 2748.08),
    (142.0, 2755.176),
    (142.2, 2762.295),
    (142.4, 2769.414),
    (142.6, 2776.534),
    (142.8, 2783.653),
    (143.0, 2790.772),
    (143.2, 2797.916),
    (143.4, 2805.059),
    (143.6, 2812.202),
    (143.8, 2819.345),
    (144.0, 2826.488),
    (144.2, 2833.655),
    (144.4, 2840.822),
    (144.6, 2847.988),
    (144.8, 2855.155),
    (145.0, 2862.322))

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
    global pacing_mode
    global sample_pacing
    global g_running_total
    global bottle_capacity
    global aliquot_vol_mL
    global bottle_num
    global tot_aliquots
    global aliquots_in_bottle
    global vol_in_bottle
    global time_last_sample
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
    pacing_mode = get_pacing_mode()
    ## FLow Units
    flow_pacing_data_source_units, flow_pacing_units = get_flow_units()

    if sampling_on == False and  pacing_mode == "FLOW":
        print ('Sampling is OFF, Sample pacing is FLOW weighted')
        print('Flow:' + "%.2f" % flow + flow_pacing_data_source_units)
        print ("Current bottle number: "+"%.0f"%bottle_num)
        print ("Current pacing: "+"%.0f"%sample_pacing + flow_pacing_units)
        print ("Total aliquots: "+"%.0f"% tot_aliquots)
        print("Aliquots in bottle: " + "%.0f"%aliquots_in_bottle)
        print("Bottle capacity: " + "%.0f"%bottle_capacity)

    elif sampling_on == True and  pacing_mode == "FLOW":
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
    global pacing_mode
    global sample_pacing
    global g_running_total
    global bottle_capacity
    global aliquot_vol_mL
    global bottle_num
    global tot_aliquots
    global aliquots_in_bottle
    global vol_in_bottle
    global time_last_sample

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

    ## Check if program is flow weighted or timeweighted
    pacing_mode = get_pacing_mode()
    sample_pacing = float(gp_read_value_by_label("sample_pacing")) # SamplePacin is GenPurp variables

    if sampling_on == False and  pacing_mode == "TIME":
        print ('Sampling is OFF, Sample pacing is TIME weighted')
        print ("Current bottle number: "+"%.0f"%bottle_num)
        print ("Current pacing: "+str(sample_pacing) + "minutes")
        print ("Total aliquots: "+"%.0f"%tot_aliquots)
        print("Aliquots in bottle: " + "%.0f"%aliquots_in_bottle)
        print("Bottle capacity: " + "%.0f"%bottle_capacity)

    elif sampling_on == True and  pacing_mode == "TIME":
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
def display_aliquots_in_bottle(input):
    global aliquots_in_bottle
    print ('Number of aliquots in bottle: '+str(aliquots_in_bottle))
    return aliquots_in_bottle

@MEASUREMENT
def display_vol_in_bottle(input):
    global vol_in_bottle
    print ('Volume in bottle: '+str(vol_in_bottle))
    return vol_in_bottle

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
    ## Check if sampling is on
    gp_sampling_on = gp_read_value_by_label("sampling_on") ## Read value in GP
    if gp_sampling_on == 1:
        sampling_on =  True
    elif gp_sampling_on == 0:
        sampling_on = False
    ## If sampling_on=0 (sampling not started yet)
    if sampling_on == False:
        print("Start sampling!")
        ## update all measurements to 1min except for Battery voltage (M32)
        for i in [i for i in range(1,31,1)]: #0-29 = M1-M30
            setup_write("!M"+str(i)+" meas interval", "00:01:00")

        # Start sampling when level triggered
        gp_write_value_by_label("sampling_on", 1)  # 1=True
        
        ## turn on Event Number logging - this will flag all of the event data
        event_num = int(gp_read_value_by_label("event_num"))
        setup_write("!M30 log reading", "On") #start logging event number, Event Number is hardcoded to M30

        ## get pacing
        sample_pacing = float(gp_read_value_by_label("sample_pacing")) # SamplePacin is GenPurp variables
        ## Reset parameters for event
        bottle_num = int(gp_read_value_by_label("bottle_num"))
        tot_aliquots = 0
        aliquots_in_bottle = 0
        vol_in_bottle = 0
        ## Check if program is flow weighted
        pacing_mode = get_pacing_mode()
        # Running total increment (time or volume)
        if pacing_mode == "FLOW":
            g_running_total = 0.0  # start at 0 and count up to pacing
        if pacing_mode == "TIME":
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
    setup_write("!M30 log reading", "Off") #stop logging event number
    ## Set data collection back to 5 min
    for i in [i for i in range(1, 31, 1)]: #0-29 = M1-M30
        setup_write("!M" + str(i) + " meas interval", "00:05:00")

@TASK
def reset_sampling_params():
    print("Manually reset sampling parameters!")
    ## Reset all params for start of event
    global sampling_on
    global pacing_mode
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
    pacing_mode = get_pacing_mode()
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
    """ Function triggers SW12 for half seconds in order to trigger a sampler"""
    # trigger sampler by pulsing output for 0.5 seconds
    pulse_sampler()

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

