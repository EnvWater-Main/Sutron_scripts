# -*- coding: utf-8 -*-
"""
Created on Thu Oct 29 13:08:50 2020

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

site = 'Del Dios'
#site = 'Felicita'
#site = 'Kit Carson'
#site = 'Cloverdale'
#site = 'Green Valley'
#site = 'Moonsong'
#site = 'Sycamore'
#site = 'San Dieguito'
#site = 'Guejito'

#site = 'El Ku'
#site = 'Via Rancho'
#site = 'Tazon'
#site = 'Oceans11'
#site = 'Lomica'

datadir = 'C:/Users/alex.messina/Documents/GitHub/Sutron_scripts/LakeHodges/Sutron_Scripts/Creeks/'

rating_curves = pd.ExcelFile(datadir+'Rating Curves 10_29_2020.xlsx')
rating_curve = rating_curves.parse(sheetname= site ,skiprows=1,header=0)
rating_curve = rating_curve.round(3)
rating_curve.index = rating_curve['Stage (in)']

if site=='Cloverdale':
    rating_curve = rating_curve[ rating_curve['Stage (in)']<75]
    
list_limit = int(len(rating_curve) / 70)


if site == 'Green Valley':
    list_limit = 1

if 'Flow (cfs)' in rating_curve.columns:
    STAGETBL = zip(rating_curve['Stage (in)'].values[::list_limit],rating_curve['Flow (cfs)'].values[::list_limit])
if 'Flow (gpm)' in rating_curve.columns:
    STAGETBL = zip(rating_curve['Stage (in)'].values[::list_limit],rating_curve['Flow (gpm)'].values[::list_limit])    


for i in STAGETBL:
    print (   str((float('%.2f'%i[0]), float('%.3f'%i[1])))+','   ) 