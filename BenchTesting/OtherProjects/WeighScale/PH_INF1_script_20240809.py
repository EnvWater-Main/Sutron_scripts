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
    # stage, flow pairs
    STAGETBL = (
   (0.0, 0.0),
(0.2, 0.008),
(0.4, 0.022),
(0.6, 0.04),
(0.8, 0.061),
(1.0, 0.085),
(1.2, 0.112),
(1.4, 0.14),
(1.6, 0.172),
(1.8, 0.204),
(2.0, 0.237),
(2.2, 0.274),
(2.4, 0.311),
(2.6, 0.349),
(2.8, 0.388),
(3.0, 0.43),
(3.2, 0.472),
(3.4, 0.515),
(3.6, 0.56),
(3.8, 0.605),
(4.0, 0.651),
(4.2, 0.7),
(4.4, 0.747),
(4.6, 0.794),
(4.8, 0.846),
(5.0, 0.896),
(5.2, 0.946),
(5.4, 1.0),
(5.6, 1.051),
(5.8, 1.104),
(6.0, 1.158),
(6.2, 1.213),
(6.4, 1.267),
(6.6, 1.323),
(6.8, 1.378),
(7.0, 1.433),
(7.2, 1.492),
(7.4, 1.549),
(7.6, 1.605),
(7.8, 1.662),
(8.0, 1.723),
(8.2, 1.78),
(8.4, 1.839),
(8.6, 1.9),
(8.8, 1.959),
(9.0, 2.018),
(9.2, 2.08),
(9.4, 2.139),
(9.6, 2.199),
(9.8, 2.262),
(10.0, 2.322),
(10.2, 2.382),
(10.4, 2.446),
(10.6, 2.507),
(10.8, 2.567),
(11.0, 2.725),
(11.2, 2.786),
(11.4, 2.848),
(11.6, 2.909),
(11.8, 2.97),
(12.0, 3.032),
(12.2, 3.133),
(12.4, 3.235),
(12.6, 3.345),
(12.8, 3.438),
(13.0, 3.532),
(13.2, 3.669),
(13.4, 3.807),
(13.6, 3.96),
(13.8, 4.13),
(14.0, 4.299),
(14.2, 4.497),
(14.4, 4.694),
(14.6, 4.934),
(14.8, 5.215),
(15.0, 5.508),
(15.2, 5.813),
(15.4, 6.118),
(15.6, 6.455),
(15.8, 6.824),
(16.0, 7.192),
(16.2, 7.48),
(16.4, 7.769),
(16.6, 8.195),
(16.8, 8.699),
(17.0, 9.203),
(17.2, 9.543),
(17.4, 9.883),
(17.6, 10.223),
(17.8, 10.537),
(18.0, 10.851),
(18.2, 11.166),
(18.4, 11.443),
(18.6, 11.683),
(18.8, 11.923),
(19.0, 12.163),
(19.2, 12.514),
(19.4, 12.866),
(19.6, 13.217),
(19.8, 13.594),
(20.0, 13.997),
(20.2, 14.399),
(20.4, 14.802),
(20.6, 15.174),
(20.8, 15.517),
(21.0, 15.859),
(21.2, 16.202),
(21.4, 16.563),
(21.6, 16.943),
(21.8, 17.323),
(22.0, 17.703),
(22.2, 18.085),
(22.4, 18.47),
(22.6, 18.855),
(22.8, 19.24),
(23.0, 19.684),
(23.2, 20.186),
(23.4, 20.688),
(23.6, 21.191),
(23.8, 21.693),
(24.0, 22.183),
(24.2, 22.673),
(24.4, 23.163),
(24.6, 23.653),
(24.8, 24.143),
(25.0, 24.725),
(25.2, 25.307),
(25.4, 25.889),
(25.6, 26.472),
(25.8, 26.965),
(26.0, 27.369),
(26.2, 27.773),
(26.4, 28.177),
(26.6, 28.581),
(26.8, 28.973),
(27.0, 29.353),
(27.2, 29.733),
(27.4, 30.113),
(27.6, 30.493),
(27.8, 30.873),
(28.0, 31.253),
(28.2, 31.805),
(28.4, 32.358),
(28.6, 32.91),
(28.8, 33.463),
(29.0, 33.865),
(29.2, 34.266),
(29.4, 34.668),
(29.6, 35.07),
(29.8, 35.472)
   )

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
