# -*- coding: utf-8 -*-
"""
Created on Wed Feb 12 14:37:28 2020

@author: alex.messina
"""

import pandas as pd
from matplotlib import pyplot as plt
import datetime as dt
## Set Pandas display options
pd.set_option('display.large_repr', 'truncate')
pd.set_option('display.width', 180)
pd.set_option('display.max_rows', 40)
pd.set_option('display.max_columns', 13)
plt.ion()

#site = 'DELDIOS'
#site = 'FELICITA'
#site = 'KITCARSON'
site = 'CLOVERDALE'
#site = 'GREENVALLEY'
#site = 'MOONSONG'
#site = 'SDG_CRK'


datadir = 'C:/Users/alex.messina/Documents/GitHub/Sutron_scripts/Data Download/'
filename = 'LakeHodges_'+site+'_log_20200312.csv'

rating_curves = pd.ExcelFile(datadir+'Current_RatingCurves.xlsx')
rating_curve = rating_curves.parse(sheetname='4. San Dieguito',skiprows=1,header=0)
rating_curve = rating_curve.round(2)
rating_curve.index = rating_curve['Stage (in)']

STAGETBL = zip(rating_curve['Stage (in)'].values,rating_curve['Q Total (cfs)'].values)
    
for i in STAGETBL:
    print str((float('%.2f'%i[0]), float('%.2f'%i[1])))+','


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
    ## DelDios
    #STAGETBL = ((0, 0), (18.33, 56.6), (28.60, 22), (36.22, 42), (44.77, 92), (51.04, 243), (57.09, 500), (63.16, 900), (70.13, 1317))
    
    ## Felicita
    #STAGETBL = ((0, 0), (18.33, 56.6), (28.60, 22), (36.22, 42), (44.77, 92), (51.04, 243), (57.09, 500),(63.16, 900), (70.13, 1317))
    
    STAGETBL = zip(rating_curve['Stage (in)'].values,rating_curve['Q Total (cfs)'].values)
    
    # Test for out of bounds stage values
    if stage_in < STAGETBL[0][0]:  # below
        flow_cfs = STAGETBL[0][0]
    elif stage_in > STAGETBL[-1][0]:  # above
        #flow_cfs = -99.99 #error value
        flow_cfs = STAGETBL[-1][0] #max value
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
#    print ("")
#    print("Flow: {}".format("%.3f"%flow_cfs))
#    print("Stage: {}".format("%.2f"%stage_in))
#    print("")
    return flow_cfs

#%%

df_all = pd.DataFrame.from_csv(datadir+filename,header=5).reset_index()
df_all.columns=['Param','Date','Time','Result','Quality']
df_all['Datetime'] = df_all['Date']+' '+df_all['Time']

level = df_all[df_all['Param']=='PT Level'][['Datetime','Result']]
level['Datetime'] = pd.to_datetime(level['Datetime'])
level = level.set_index('Datetime')
level['Result'] = level['Result'].astype('float')

flow = pd.DataFrame(level['Result'].apply(lambda x: rating_table(float(x))),columns=['Result'])


#%%
fig, ax1 = plt.subplots(1,1,figsize=(16,8))
fig.suptitle(filename,fontsize=14,fontweight='bold')

ax1.plot_date(level.index,level['Result'],ls='-',marker='None',c='r',label='Water Level from PT')
ax1.set_ylabel('Water Level (inches)',color='r',fontsize=14,fontweight='bold')
ax1.spines['left'].set_color('r')
ax1.tick_params(axis='y',colors='r',labelsize=14)
ax1.xaxis.set_major_formatter(mpl.dates.DateFormatter('%A \n %m/%d/%y %H:%M'))

# Delineate alarms
#ax1.axvline(alarm_in.index[0],c='g')
#ax1.axvline(alarm_out.index[0],c='r')



ax2 = ax1.twinx()
ax2.plot_date(flow.index,flow['Result'],ls='-',marker='None',c='b',label='Flow from HvF')
ax2.plot_date(aliquots.index,aliquots['Flow'],ls='None',marker='o',c='k',label='Aliquots')
for al in aliquots.iterrows():
    print al
    al_num = "%.0f"%al[1]['Result']
    ax2.annotate(al_num,xy=(pd.to_datetime(al[0]),al[1]['Flow']*1.1),ha='center')

ax2.set_ylabel('Flow (cfs)',color='b',fontsize=14,fontweight='bold')
ax2.spines['right'].set_color('b')
ax2.tick_params(axis='y',colors='b',labelsize=14)


ax1.legend(fontsize=14,ncol=1,loc='upper left')
ax2.legend(fontsize=14,loc='upper right')

plt.tight_layout()
plt.subplots_adjust(top=0.95)

#%%








