# -*- coding: utf-8 -*-
"""
Created on Tue Jun 24 12:22:24 2025

@author: USAM717566
"""

#%%
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
import requests

#%%
maindir = "C:/Users/USAM717566/OneDrive - WSP O365/Desktop/Temporary_work_shit/County Weirs/scrape_test/"

camera_dict= {"SLR-094-UP3":"64e4ff7a511001e1d51dd034"}

## new DF to save all the cameras in
df = pd.DataFrame(columns=['SiteName','CameraName','Camera_URL_num','url'])

#%%
for camera in camera_dict.items():
    print(camera)
    cam_name, cam_url_num = camera[0],camera[1]
    print ("Camera name: "+cam_name)
    print ("Camera url number: " +cam_url_num)
    ## go to that camera page and get all the current picture urls
    
    # Setup Selenium
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Optional: Run in background
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    # Load Spypoint camera page
    url = "https://webapp.spypoint.com/camera/" + cam_url_num
    driver.get(url)

    print(driver.current_url)
    
    # Wait for the login form to load
    print("waiting 10 sec....")
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
    
    # Fill in login form (adjust selectors as needed)
    print ("Logging in....")
    driver.find_element(By.NAME, "email").send_keys("alex.messina@woodplc.com")
    driver.find_element(By.NAME, "password").send_keys("Mactec101")
    driver.find_element(By.NAME, "password").send_keys(Keys.RETURN)
    print ("Logged in!")
    
    # Wait for successful login and page redirect
    print(driver.current_url)
    #WebDriverWait(driver, 10).until(EC.url_contains("/camera"))
     
    # Wait for JavaScript to load images
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 's3.amazonaws.com')]")))
    except:
        print(driver.current_url)
    
    # Find all <img> tags
    img_elements = driver.find_elements(By.XPATH, "//img[contains(@src, 's3.amazonaws.com')]")
    print ("length of img_elements: " + str(len(img_elements)))
    
    # Extract S3 image URLs
    image_urls = [img.get_attribute("src") for img in img_elements if img.get_attribute("src")]
    
    # Remove duplicates
    image_urls = list(set(image_urls))
    
    # Print or save
    for url in image_urls:
        print(url)
        
    ## Get full images from thumbnails
    thumbnails = img_elements
    full_img_urls = []

    for thumbnail in thumbnails:
        try:
            # Scroll into view to avoid interaction issues
            driver.execute_script("arguments[0].scrollIntoView(true);", thumbnail)
            time.sleep(0.5)
    
            # Click using JavaScript to avoid "not interactable" error
            driver.execute_script("arguments[0].click();", thumbnail)
    
            # Wait for modal to appear
            wait = WebDriverWait(driver, 10)
            full_img = wait.until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'MuiDialogContent-root')]//img"))
            )
    
            # Get the image src URL
            img_url = full_img.get_attribute("src")
            print("Full-size image URL:", img_url)
            full_img_urls.append(img_url)
    
            # Close modal
            close_button = driver.find_element(By.XPATH, "//button[@aria-label='close']")
            close_button.click()
            time.sleep(1)
    
        except Exception as e:
            print("Error getting full image:", e)
    
    
    driver.quit()
         
#%%
    cam_df = pd.DataFrame(columns=['SiteName','CameraName','Camera_URL_num','url'])
    ## save current urls to csv
    for img_url in image_urls:
        print (img_url)
        cam_df.loc[len(df)] = [cam_name, cam_name, cam_url_num, img_url]
        
    ## add each camera to the main df
    df = df.append(cam_df)
    
df.to_csv(maindir+"csv/image_urls.csv")    
    ##



















