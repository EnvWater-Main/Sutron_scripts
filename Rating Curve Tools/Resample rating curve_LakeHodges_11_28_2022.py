# -*- coding: utf-8 -*-
"""
Created on Thu Sep 29 14:47:30 2022

@author: alex.messina
"""


import pandas as pd
import numpy as np


datadir = 'C:/Users/alex.messina/Documents/GitHub/Sutron_scripts/LakeHodges/'

ratings = pd.ExcelFile(datadir + 'Rating Curves 11_28_2022.xlsx')

resampled_index = np.round(np.arange(0.00,72, step=0.1),2)
ratings_resampled = pd.DataFrame(index=resampled_index)



#fig, ax = plt.subplots(1,1)
for sheet in ratings.sheet_names[1:]:
    print (sheet)

#%%
    rating_curve = ratings.parse(sheet_name = sheet,index_col=0,skiprows=1)
    
    if rating_curve.columns[0].endswith('gpm') == True:
        rating_curve['Flow_cfs'] = rating_curve['Flow_gpm'] * 0.0026757275153786
        
    
    
    fig, ax = plt.subplots(1,1)
    
    ## round rating curve to .01 stage and .001 cfs
    rating_curve_rd = pd.DataFrame({'Flow_cfs':np.round(rating_curve['Flow_cfs'].values,3)},index = np.round(rating_curve.index,2))
    ## drop duplicates
    rating_curve_rd = rating_curve_rd[rating_curve_rd.index.duplicated()==False]
    ## create new index from the first entry (should be 0.0in) to the last, in 0.01 in increements
    resampled_index = np.round(np.arange(rating_curve_rd.index[0],rating_curve_rd.index[-1], step=0.01),2)
    ## join the rating curve index with the new index, interpolate them
    
    rating_curve_resampled = rating_curve_rd.reindex(rating_curve_rd.index.union(resampled_index)).interpolate('values').loc[resampled_index]
    ## take every 10th entry to get in 0.1 in increments
#    rating_curve_resampled = rating_curve_resampled[::10]
    ## round cfs to 0.001 cfs
    rating_curve_resampled['Flow_cfs'] = rating_curve_resampled['Flow_cfs'] .round(3)
    ## rename index
    rating_curve_resampled.index.rename(name = 'Stage_in',inplace=True)
    
    ratings_resampled.loc[:,sheet+'_flow_cfs'] = rating_curve_resampled['Flow_cfs'] 
    
    
    ax.plot(rating_curve_resampled.index,rating_curve_resampled['Flow_cfs'],ls='-',marker='.',c='b',alpha=1,label=sheet+' resampled rating curve')
    ax.plot(rating_curve.index,rating_curve['Flow_cfs'],ls='-',marker='.',c='r',alpha=0.5,label = sheet+' orig rating curve')
    
    plt.legend()
    ax.set_xlabel('Level (inches)')
    ax.set_ylabel('Flow (cfs)')
    
    
    for i in zip(rating_curve_resampled.index.values,rating_curve_resampled['Flow_cfs']):
        print (   str((float('%.2f'%i[0]), float('%.3f'%i[1])))+','   ) 
