# -*- coding: utf-8 -*-
"""
Created on Wed Feb 12 14:37:28 2020

@author: alex.messina
"""

import pandas as pd
from matplotlib import pyplot as plt
import matplotlib as mpl
import datetime as dt
import numpy as np
import os
#from Rating_curve import *
## Set Pandas display options
pd.set_option('display.large_repr', 'truncate')
pd.set_option('display.width', 180)
pd.set_option('display.max_rows', 40)
pd.set_option('display.max_columns', 13)
plt.ion()

## Set Storm start and end
storm_start = dt.datetime(2021,3,10,0,0)
storm_end = dt.datetime(2021,3,12,23)

use_recorded_flow = True
#use_recorded_flow = False

cfs = ['ViaRancho','DELDIOS', 'FELICITA', 'KITCARSON','GREENVALLEY', 'MOONSONG','CLOVERDALE','GUEJITO','SYCAMORE','SDGCRK']
gpm = ['ElKu','Tazon','Oceans11','Lomica']

#### INDIVIDUAL SITES
#creeks
site_list = ['DELDIOS']
#site_list = ['FELICITA']
#site_list = ['KITCARSON']
#site_list = ['CLOVERDALE']
#site_list = ['GUEJITO']
#site_list = ['SDGCRK']
#site_list = ['MOONSONG']
#site_list = ['GREENVALLEY']
#site_list = ['SYCAMORE']
#outfalls
site_list = ['ElKu']
#site_list = ['ViaRancho']
#site_list = ['Tazon']
#site_list = ['Oceans11']
#site_list = ['Lomica']



## CREEKS
#site_list = ['DELDIOS', 'FELICITA', 'KITCARSON','GREENVALLEY', 'MOONSONG','CLOVERDALE','GUEJITO','SYCAMORE','SDGCRK']

## OUTFALLS
#site_list = ['ElKu','ViaRancho','Tazon','Oceans11','Lomica']


for site in site_list:
    print (site)
    #datadir = 'C:/Users/alex.messina/Documents/GitHub/Sutron_scripts/Data Download/Log backup 5_11_2020/'
    datadir = 'C:/Users/alex.messina/Documents/LinkComm/Log Files/'
    df = pd.DataFrame()
    
    ## Time Series Data
    for fname in [f for f in os.listdir(datadir) if site in f and 'loggrp' in f]:
        print (fname)
        df_ind = pd.read_csv(datadir+fname,index_col=0,header=0,skiprows=[1])
        
        ## Rename flow data column
        if site in gpm:
            flow_units = 'gpm'
            print ('Rename PT Flow to Flow_gpm')
            df_ind = df_ind.rename(columns={'PT Flow':'Flow_gpm','Flow _PT':'Flow_gpm','Flow_PT':'Flow_gpm'})
        if site in cfs:
            flow_units = 'cfs'
            print ('Rename PT Flow to Flow_cfs')
            df_ind = df_ind.rename(columns={'PT Flow':'Flow_cfs','Flow _PT':'Flow_cfs','Flow_PT':'Flow_cfs'})     
        ## Rename Level
        df_ind = df_ind.rename(columns={'PT Level':'Level_PT'})     
        
        if site=='GREENVALLEY':
            df_ind = df_ind.rename(columns={'PT North':'Level_PT_No', 'PT South':'Level_PT_So'}) 
            
        
        ## Rename other stuff
        df_ind = df_ind.rename(columns={'Aliquot_Num':'AliquotNum','Curr_pacing':'SamplePacin','FlowVolume':'Incr_Flow'})
        
        ## Combine date and time
        if 'Time' in df_ind.columns:
            df_ind.index = pd.to_datetime(df_ind.index +' '+ df_ind['Time'])  
        df_ind.index = pd.to_datetime(df_ind.index)
        ## append to df
        df = df.append(df_ind)#,sort=True)
    
    ##format df
    # Replace error values == -99999
    df = df.replace(-99999,np.nan)
    df = df.replace(-99,np.nan)
    # ensure datetime index and drop duplicates
    df.index = pd.to_datetime(df.index)
    df['Datetime'] = df.index
    df = df.drop_duplicates(subset='Datetime')
    
    # Interpolate battery level
    if 'Battery_950' in df.columns:
        df['Battery_950'] = df['Battery_950'].interpolate('linear',axis=0,limit = 13)
    
    # Interpolate data to fill gap
    for col in ['Level_950','Vel_950','Flow_950']:
        if col in df:
            df[col] = df[col].interpolate('linear',axis=0,limit=3)
            
    if site == 'Tazon':
        df['Flow_gpm'] = df['Flow_950']
        df['Level_PT'] = df['Level_950']

#    df['PT Level'].plot()
            
    ## Alarm Data
    events = pd.DataFrame()
    for fname in [f for f in os.listdir(datadir) if site in f and 'events' in f]:
        print (fname)
        df_events = pd.read_csv(datadir+fname,index_col=0,header=0,skiprows=[1])
        if 'Time' in df_ind.columns:
            df_events.index = pd.to_datetime(df_events.index +' '+ df_devents['Time'])
        ## append to df
        events = events.append(df_events,sort=True)
    # ensure datetime index and drop duplicates
    events.index = pd.to_datetime(events.index)
    events['Datetime'] = events.index
    events = events.drop_duplicates(subset='Datetime')  
    
    ## Event df's
    ## Aliquots
    aliquots = events[events['Label']=='Triggered S'][['Label','Value']]
    manual_grabs = events[events['Label']=='Trigger Man'][['Label','Value']]
    if site in gpm:
        aliquots['Flow_gpm'] = df['Flow_gpm']
    if site in cfs:
        aliquots['Flow_cfs'] = df['Flow_cfs']
    aliquots = aliquots.dropna()
    aliquots['Datetime'] = aliquots.index 
    aliquots['Time between aliquots'] = aliquots['Datetime'].diff()
    aliquots = aliquots.drop('Datetime',1)
    aliquots = aliquots.rename(columns={'Value':'Aliquot#'}) 
    aliquots['Aliquot#'] = aliquots['Aliquot#'].astype(int)
                
    
    ## Alarms
    alarm_in = events[events['Label']=='Alarm In'][['Label','Value']]
    alarm_out =  events[events['Label']=='Alarm Out'][['Label','Value']]
    ## Bottle changes
    bottle_change = events[events['Label']=='BottleChang'][['Label','Value']]

    ## 
    ## now resample to 5Min  
#    df = df.resample('1Min')#.mean()  
    
    
##%% RECALCULATE FLOWS
    if use_recorded_flow == False:
        ## Rating Curve
        rating_curves = pd.ExcelFile(datadir+'Current_RatingCurves.xlsx')
        rating_curve = rating_curves.parse(sheetname=site,skiprows=1,header=0)
        rating_curve = rating_curve.round(2)
        rating_curve.index = rating_curve['Stage (in)']
        ## From rating curve
        if site == 'GREENVALLEY':
            df['Flow_north_cfs']  = pd.DataFrame(df['Level_PT_No'].apply(lambda x: rating_table(rating_curve,float(x))),columns=['Level_PT_No'])
            df['Flow_south_cfs']  = pd.DataFrame(df['Level_PT_So'].apply(lambda x: rating_table(rating_curve,float(x))),columns=['Level_PT_So'])
            df['Flow_cfs'] = df['Flow_north_cfs'] + df['Flow_south_cfs']
        else:
            df['Flow_cfs'] = pd.DataFrame(level['Result'].apply(lambda x: rating_table(rating_curve,float(x))),columns=['Result'])
    
#%% PLOT
    fig, ax1 = plt.subplots(1,1,figsize=(16,8))
    fig.suptitle(site,fontsize=14,fontweight='bold')
    
    ## Water Level
    if site=='GREENVALLEY':
        ax1.plot_date(df.index,df['Level_PT_No'],ls='-',marker='None',c='r',label='Water Level from PT North')
        ax1.plot_date(df.index,df['Level_PT_So'],ls='-',marker='None',c='g',label='Water Level from PT South')
        ax1.set_ylim(0, df['Level_PT_No'].max()*1.25)
    else:
        ax1.plot_date(df.index,df['Level_PT'],ls='-',marker='None',c='r',label='Water Level from PT')
        ax1.set_ylim(0, df['Level_PT'].max()*1.25)
    ax1.set_ylabel('Water Level (inches)',color='r',fontsize=14,fontweight='bold')
    ax1.spines['left'].set_color('r')
    ax1.tick_params(axis='y',colors='r',labelsize=14)
    ax1.xaxis.set_major_formatter(mpl.dates.DateFormatter('%A \n %m/%d/%y %H:%M'))
   
    ## Flow
    ax2 = ax1.twinx()
    if site=='GREENVALLEY' and use_recorded_flow==False:
        print ('GREEN VALLEY recalculated flows')
        ax2.plot_date(df.index,df['Flow_north_cfs'] ,ls='-',marker='None',c='teal',label='Flow from HvF (north)')
        ax2.plot_date(df.index,df['Flow_south_cfs'] ,ls='-',marker='None',c='b',alpha=0.6,label='Flow from HvF (south)')
        ax2.plot_date(df.index,df['Flow_cfs'],ls='-',marker='None',c='b',label='Flow from HvF (Total)')
    else:
        if site in cfs:
            ax2.plot_date(df.index,df['Flow_cfs'],ls='-',marker='None',c='b',label='Flow from HvF')
            ax2.set_ylabel('Flow (cfs)',color='b',fontsize=14,fontweight='bold')
            ## Plot Aliquots
            if len(aliquots) >0:
                ax2.plot_date(aliquots.index,aliquots['Flow_cfs'],ls='None',marker='o',c='k',label='Aliquots')
                for al in aliquots.iterrows():
                    #print (al)
                    al_num = "%.0f"%al[1]['Aliquot#']
                    ax2.annotate(al_num,xy=(pd.to_datetime(al[0]),al[1]['Flow_cfs']*1.05),ha='center')
            
        if site in gpm:
            ax2.plot_date(df.index,df['Flow_gpm'],ls='-',marker='None',c='b',label='Flow from HvF')
            ax2.set_ylabel('Flow (gpm)',color='b',fontsize=14,fontweight='bold')
            ax2.set_ylim(0, df['Flow_gpm'].max()*1.1)
            ## Plot Aliquots
            if len(aliquots) >0:
                ax2.plot_date(aliquots.index,aliquots['Flow_gpm'],ls='None',marker='o',c='k',label='Aliquots')
                for al in aliquots.iterrows():
                    #print (al)
                    al_num = "%.0f"%al[1]['Aliquot#']
                    ax2.annotate(al_num,xy=(pd.to_datetime(al[0]),al[1]['Flow_gpm']*1.05),ha='center')
    ax2.xaxis.set_major_formatter(mpl.dates.DateFormatter('%A \n %m/%d/%y %H:%M'))  
    # Plot Bottle Changes
    for b_chng in bottle_change.iterrows():
        ax1.axvline(b_chng[0],label='Bottle: '+"%.0f"%b_chng[1]['Value'],c='grey',alpha=0.6)
        ax1.annotate('^ Bottle '+"%.0f"%b_chng[1]['Value']+' ^',xy=(b_chng[0],5),ha='left',rotation=-90)

    ## FMT      
    ax2.spines['right'].set_color('b')
    ax2.tick_params(axis='y',colors='b',labelsize=14)
    
    ax1.legend(fontsize=14,ncol=1,loc='upper left')
    ax2.legend(fontsize=14,loc='upper right')
    
    plt.tight_layout()
    plt.subplots_adjust(top=0.95)
    
    ## Zoom to storm
    ax1.set_xlim(storm_start,storm_end)
    if site == 'GREENVALLEY':
        ax1.set_ylim(0, df.loc[storm_start:storm_end,'Level_PT_No'].max()*1.25)
    else:
        ax1.set_ylim(0, df.loc[storm_start:storm_end,'Level_PT'].max()*1.25)
    ax2.set_ylim(0, df.loc[storm_start:storm_end,'Flow_'+flow_units].max()*1.1)
    
    print (aliquots[storm_start:storm_end])
    print ('Minimum time between aliquots: '+ str(aliquots.loc[storm_start:storm_end,'Time between aliquots'].min()))
    
    print ('Peak flow rate: ' + "%.2f"%df.loc[storm_start:storm_end,'Flow_'+flow_units].max() + flow_units)
    if site == 'GREENVALLEY':
        print ('Peak stage: ' + "%.2f"%df.loc[storm_start:storm_end,'Level_PT_No'].max() + 'inches')
        print ('Peak stage: ' + "%.2f"%df.loc[storm_start:storm_end,'Level_PT_So'].max() + 'inches')
        
    else:
        print ('Peak stage: ' + "%.2f"%df.loc[storm_start:storm_end,'Level_PT'].max() + 'inches')


#%%
import mpld3
html_file= open('C:/Users/alex.messina/Documents/GitHub/Sutron_scripts/LakeHodges/Interactive Data Files/'+site+'-flow_data.html',"w")
mpld3.save_html(fig,html_file)
html_file.close()

#%% Scatterplot 950 vs PT LEVEL

#df = df[df.index > dt.datetime(2020,12,26)]

fig,ax = plt.subplots(1,1)
plt.scatter(df['Level_950'],df['Level_PT'],c='grey',alpha=0.5,label='raw data')
plt.scatter(df['Level_950'],df['Level_PT']-0.75,c='r',label='-0.75 offset')
plt.xlabel('Level 950'), plt.ylabel('Level PT')
plt.xlim(0,18), plt.ylim(0,18)
plt.plot([0,20],[0,20],ls='--',marker='None',c='grey')
plt.legend()


#%% Scatterplot 950 vs PT FLOW
fig,ax = plt.subplots(1,1)
plt.scatter(df['Flow_950'],df['Flow _PT'],c='grey',alpha=0.5)
plt.scatter(df['Flow_950'],df['Flow _PT'],c='r')
plt.xlabel('Flow 950'), plt.ylabel('Flow PT')
plt.xlim(0,18), plt.ylim(0,18)
plt.plot([0,20],[0,20],ls='--',marker='None',c='grey')

#%% Scatterplot 950 Level Velocity
fig,ax = plt.subplots(1,1)
plt.scatter(df['Level_950'],df['Vel_950'],c='r',label='Level_950 vs Vel_950')
plt.scatter(df['Level_PT'],df['Vel_950'],c='b',label='Level_PT vs Vel_950')
plt.xlabel('Level 950 and Level_PT'), plt.ylabel('Velocity 950 ')
plt.xlim(0,18), plt.ylim(0,18)
plt.plot([0,20],[0,20],ls='--',marker='None',c='grey')
legend(loc='upper right')


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
    






