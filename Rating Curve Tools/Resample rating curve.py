# -*- coding: utf-8 -*-
"""
Created on Thu Sep 29 14:47:30 2022

@author: alex.messina
"""


import pandas as pd


datadir = "P:/5018_Water Quality/5018-22-1107 CiSD TO 107 Famosa Slough/Data & Field Records/Continuous Flow/"

rating_curve = pd.read_excel(datadir + "HvF table for Sutron_09292022.xlsx",sheetname='Sheet1',index_col=0)


fig, ax = plt.subplots(1,1)

## round rating curve to .01 stage and .001 cfs
rating_curve_rd = pd.DataFrame({'Flow (cfs)':np.round(rating_curve['Weir + Channel Flow (cfs)'].values,3)},index = np.round(rating_curve.index,2))
## drop duplicates
rating_curve_rd = rating_curve_rd[rating_curve_rd.index.duplicated()==False]
## create new index from the first entry (should be 0.0in) to the last, in 0.01 in increements
resampled_index = np.round(np.arange(rating_curve_rd.index[0],rating_curve_rd.index[-1], step=0.01),2)
## join the rating curve index with the new index, interpolate them

rating_curve_resampled = rating_curve_rd.reindex(rating_curve_rd.index.union(resampled_index)).interpolate('values').loc[resampled_index]
## take every 10th entry to get in 0.1 in increments
rating_curve_resampled = rating_curve_resampled[::20]
## round cfs to 0.001 cfs
rating_curve_resampled['Flow (cfs)'] = rating_curve_resampled['Flow (cfs)'] .round(3)
## rename index
rating_curve_resampled.index.rename(name = 'Stage (in)',inplace=True)




ax.plot(rating_curve_resampled.index,rating_curve_resampled['Flow (cfs)'],ls='-',marker='.',c='b',alpha=1,label='resampled rating curve')
ax.plot(rating_curve.index,rating_curve['Weir + Channel Flow (cfs)'],ls='-',marker='.',c='r',alpha=0.5,label = 'orig rating curve')

plt.legend()
ax.set_xlabel('Level (inches)')
ax.set_ylabel('Flow (cfs)')


for i in zip(rating_curve_resampled.index.values,rating_curve_resampled['Flow (cfs)']):
    print (   str((float('%.2f'%i[0]), float('%.3f'%i[1])))+','   ) 
