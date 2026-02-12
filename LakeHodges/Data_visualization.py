# -*- coding: utf-8 -*-
"""
Created on Wed Feb 12 14:37:28 2020

@author: alex.messina
"""

import pandas as pd
from matplotlib import pyplot as plt
import datetime as dt
from Rating_curve import *
## Set Pandas display options
pd.set_option('display.large_repr', 'truncate')
pd.set_option('display.width', 180)
pd.set_option('display.max_rows', 40)
pd.set_option('display.max_columns', 13)
plt.ion()


#
site_list = ['KITCARSON']
site_list = ['DELDIOS']
#site_list = ['FELICITA']
site_list = ['CLOVERDALE']
site_list = ['GUEJITO']
#site_list = ['SYCAMORE']
#site_list = ['MOONSONG']
#site_list = ['SDGCRK']
site_list = ['GREENVALLEY']
use_recorded_flow = True
use_recorded_flow = False

#site_list = ['DELDIOS', 'FELICITA', 'KITCARSON','GREENVALLEY', 'MOONSONG','CLOVERDALE','GUEJITO','SYCAMORE','SDGCRK']

for site in site_list:
    print site
    datadir = 'C:/Users/alex.messina/Documents/GitHub/Sutron_scripts/Data Download/Log backup 5_11_2020/'
    filename = 'LakeHodges_'+site+'_log_20200511.csv'
    
    #%%
    
    df_all = pd.DataFrame.from_csv(datadir+filename,header=8).reset_index()
    df_all.columns=['Date','Time','Param','Result','Units','Quality']
    df_all['Datetime'] = df_all['Date'].astype('str')+' '+df_all['Time']
    
    if site == 'GREENVALLEY':
        # North Pipe
        level_north = df_all[df_all['Param'].isin(['PT Level No','PT North'])][['Datetime','Result']]
        level_north['Datetime'] = pd.to_datetime(level_north['Datetime'])
        level_north = level_north.drop_duplicates(subset=['Datetime']).set_index('Datetime')
        # South Pipe
        level_south = df_all[df_all['Param'].isin(['PT Level So','PT South'])][['Datetime','Result']]
        level_south['Datetime'] = pd.to_datetime(level_south['Datetime'])
        level_south = level_south.drop_duplicates(subset=['Datetime']).set_index('Datetime')
        
    else:
        level = df_all[df_all['Param']=='PT Level'][['Datetime','Result']]
        level['Datetime'] = pd.to_datetime(level['Datetime'])
        level = level.drop_duplicates(subset=['Datetime']).set_index('Datetime')
        
    if use_recorded_flow == True:
    
    ## recorded data
        flow = df_all[df_all['Param']=='Flow_cfs'][['Datetime','Result']]
        flow['Datetime'] = pd.to_datetime(flow['Datetime'])
        flow = flow.drop_duplicates(subset=['Datetime']).set_index('Datetime')
    
    if use_recorded_flow == False:
        ## Rating Curve
        rating_curves = pd.ExcelFile(datadir+'Current_RatingCurves.xlsx')
        rating_curve = rating_curves.parse(sheetname=site,skiprows=1,header=0)
        rating_curve = rating_curve.round(2)
        rating_curve.index = rating_curve['Stage (in)']
        ## From rating curve
        if site == 'GREENVALLEY':
            flow_north = pd.DataFrame(level_north['Result'].apply(lambda x: rating_table(rating_curve,float(x))),columns=['Result'])
            flow_south = pd.DataFrame(level_south['Result'].apply(lambda x: rating_table(rating_curve,float(x))),columns=['Result'])
            flow = pd.DataFrame({'Flow_north_cfs':flow_north['Result'],'Flow_south_cfs':flow_south['Result']}, index=[flow_north.index])
            flow['Result'] = flow['Flow_north_cfs'] + flow['Flow_south_cfs']
            
        else:
            flow = pd.DataFrame(level['Result'].apply(lambda x: rating_table(rating_curve,float(x))),columns=['Result'])
    
    aliquots =  df_all[df_all['Param']=='Triggered S'][['Datetime','Result']]
    aliquots['Datetime'] = pd.to_datetime(aliquots['Datetime'])
    aliquots = aliquots.drop_duplicates(subset=['Datetime']).set_index('Datetime')
    if len(aliquots) >0:
        aliquots['Flow'] = flow['Result']
    
    alarm_in = df_all[df_all['Param']=='Alarm In'][['Datetime','Result']]
    alarm_in['Datetime'] = pd.to_datetime(alarm_in['Datetime'])
    alarm_in = alarm_in.drop_duplicates(subset=['Datetime']).set_index('Datetime')
    
    alarm_out = df_all[df_all['Param']=='Alarm Out'][['Datetime','Result']]
    alarm_out['Datetime'] = pd.to_datetime(alarm_out['Datetime'])
    alarm_out = alarm_out.drop_duplicates(subset=['Datetime']).set_index('Datetime')
    
#    bottle_change = df_all[df_all['Param']=='BottleChang'][['Datetime','Result']]
#    bottle_change['Datetime'] = pd.to_datetime(bottle_change['Datetime'])
#    bottle_change = bottle_change.drop_duplicates(subset=['Datetime']).set_index('Datetime')
#    bottle_change = bottle_change.append(pd.DataFrame({'Result':1},index=[alarm_in.index[0]]))
#    bottle_change = bottle_change.sort()
#    
    #%%
    fig, ax1 = plt.subplots(1,1,figsize=(16,8))
    fig.suptitle(filename,fontsize=14,fontweight='bold')
    
    ## Water Level
    if site=='GREENVALLEY' and use_recorded_flow==False:
        ax1.plot_date(level_north.index,level_north['Result'],ls='-',marker='None',c='r',label='Water Level from PT North')
        ax1.plot_date(level_south.index,level_south['Result'],ls='-',marker='None',c='g',label='Water Level from PT South')
        ax1.set_ylim(0, level_north['Result'].max()*1.25)
    else:
        ax1.plot_date(level.index,level['Result'],ls='-',marker='None',c='r',label='Water Level from PT')
        ax1.set_ylim(0, level['Result'].max()*1.25)
    ax1.set_ylabel('Water Level (inches)',color='r',fontsize=14,fontweight='bold')
    ax1.spines['left'].set_color('r')
    ax1.tick_params(axis='y',colors='r',labelsize=14)
    ax1.xaxis.set_major_formatter(mpl.dates.DateFormatter('%A \n %m/%d/%y %H:%M'))
    
    
    # Delineate alarms
    #ax1.axvline(alarm_in.index[0],c='g')
    #ax1.axvline(alarm_out.index[0],c='r')
    
    ## Flow
    ax2 = ax1.twinx()
    if site=='GREENVALLEY' and use_recorded_flow==False:
        print 'yes'
        ax2.plot_date(flow_north.index,flow_north['Result'],ls='-',marker='None',c='teal',label='Flow from HvF (north)')
        ax2.plot_date(flow_south.index,flow_south['Result'],ls='-',marker='None',c='b',alpha=0.6,label='Flow from HvF (south)')
        ax2.plot_date(flow.index,flow['Result'],ls='-',marker='None',c='b',label='Flow from HvF (Total)')
    else:
        ax2.plot_date(flow.index,flow['Result'],ls='-',marker='None',c='b',label='Flow from HvF')
    ax2.set_ylabel('Flow (cfs)',color='b',fontsize=14,fontweight='bold')
    ax2.spines['right'].set_color('b')
    ax2.tick_params(axis='y',colors='b',labelsize=14)
    
    ## Plot Aliquots
    if len(aliquots) >0:
        ax2.plot_date(aliquots.index,aliquots['Flow'],ls='None',marker='o',c='k',label='Aliquots')
        for al in aliquots.iterrows():
            print al
            al_num = "%.0f"%al[1]['Result']
            ax2.annotate(al_num,xy=(pd.to_datetime(al[0]),al[1]['Flow']*1.05),ha='center')
        
    # Plot Bottle Changes
#    for b_chng in bottle_change.iterrows():
#        ax1.axvline(b_chng[0],label='Bottle: '+"%.0f"%b_chng[1]['Result'],c='grey',alpha=0.6)
#        ax1.annotate('^ Bottle '+"%.0f"%b_chng[1]['Result']+' ^',xy=(b_chng[0],5),ha='left',rotation=-90)

    ## FMT

    ax2.set_ylim(0, flow['Result'].max()*1.1)
    ax1.legend(fontsize=14,ncol=1,loc='upper left')
    ax2.legend(fontsize=14,loc='upper right')
    
    plt.tight_layout()
    plt.subplots_adjust(top=0.95)

#%% SAVE TO CSV
#    if site == 'GREENVALLEY':
#        df_out = pd.DataFrame({'Level_North_in':level_north['Result'],'Level_South_in':level_south['Result'],'Flow_North_cfs':flow_north['Result'],'Flow_South_cfs':flow_south['Result'],'Flow_cfs':flow['Result']})
#        
#    else:
#        df_out = pd.DataFrame({'Level_in':level['Result'],'Flow_cfs':flow['Result']})
#    df_out = df_out[df_out != -99999.0].dropna()
#    
#    if site == 'SDGCRK':
#        ## just get rid of data prior since it wasn't offset and doesnt matter
#        df_out.ix[:dt.datetime(2020,3,18,8,50)] = np.nan
#        df_out = df_out.dropna()
#        # shift one hour forward to match PDT
#        df_out.ix[:dt.datetime(2020,3,26,15,0)] = df_out.ix[:dt.datetime(2020,3,26,15,0)].set_index(df_out.ix[:dt.datetime(2020,3,26,15,0)].index + dt.timedelta(minutes=60))
#        

        
        
#    df_out.to_csv(datadir +'just level and flow/'+ site+'_level_and_flow.csv')
    






