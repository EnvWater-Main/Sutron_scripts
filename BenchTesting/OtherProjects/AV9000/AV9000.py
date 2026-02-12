"""
Support for the AV9000 sensor
"""
from sl3 import *
import serial
import utime

"""
CurrentTime 49981 Unsigned Long 2 R/W Seconds since 1/1/2000.
we do not set the correct time, but it does not matter as long as
the clock register is written to
"""
set_time = b'\xF7\x10\x26\xFC\x00\x02\x04\x00\x01\x00\x00\x02\x94' #hexadecimal
slave_id = 'F7' # F7 is hexadecimal representing 247 (Modbus slave id) https://www.rapidtables.com/convert/number/decimal-to-binary.html
function_code = '10' #10 is hexadecimal reprsenting 16, modbus function code for writing multiple registers
start_register = '26 FC' # 26FC is hex representing 9980 which is I think the start register?
num_regiesters = '00 02' # 1 is hex for 1, only one register
byte_count = '04' # four bytes for data message
data = '00 01 00 00' # first register is 0001, second register is 0000 and I don't know what that means
checksum_CRC = '02 94'

"""
Measurement interval 40133 Unsigned Integer 1 R/W 
1 = 30 seconds
2 = 1 min
3 = 2 min
4 = 5 min
5 = 10 min
6 = 15 min
7 = 30 min
8 = 60 min
"""
# set it up for 1 minute interval
set_interval = b'\xF7\x10\x00\x84\x00\x01\x02\x00\x02\x16\x71'
slave_id = 'F7' # F7 is hexadecimal representing 247 (Modbus slave id) https://www.rapidtables.com/convert/number/decimal-to-binary.html
function_code = '10' #10 is hexadecimal reprsenting 16, modbus function code for writing multiple registers
start_register = '00 84' # 84 is hex representing 132 which is I think the start register
num_regiesters = '00 01' # 1 is hex for 1, only one register
byte_count = '02' # two bytes for data message
data = '00 02' # 2 corresponds to 1min in the table above
checksum_CRC = '16 71'

@TASK
def AV9000_setup():
    """
    Routine should be called once when the AV9000 is powered up
    It sets the AV9000 up
    """

    time_aok = False
    interval_aok = False

    with serial.Serial("RS485", 19200, stopbits=1) as sensor:
        sensor.rs485 = True  # required to actually send data over RS484
        sensor.timeout = 1
        sensor.inter_byte_timeout = .2
        sensor.delay_before_tx = .5  # if you only get intermittent data, increase this value

        # make sure the sensor is powered on OK
        power_control("SW1", False)  # turn off power to sensor
        utime.sleep(2)  # make sure sensor is off
        power_control("SW1", True)  # turn on power to sensor
        utime.sleep(3)  # give sensor a chance to wake up

        # set the clock of the AV9000 so that it measures on its own
        for i in range(3):  # retry
            sensor.write(set_time) ## here it delivers the hexadecimal byte string to the AV9000
            buff = sensor.read(8) ## here it reads 8 characters
            sensor.flush()
            if len(buff) >= 8 and buff[0] == 247: # our only verification is that first return byte matches (first byte is 247 the modbus slave address)
                time_aok = True
                break
            else:
                utime.sleep(2)

        # set the measurement interval to 1 minute
        for i in range(3):  # retry
            sensor.write(set_interval) ## here it delivers the hexadecimal byte string to the AV9000
            buff = sensor.read(8)
            sensor.flush()
            if len(buff) >= 8 and buff[0] == 247: # our only verification is that first return byte matches
                interval_aok = True
                break
            else:
                print(buff)
                utime.sleep(2)

    if not time_aok or not interval_aok:
        raise ValueError("Could not setup AV9000")


@TASK
def grab_sample_modbus():
    """
    Using a SD900 sampler
    only can use over RS232, baud rate is 115200
    RTU mode: # of data bits is 8
    ASCII mode: # of data bits is 7
    parity fixed at none. stop bits is 1 or 2
    """
    grab_aok = False
    result_aok = False
    
    modbus_address = 2 #first byte below
    function_code = 10 #hex for 16-write registers
    grab_sample = b'\x02\x10\x26\xCF\x00\x02\x04\x00\x64\x80\x07\x63\x47' ## 00 64 is hex for 100mL
    #grab_sample = b'\x02\x10\x26\xCF\x00\x02\x04\x00\xFA\x80\x07\xA9\x02' ## 00 FA is hex for 250mL
    #grab_sample = b'\x02\x10\x26\xCF\x00\x02\x04\x03\xE8\x80\x07\x63\x47' ## 00 64 is hex for 1000mL
    
    
    
    with serial.Serial("RS232",115200, stopbits=1) as sampler:
        sampler.port = "RS232" #i think this is redundant by why not
        sampler.timeout = 1
        sampler.inter_byte_timeout = 0.2 #not sure but going with what was programmed for AV900, maybe something to do with baudrate?
        sampler.delay_before_tx = .5  # if you only get intermittent data, increase this value
        max_retries = 3
        retries = 0
        #trigger sampler
        for i in range(max_retries): #retry
            if grab_aok == False or max_retries < retries:
                sampler.write(grab_sample)
                buff = sampler.read(8) # 8 or 16? the response message is 021026CF00027A8C (length=16)
                sampler.flush()
                if len(buff) >= 8 and buff[0] == 2: # our only verification is that first return byte matches modbus address
                    grab_aok = True
                    print('Attempt: '+str(i+1))
                    print ('grab aok')
                    print(buff)
                    print('Length buff: '+str(len(buff)))
                    print ('Buff[0]: '+str(buff[0]))
                    print ('  ')
                    
                    #read result register
                    utime.sleep(2)
                    result_code_max_retries = 12
                    result_code_tries = 1
                    result_register = b'\x02\x03\x26\xCE\x00\x01\xEE\x8E'
                    for i in range(result_code_max_retries):
                        print ('result code try: '+str(result_code_tries))
                        sampler.write(result_register)
                        buff = sampler.read(8) # 8 or 16? the response message is 021026CF00027A8C (length=16)
                        sampler.flush()
                        if len(buff) >= 7 and buff[0] == 2: # our only verification is that first return byte matches modbus address
                            result_aok = True
                            result_code = buff[3]
                            print (buff)
                            print('Length buff: '+str(len(buff)))
                            print ('buff[0]: '+str(buff[0]))
                            print("result code buff[4]: "+str(buff[4]))
                            print ('  ')
                            if result_code == 2 or result_code ==5 or result_code_tries>result_code_max_retries:
                                break ## stop if code is different than 2 or 5
                            else:
                                pass
                                  
                        else:
                            print ('unsuccessful read')
                            print (buff)
                        
                        utime.sleep(2)
                        result_code_tries+=1    
                    break
                    
                else:
                    print('Attempt: '+str(i+1))
                    print ('grab NOT aok')
                    print(buff)
                    print('Length buff: '+str(len(buff)))
                    print ('  ')
                    
                    
                    utime.sleep(2)
                    
                retries+=1
            
    if not grab_aok:
        raise ValueError("Could not trigger sampler")
    if not result_aok:
        raise ValueError("Could not get result")

@TASK
def check_result_code():
    
    with serial.Serial("RS232",115200, stopbits=1) as sampler:
        sampler.port = "RS232" #i think this is redundant by why not
        sampler.timeout = 1
        sampler.inter_byte_timeout = 0.2 #not sure but going with what was programmed for AV900, maybe something to do with baudrate?
        sampler.delay_before_tx = .5  # if you only get intermittent data, increase this value
    
        #read result register
        result_code_max_retries = 12
        result_code_tries = 1
        result_register = b'\x02\x03\x26\xCE\x00\x01\xEE\x8E'
        for i in range(result_code_max_retries):
            print ('result code try: '+str(result_code_tries))
            sampler.write(result_register)
            buff = sampler.read(8) # 8 or 16? the response message is 021026CF00027A8C (length=16)
            sampler.flush()
            if len(buff) >= 7 and buff[0] == 2: # our only verification is that first return byte matches modbus address
                result_aok = True
                result_code = buff[3]
                print (buff)
                print('Length buff: '+str(len(buff)))
                print ('buff[0]: '+str(buff[0]))
                print("result code buff[4]: "+str(buff[4]))
                print ('  ')
                if result_code == 2 or result_code ==5 or result_code_tries>result_code_max_retries:
                    break ## stop if code is different than 2 or 5
                else:
                    pass
                      
            else:
                print ('unsuccessful read')
                print (buff)
            
            utime.sleep(2)
            result_code_tries+=1  
        
@TASK
def turn_sampler_on_fwd():
    """
    Using a SD900 sampler
    only can use over RS232, baud rate is 115200
    RTU mode: # of data bits is 8
    ASCII mode: # of data bits is 7
    parity fixed at none. stop bits is 1 or 2
    """
    grab_aok = False
    
    modbus_address = 2 #first byte below
    function_code = 10 #hex for 16-write registers
    pump_on_fwd = b'\x02\x10\x26\xCF\x00\x02\x04\x00\x00\x80\x00\x63\x5A'
    pump_on_rev = b'\x02\x10\x26\xCF\x00\x02\x04\x00\x01\x80\x00\x32\x9A'
    with serial.Serial("RS232",115200, stopbits=1) as sampler:
        sampler.port = "RS232" #i think this is redundant by why not
        sampler.timeout = 1
        sampler.inter_byte_timeout = 0.2 #not sure but going with what was programmed for AV900, maybe something to do with baudrate?
        sampler.delay_before_tx = .5  # if you only get intermittent data, increase this value
        
        #trigger sampler
        for i in range(3): #retry
            sampler.write(pump_on_fwd)
            buff = sampler.read(8) # 8 or 16? the response message is 021026CF00027A8C (length=16)
            
            if len(buff) >= 8 and buff[0] == 2: # our only verification is that first return byte matches modbus address
                print(buff)
                grab_aok = True
                break
            else:
                print(buff)
                utime.sleep(2)  
            
    if not grab_aok:
        raise ValueError("Could not trigger sampler")
             
    
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        