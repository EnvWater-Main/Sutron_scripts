# -*- coding: utf-8 -*-
"""
Created on Wed Mar 04 15:32:59 2020

@author: alex.messina
"""

def rating_table(stage_in):
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
    STAGETBL = ((0, 0), (1, 5), (3, 22), (5, 42), (7, 92), (9, 243), (11, 500),
                (13, 900), (15, 1317), (17, 1876), (19, 2504), (21, 3202),
                (23, 3958), (25, 4773), (27, 5650), (29, 6587), (31, 7583),
                (33, 8635), (35, 9743), (37, 10903), (39, 12119), (41, 13389),
                (43, 14717), (45, 16103), (47, 17547), (51, 20607), (55, 23895),
                (59, 27393), (61, 29219), (65, 33011), (69, 37019), (73, 41287))
    # Test for out of bounds stage values
    if stage_in < STAGETBL[0][0]:  # below
        flow_cfs = STAGETBL[0][0]
    elif stage_in > STAGETBL[-1][0]:  # above
        flow_cfs = -99.99
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
        flow_cfs = a_flow1 + (b_diff_stage / (c_stage2 - d_stage1)) * (e_flow2 - a_flow1)
    print ("")
    print("Flow: {}".format("%.3f"%flow_cfs))
    print("Stage: {}".format("%.2f"%stage_in))
    print("")
    return flow_cfs