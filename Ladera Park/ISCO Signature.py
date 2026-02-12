# -*- coding: utf-8 -*-
"""
Created on Wed May  3 15:23:12 2023

@author: alex.messina
"""

@MEASUREMENT
def ISCO_flow(input):
    """
    Using a ISCO Signature flowmeter
    only can use over RS485, baud rate is 19200
    ASCII mode: # of data bits is 8
    parity fixed at none. stop bits is 1
    """
    
    #modbus_address = 2  # first byte below
    #function_code = 03  # hex for 16-write registers
    #message = b'\x02\x03\x00\x49\x00\x02\x15\xEE' # read register 40074 (73 in hex=00 49)
    message = b'\x02\x03\x00\x27\x00\x02\x74\x33' # read register 40040 (39 in hex=00 27)

    ## Connect serial and send command 
    with serial.Serial("RS485", 19200, stopbits=1) as isco:
        isco.port = "RS485"  # i think this is redundant by why not
        isco.parity = 'N'
        isco.timeout = 1
        isco.inter_byte_timeout = 0.2  # not sure but going with what was programmed for AV900, maybe something to do with baudrate?
        isco.delay_before_tx = .5  # if you only get intermittent data, increase this value
        # send command to isco
        for i in range(3):  # retry 3 times
            print(i, message)
            isco.write(message)
            buff = isco.read(8)  # 8 or 16? the response message is 0203020003 + checksum (length=16)
            isco.flush()  # should add this to command?
            ## if good response from command
            if len(buff) >= 8 and buff[0] == 2 and buff[1]==3 and buff[2]==4:  # our only verification is that first return byte matches modbus address, second byte matches function code, and third byte matches byte count
                print ('buff >=8 and buff[0]==2')
                print(buff)
                print ('Result: '+str(buff[4]))
                d = int(buff[4])  

                
            ## if no good response from command, retry
            else:
                print('else')
                print('len(buff)=' + str(len(buff)))
                print(buff)
                utime.sleep(1)

    return d