from sl3 import *
import utime
import math

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
    if setup_read("M3 ACTIVE") == "On":
        pacing = "FLOW"
    elif setup_read("M4 ACTIVE") == "On":
        pacing = "TIME"
    else:
        pacing = "NONE"
    return pacing

def get_flow_units():
    # Flow units - cfs or gpm usually
    flow_pacing_data_source = setup_read("M3 META INDEX")
    flow_pacing_data_source_units = setup_read("M"+str(flow_pacing_data_source )+" UNITS")
    if flow_pacing_data_source_units == 'cfs':
        flow_pacing_units = 'cf'
    elif flow_pacing_data_source_units == 'gpm':
        flow_pacing_units = 'gal'
    elif flow_pacing_data_source_units == 'm3s':
        flow_pacing_units = 'm3'
    else:
        pass
    return flow_pacing_data_source_units, flow_pacing_units

def get_time_pacing_increment():
    # Time Pacing Units should be minutes, just need to know how many
    time_pacing_increment = int(setup_read("M4 MEAS INTERVAL").split(":")[1]) #time is formatted '00:01:00'
    return time_pacing_increment


## Pacing Weighting
pacing_weighting = get_pacing_weighting()

## Flow Units
flow_pacing_data_source_units, flow_pacing_units = get_flow_units()

## Time Pacing Increment
time_pacing_increment = get_time_pacing_increment()

# SampleOn - start/stop sampling
sampling_on = False

# Bottle Number (if pacing is changed bottle number will need to update)
bottle_num = float(gp_read_value_by_label("bottle_num"))

# Bottle volume - running total of volume in bottle
vol_in_bottle = 0.0

# We count how many aliquots have been collected in each bottle
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
        if bottle_num != bottle_input:
            aliquots_in_bottle = 0  # reset aliquot counter to zero
            vol_in_bottle = 0
            print("New Bottle!")
            print("Previous bottle number: " + '%.0f' % bottle_num)
            bottle_num = bottle_input  # update global bottle_num from BottleNum M2 Offset
            print("New bottle number: " + '%.0f' % bottle_input)
            print("................Aliquots in bottle: " + "%.0f" % aliquots_in_bottle)
            print("................Volume in bottle: " + "%.0f" % vol_in_bottle + "mL")
        else:
            print("No bottle change...Current Bottle number: " + '%.0f' % bottle_num)
            print("................Aliquots in bottle: " + "%.0f" % aliquots_in_bottle)
            print("................Volume in bottle: " + "%.0f" % vol_in_bottle + "mL")
            # bottle number should always be whatever is in the GP variable
    return sample_pacing, bottle_num # return new/current pacing volume and new/current bottle number to main function

def bottle_and_pacing_change(pacing_input,bottle_input):
    """ Updates the bottle number (composite) and resets aliquot counts etc
    :return: bottle_num, sample_pacing"""
    global sample_pacing
    global bottle_num
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
                          etype='E', value=aliquots_in_bottle,
                          right_digits=0, quality='G')  # 'E' = event, 'M' = measurement, 'D' = debug
        reading.write_log()
        ## Write display log entries
        global sample_log
        global bottle_num
        global sample_pacing
        pacing_units = setup_read("M1 Units")
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
    # stage, flow pairs (in, cfs)
	 # Site: Del Dios
	 # Date: 12/02/2022
    STAGETBL = ((00.00,00.09),
(00.10,00.10),
(00.20,00.10),
(00.30,00.11),
(00.40,00.11),
(00.50,00.12),
(00.60,00.12),
(00.70,00.13),
(00.80,00.13),
(00.90,00.13),
(01.00,00.14),
(01.10,00.14),
(01.20,00.15),
(01.30,00.15),
(01.40,00.16),
(01.50,00.16),
(01.60,00.16),
(01.70,00.17),
(01.80,00.17),
(01.90,00.18),
(02.00,00.18),
(02.10,00.19),
(02.20,00.19),
(02.30,00.20),
(02.40,00.20),
(02.50,00.22),
(02.60,00.23),
(02.70,00.25),
(02.80,00.27),
(02.90,00.29),
(03.00,00.32),
(03.10,00.34),
(03.20,00.36),
(03.30,00.38),
(03.40,00.41),
(03.50,00.43),
(03.60,00.46),
(03.70,00.49),
(03.80,00.51),
(03.90,00.54),
(04.00,00.57),
(04.10,00.59),
(04.20,00.62),
(04.30,00.66),
(04.40,00.69),
(04.50,00.72),
(04.60,00.76),
(04.70,00.80),
(04.80,00.84),
(04.90,00.88),
(05.00,00.91),
(05.10,00.95),
(05.20,00.99),
(05.30,01.03),
(05.40,01.08),
(05.50,01.13),
(05.60,01.18),
(05.70,01.23),
(05.80,01.28),
(05.90,01.33),
(06.00,01.39),
(06.10,01.44),
(06.20,01.50),
(06.30,01.56),
(06.40,01.62),
(06.50,01.68),
(06.60,01.74),
(06.70,01.81),
(06.80,01.88),
(06.90,01.94),
(07.00,02.02),
(07.10,02.09),
(07.20,02.16),
(07.30,02.24),
(07.40,02.31),
(07.50,02.39),
(07.60,02.46),
(07.70,02.55),
(07.80,02.63),
(07.90,02.72),
(08.00,02.81),
(08.10,02.90),
(08.20,02.99),
(08.30,03.08),
(08.40,03.18),
(08.50,03.27),
(08.60,03.37),
(08.70,03.47),
(08.80,03.57),
(08.90,03.67),
(09.00,03.77),
(09.10,03.88),
(09.20,03.99),
(09.30,04.10),
(09.40,04.21),
(09.50,04.32),
(09.60,04.43),
(09.70,04.55),
(09.80,04.67),
(09.90,04.79),
(10.00,04.91),
(10.10,05.03),
(10.20,05.15),
(10.30,05.28),
(10.40,05.40),
(10.50,05.53),
(10.60,05.66),
(10.70,05.79),
(10.80,05.93),
(10.90,06.07),
(11.00,06.21),
(11.10,06.35),
(11.20,06.50),
(11.30,06.65),
(11.40,06.79),
(11.50,06.94),
(11.60,07.09),
(11.70,07.25),
(11.80,07.43),
(11.90,07.60),
(12.00,07.77),
(12.10,07.93),
(12.20,08.10),
(12.30,08.27),
(12.40,08.43),
(12.50,08.59),
(12.60,08.75),
(12.70,08.93),
(12.80,09.11),
(12.90,09.29),
(13.00,09.48),
(13.10,09.65),
(13.20,09.83),
(13.30,10.02),
(13.40,10.21),
(13.50,10.40),
(13.60,10.60),
(13.70,10.79),
(13.80,10.96),
(13.90,11.17),
(14.00,11.38),
(14.10,11.61),
(14.20,11.85),
(14.30,12.06),
(14.40,12.27),
(14.50,12.48),
(14.60,12.69),
(14.70,12.90),
(14.80,13.10),
(14.90,13.32),
(15.00,13.55),
(15.10,13.77),
(15.20,13.96),
(15.30,14.17),
(15.40,14.40),
(15.50,14.69),
(15.60,14.95),
(15.70,15.20),
(15.80,15.45),
(15.90,15.70),
(16.00,15.95),
(16.10,16.20),
(16.20,16.45),
(16.30,16.72),
(16.40,16.98),
(16.50,17.23),
(16.60,17.50),
(16.70,17.75),
(16.80,18.03),
(16.90,18.28),
(17.00,18.56),
(17.10,18.83),
(17.20,19.11),
(17.30,19.39),
(17.40,19.69),
(17.50,19.97),
(17.60,20.25),
(17.70,20.53),
(17.80,20.81),
(17.90,21.11),
(18.00,21.41),
(18.10,21.72),
(18.20,22.00),
(18.30,22.31),
(18.40,22.63),
(18.50,22.94),
(18.60,23.25),
(18.70,23.56),
(18.80,23.88),
(18.90,24.19),
(19.00,24.50),
(19.10,24.84),
(19.20,25.18),
(19.30,25.54),
(19.40,25.89),
(19.50,26.29),
(19.60,26.67),
(19.70,27.04),
(19.80,27.39),
(19.90,27.79),
(20.00,28.25),
(20.10,28.67),
(20.20,29.08),
(20.30,29.50),
(20.40,29.95),
(20.50,30.41),
(20.60,30.86),
(20.70,31.32),
(20.80,31.77),
(20.90,32.23),
(21.00,32.68),
(21.10,33.14),
(21.20,33.59),
(21.30,34.05),
(21.40,34.50),
(21.50,34.96),
(21.60,35.43),
(21.70,35.90),
(21.80,36.37),
(21.90,36.84),
(22.00,37.31),
(22.10,37.78),
(22.20,38.26),
(22.30,38.73),
(22.40,39.20),
(22.50,39.67),
(22.60,40.15),
(22.70,40.65),
(22.80,41.15),
(22.90,41.65),
(23.00,42.15),
(23.10,42.65),
(23.20,43.15),
(23.30,43.65),
(23.40,44.15),
(23.50,44.65),
(23.60,45.16),
(23.70,45.71),
(23.80,46.25),
(23.90,46.79),
(24.00,47.34),
(24.10,47.88),
(24.20,48.42),
(24.30,48.97),
(24.40,49.51),
(24.50,50.06),
(24.60,50.65),
(24.70,51.24),
(24.80,51.82),
(24.90,52.41),
(25.00,53.00),
(25.10,53.59),
(25.20,54.18),
(25.30,54.77),
(25.40,55.36),
(25.50,55.96),
(25.60,56.57),
(25.70,57.17),
(25.80,57.77),
(25.90,58.37),
(26.00,58.98),
(26.10,59.58),
(26.20,60.19),
(26.30,60.82),
(26.40,61.46),
(26.50,62.09),
(26.60,62.72),
(26.70,63.35),
(26.80,63.99),
(26.90,64.62),
(27.00,65.27),
(27.10,65.95),
(27.20,66.62),
(27.30,67.30),
(27.40,67.97),
(27.50,68.65),
(27.60,69.32),
(27.70,70.00),
(27.80,70.67),
(27.90,71.33),
(28.00,72.00),
(28.10,72.67),
(28.20,73.33),
(28.30,74.00),
(28.40,74.67),
(28.50,75.36),
(28.60,76.07),
(28.70,76.79),
(28.80,77.50),
(28.90,78.21),
(29.00,78.93),
(29.10,79.64),
(29.20,80.36),
(29.30,81.07),
(29.40,81.79),
(29.50,82.50),
(29.60,83.24),
(29.70,83.97),
(29.80,84.71),
(29.90,85.46),
(30.00,86.21),
(30.10,86.97),
(30.20,87.73),
(30.30,88.49),
(30.40,89.24),
(30.50,90.00),
(30.60,90.79),
(30.70,91.59),
(30.80,92.38),
(30.90,93.18),
(31.00,93.97),
(31.10,94.76),
(31.20,95.54),
(31.30,96.31),
(31.40,97.08),
(31.50,97.85),
(31.60,98.62),
(31.70,99.39),
(31.80,100.17),
(31.90,101.01),
(32.00,101.85),
(32.10,102.69),
(32.20,103.53),
(32.30,104.37),
(32.40,105.21),
(32.50,106.05),
(32.60,106.89),
(32.70,107.73),
(32.80,108.57),
(32.90,109.41),
(33.00,110.27),
(33.10,111.15),
(33.20,112.04),
(33.30,112.92),
(33.40,113.81),
(33.50,114.69),
(33.60,115.58),
(33.70,116.46),
(33.80,117.35),
(33.90,118.23),
(34.00,119.12),
(34.10,120.00),
(34.20,120.92),
(34.30,121.85),
(34.40,122.77),
(34.50,123.69),
(34.60,124.62),
(34.70,125.54),
(34.80,126.48),
(34.90,127.43),
(35.00,128.38),
(35.10,129.33),
(35.20,130.29),
(35.30,131.26),
(35.40,132.23),
(35.50,133.20),
(35.60,134.18),
(35.70,135.15),
(35.80,136.12),
(35.90,137.09),
(36.00,138.06),
(36.10,139.03),
(36.20,140.00),
(36.30,141.16),
(36.40,142.33),
(36.50,143.49),
(36.60,144.65),
(36.70,145.81),
(36.80,146.98),
(36.90,148.14),
(37.00,149.30),
(37.10,150.42),
(37.20,151.47),
(37.30,152.53),
(37.40,153.58),
(37.50,154.63),
(37.60,155.68),
(37.70,156.74),
(37.80,157.79),
(37.90,158.84),
(38.00,159.90),
(38.10,161.01),
(38.20,162.14),
(38.30,163.26),
(38.40,164.38),
(38.50,165.51),
(38.60,166.63),
(38.70,167.75),
(38.80,168.88),
(38.90,170.00),
(39.00,171.16),
(39.10,172.33),
(39.20,173.49),
(39.30,174.65),
(39.40,175.81),
(39.50,176.98),
(39.60,178.14),
(39.70,179.30),
(39.80,180.39),
(39.90,181.37),
(40.00,182.34),
(40.10,183.32),
(40.20,184.29),
(40.30,185.27),
(40.40,186.24),
(40.50,187.22),
(40.60,188.20),
(40.70,189.17),
(40.80,190.15),
(40.90,191.12),
(41.00,192.10),
(41.10,193.07),
(41.20,194.05),
(41.30,195.02),
(41.40,196.00),
(41.50,196.98),
(41.60,197.95),
(41.70,198.93),
(41.80,199.90),
(41.90,200.77),
(42.00,201.63),
(42.10,202.48),
(42.20,203.34),
(42.30,204.20),
(42.40,205.05),
(42.50,205.91),
(42.60,206.76),
(42.70,207.62),
(42.80,208.48),
(42.90,209.33),
(43.00,210.19),
(43.10,211.04),
(43.20,211.90),
(43.30,212.76),
(43.40,213.61),
(43.50,214.47),
(43.60,215.32),
(43.70,216.18),
(43.80,217.04),
(43.90,217.89),
(44.00,218.75),
(44.10,219.60),
(44.20,220.46),
(44.30,221.32),
(44.40,222.19),
(44.50,223.14),
(44.60,224.08),
(44.70,225.03),
(44.80,225.98),
(44.90,226.93),
(45.00,227.87),
(45.10,228.82),
(45.20,229.77),
(45.30,230.72),
(45.40,231.66),
(45.50,232.61),
(45.60,233.56),
(45.70,234.51),
(45.80,235.45),
(45.90,236.40),
(46.00,237.35),
(46.10,238.30),
(46.20,239.24),
(46.30,240.20),
(46.40,241.21),
(46.50,242.21),
(46.60,243.21),
(46.70,244.22),
(46.80,245.22),
(46.90,246.23),
(47.00,247.23),
(47.10,248.23),
(47.20,249.24),
(47.30,250.24),
(47.40,251.25),
(47.50,252.25),
(47.60,253.26),
(47.70,254.26),
(47.80,255.26),
(47.90,256.27),
(48.00,257.27),
(48.10,258.28),
(48.20,259.28),
(48.30,260.29),
(48.40,261.29),
(48.50,262.29),
(48.60,263.30),
(48.70,264.35),
(48.80,265.51),
(48.90,266.67),
(49.00,267.83),
(49.10,268.99),
(49.20,270.15),
(49.30,271.30),
(49.40,272.46),
(49.50,273.62),
(49.60,274.78),
(49.70,275.94),
(49.80,277.10),
(49.90,278.26),
(50.00,279.42),
(50.10,280.50),
(50.20,281.49),
(50.30,282.48),
(50.40,283.47),
(50.50,284.46),
(50.60,285.45),
(50.70,286.44),
(50.80,287.43),
(50.90,288.42),
(51.00,289.41),
(51.10,290.40),
(51.20,291.39),
(51.30,292.38),
(51.40,293.37),
(51.50,294.36),
(51.60,295.35),
(51.70,296.34),
(51.80,297.33),
(51.90,298.32),
(52.00,299.31),
(52.10,300.31),
(52.20,301.33),
(52.30,302.35),
(52.40,303.37),
(52.50,304.39),
(52.60,305.41),
(52.70,306.43),
(52.80,307.45),
(52.90,308.47),
(53.00,309.49),
(53.10,310.54),
(53.20,311.61),
(53.30,312.69),
(53.40,313.76),
(53.50,314.84),
(53.60,315.91),
(53.70,316.99),
(53.80,318.07),
(53.90,319.14),
(54.00,320.20),
(54.10,321.21),
(54.20,322.21),
(54.30,323.22),
(54.40,324.22),
(54.50,325.23),
(54.60,326.23),
(54.70,327.24),
(54.80,328.24),
(54.90,329.25),
(55.00,330.25),
(55.10,331.26),
(55.20,332.26),
(55.30,333.27),
(55.40,334.27),
(55.50,335.28),
(55.60,336.28),
(55.70,337.29),
(55.80,338.29),
(55.90,339.30),
(56.00,340.30),
(56.10,341.28),
(56.20,342.27),
(56.30,343.25),
(56.40,344.24),
(56.50,345.23),
(56.60,346.21),
(56.70,347.20),
(56.80,348.18),
(56.90,349.17),
(57.00,350.16),
(57.10,351.14),
(57.20,352.13),
(57.30,353.11),
(57.40,354.10),
(57.50,355.09),
(57.60,356.07),
(57.70,357.06),
(57.80,358.04),
(57.90,359.03),
(58.00,360.01),
(58.10,00.00),
(58.20,00.00),
(58.30,00.00),
(58.40,00.00),
(58.50,00.00),
(58.60,00.00),
(58.70,00.00),
(58.80,00.00),
(58.90,00.00),
(59.00,00.00),
(59.10,00.00),
(59.20,00.00),
(59.30,00.00),
(59.40,00.00),
(59.50,00.00),
(59.60,00.00),
(59.70,00.00),
(59.80,00.00),
(59.90,00.00),
(60.00,00.00),
(60.10,00.00),
(60.20,00.00),
(60.30,00.00),
(60.40,00.00),
(60.50,00.00),
(60.60,00.00),
(60.70,00.00),
(60.80,00.00),
(60.90,00.00),
(61.00,00.00),
(61.10,00.00),
(61.20,00.00),
(61.30,00.00),
(61.40,00.00),
(61.50,00.00),
(61.60,00.00),
(61.70,00.00),
(61.80,00.00),
(61.90,00.00),
(62.00,00.00),
(62.10,00.00),
(62.20,00.00),
(62.30,00.00),
(62.40,00.00),
(62.50,00.00),
(62.60,00.00),
(62.70,00.00),
(62.80,00.00),
(62.90,00.00),
(63.00,00.00),
(63.10,00.00),
(63.20,00.00),
(63.30,00.00),
(63.40,00.00),
(63.50,00.00),
(63.60,00.00),
(63.70,00.00),
(63.80,00.00),
(63.90,00.00),
(64.00,00.00),
(64.10,00.00),
(64.20,00.00),
(64.30,00.00),
(64.40,00.00),
(64.50,00.00),
(64.60,00.00),
(64.70,00.00),
(64.80,00.00),
(64.90,00.00),
(65.00,00.00),
(65.10,00.00),
(65.20,00.00),
(65.30,00.00),
(65.40,00.00),
(65.50,00.00),
(65.60,00.00),
(65.70,00.00),
(65.80,00.00),
(65.90,00.00),
(66.00,00.00),
(66.10,00.00),
(66.20,00.00),
(66.30,00.00),
(66.40,00.00),
(66.50,00.00),
(66.60,00.00),
(66.70,00.00),
(66.80,00.00),
(66.90,00.00),
(67.00,00.00),
(67.10,00.00),
(67.20,00.00),
(67.30,00.00),
(67.40,00.00),
(67.50,00.00),
(67.60,00.00),
(67.70,00.00),
(67.80,00.00),
(67.90,00.00),
(68.00,00.00),
(68.10,00.00),
(68.20,00.00),
(68.30,00.00),
(68.40,00.00),
(68.50,00.00),
(68.60,00.00),
(68.70,00.00),
(68.80,00.00),
(68.90,00.00),
(69.00,00.00),
(69.10,00.00),
(69.20,00.00),
(69.30,00.00),
(69.40,00.00),
(69.50,00.00),
(69.60,00.00),
(69.70,00.00),
(69.80,00.00),
(69.90,00.00),
(70.00,00.00),
(70.10,00.00),
(70.20,00.00),
(70.30,00.00),
(70.40,00.00),
(70.50,00.00),
(70.60,00.00),
(70.70,00.00),
(70.80,00.00),
(70.90,00.00),
(71.00,00.00),
(71.10,00.00),
(71.20,00.00),
(71.30,00.00),
(71.40,00.00),
(71.50,00.00),
(71.60,00.00),
(71.70,00.00),
(71.80,00.00),
(71.90,00.00))

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
def display_sample_pacing(input):
    global sample_pacing
    smaple_pacing = float(gp_read_value_by_label("sample_pacing"))
    print ('Sample Pacing: '+str(sample_pacing))
    return sample_pacing

@MEASUREMENT
def display_bottle_num(input):
    global bottle_num
    bottle_num = float(gp_read_value_by_label("bottle_num"))
    print ('Bottle number: '+str(bottle_num))
    return bottle_num

@MEASUREMENT
def number_of_aliquots(input):
    global aliquots_in_bottle
    print ('Number of aliquots in bottle: '+str(aliquots_in_bottle))
    return aliquots_in_bottle

@TASK
def turn_on_sampling():
    print("Started sampling!")
    for i in [i for i in range(5,14,1)]:
        setup_write("!M"+str(i)+" meas interval", "00:01:00")
    # Start sampling when level triggered
    gp_write_value_by_label("sampling_on", 1)  # 1=True

    ## Reset all params for start of event
    global sample_pacing
    global g_running_total
    global bottle_num
    global aliquots_in_bottle
    global vol_in_bottle
    ## get pacing
    sample_pacing = float(gp_read_value_by_label("sample_pacing")) # SamplePacin is GenPurp variables

    ## Reset parameters for event
    ## Check if program is flow weighted
    pacing_weighting = get_pacing_weighting()
    # Running total increment (time or volume)
    if pacing_weighting == "FLOW":
        g_running_total = 0.0  # start at 0 and count up to pacing
    if pacing_weighting == "TIME":
        g_running_total = sample_pacing  # start at time pacing and count down
    bottle_num = float(setup_read("M2 Offset"))
    aliquots_in_bottle = 0
    vol_in_bottle = 0
    return

@TASK
def turn_off_sampling():
    print ("Stopped sampling")
    # Stop sampling when level triggered
    gp_write_value_by_label("sampling_on", 0)  # 0=False
    ## Set data collection back to 5 min
    for i in [i for i in range(5, 14, 1)]:
        setup_write("!M" + str(i) + " meas interval", "00:05:00")

@TASK
def reset_sampling_params():
    print("Manually reset sampling parameters!")

    ## Reset all params for start of event
    global sample_pacing
    global g_running_total
    global bottle_num
    global aliquots_in_bottle
    global vol_in_bottle

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

    aliquots_in_bottle = 0
    vol_in_bottle = 0

    # Sample log
    sample_log = {'SampleEvent': {'IncrTotal': '', 'Bottle#': '', 'Aliquot#': '', 'SampleTime': ''}}
    return
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

@TXFORMAT
def adafruit_io(standard):
    #data_json = '{"datum":{"value":11}}'
    data_json = ''
    return data_json

