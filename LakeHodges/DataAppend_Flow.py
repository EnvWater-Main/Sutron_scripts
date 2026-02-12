# -*- coding: utf-8 -*-
"""
Created on Sat Mar 13 13:58:01 2021

@author: alex.messina
"""
#%%
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
#site_list = ['ElKu']
#site_list = ['ViaRancho']
#site_list = ['Tazon']
#site_list = ['Oceans11']
#site_list = ['Lomica']



## CREEKS
#site_list = ['DELDIOS', 'FELICITA', 'KITCARSON','GREENVALLEY', 'MOONSONG','CLOVERDALE','GUEJITO','SYCAMORE','SDGCRK']

## OUTFALLS
#site_list = ['ElKu','ViaRancho','Tazon','Oceans11','Lomica']

## All sites
site_list = ['DELDIOS', 'FELICITA', 'KITCARSON','GREENVALLEY', 'MOONSONG','CLOVERDALE','GUEJITO','SYCAMORE','SDGCRK','ElKu','ViaRancho','Tazon','Oceans11','Lomica']

all_data_df = pd.DataFrame()

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
    ## Add site name
    df['SiteName'] = site
    
    if site in gpm:
        df['Flow'] = df['Flow_950']
        df['Units'] = 'gpm'
    if site in cfs:
        if site=='ViaRancho':
            df['Flow'] = df['Flow_950']
        else:
            df['Flow'] = df['Flow_cfs']
        df['Units'] = 'cfs'
        
    df = df.reindex(pd.date_range(dt.datetime(2020,2,1),dt.datetime(2021,6,1),freq='5Min'))
    
    df_data = df[['SiteName','Flow','Units']]
    df_data['Flow']= df_data['Flow'].resample('5Min').mean()
    
    all_data_df = all_data_df.append(df_data)
    
    
    
    
    
#%%
 all_data_df.dropna().to_csv('C:/Users/alex.messina/Documents/GitHub/Sutron_scripts/LakeHodges/flow_data_compiled.csv')