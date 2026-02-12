from sl3 import *
import utime
import math
from serial import Serial
from time import sleep, time, localtime
from os import ismount, exists, mkdir, rename, statvfs
from binascii import crc32

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
if pacing_mode == "FLOW":
    g_running_total = 0.0 # start at 0 and count up to pacing
elif pacing_mode == "TIME":
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
    #power_control('SW1', True)
    #utime.sleep(0.5)
    #power_control('SW1', False)

    # Digital Out 1 - NEEDS TO BE USED WITH RELAY OR PULL-UP RESISTOR
    output_control('OUTPUT1', True)
    utime.sleep(0.5)
    output_control('OUTPUT1', False)

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
                (100.0, 100))

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
    if pacing_mode == "FLOW":
        g_running_total = 0.0  # start at 0 and count up to pacing
    if pacing_mode == "TIME":
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
