# **Packet Serial**

### **Packet Serial Mode**

Packet serial is a buffered bidirectional serial mode. More sophisticated instructions can be sent to RoboClaw. The basic command structures consist of an address byte, command byte, data bytes and a CRC16 16bit checksum. The amount of data each command will send or receive can vary.

## **Address**

Packet serial requires a unique address when used with TTL serial pins(S1 and S2). With up to 8 addresses available you can have up to 8 RoboClaws bussed on the same RS232 port when properly wired. There are 8 packet modes 7 to 14. Each mode has a unique address. The address is selected by setting the desired packet mode using the MODE button.

NOTE: When using packet serial commands via the USB connection the address byte can be any value from 0x80 to 0x87 since each USB connection is already unique.

| <b>Mode</b> | <b>Description</b>                      |
|-------------|-----------------------------------------|
| 7           | Packet Serial Mode - Address 0x80 (128) |
| 8           | Packet Serial Mode - Address 0x81 (129) |
| 9           | Packet Serial Mode - Address 0x82 (130) |
| 10          | Packet Serial Mode - Address 0x83 (131) |
| 11          | Packet Serial Mode - Address 0x84 (132) |
| 12          | Packet Serial Mode - Address 0x85 (133) |
| 13          | Packet Serial Mode - Address 0x86 (134) |
| 14          | Packet Serial Mode - Address 0x87 (135) |

## **Packet Modes**

## **Packet Serial Baud Rate**

When in serial mode or packet serial mode the baud rate can be changed to one of four different settings in the table below. These are set using the SET button as covered in Mode Options.

## **Serial Mode Options**

| <b>Option</b> | <b>Description</b> |
|---------------|--------------------|
| 1             | 2400               |
| 2             | 9600               |
| 3             | 19200              |
| 4             | 38400              |
| 5             | 57600              |
| 6             | 115200             |
| 7             | 230400             |
| 8             | 460800             |

Image /page/58/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside it, followed by the word "BASICMICRO" in black, sans-serif font.

## **Packet Timeout**

When sending a packet to RoboClaw, if there is a delay longer than 10ms between bytes being received in a packet, RoboClaw will discard the entire packet. This will allow the packet buffer to be cleared by simply adding a minimum 10ms delay before sending a new packet command in the case of a communications error. This can usually be accomodated by having a 10ms timeout when waiting for a reply from the RoboClaw. If the reply times out the packet buffer will have been cleared automatically.

# **Packet Acknowledgement**

RoboClaw will send an acknowledgment byte on write only packet commands that are valid. The value sent back is 0xFF. If the packet was not valid for any reason no acknowledgement will be sent back.

# **CRC16 Checksum Calculation**

Roboclaw uses a CRC(Cyclic Redundancy Check) to validate each packet it receives. This is more complex than a simple checksum but prevents errors that could otherwise cause unexpected actions to execute on the Roboclaw.

The CRC can be calculated using the following code(example in C):

```
//Calculates CRC16 of nBytes of data in byte array message
unsigned int crc16(unsigned char *packet, int nBytes) {
    for (int byte = 0; byte < nBytes; byte++) {
         \text{circ} = \text{circ} \land ((unsigned int)packet[byte] \ll 8);
         for (unsigned char bit = 0; bit < 8; bit++) {
              if (crc & 0x8000) {
                 \text{circ} = (\text{circ} \ll 1) \land 0 \times 1021;
              } else {
             crc = crc \langle 1; }
 }
     }
     return crc;
}
```

# **CRC16 Checksum Calculation for Received data**

The CRC16 calculation can also be used to validate received data from the Roboclaw. The CRC16 value should be calculated using the sent Address and Command byte as well as all the data received back from the Roboclaw except the two CRC16 bytes. The value calculated will match the CRC16 sent by the Roboclaw if there are no errors in the data sent or received.

# **Easy to use Libraries**

Source code and Libraries are available on the BasicMicro website that already handle the complexities of using packet serial with the Roboclaw. Libraries are available for Arduino( $C++$ ), C# on Windows(.NET) or Linux(Mono) and Python(Raspberry Pi, Linux, OSX, etc).

Image /page/59/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

## **Handling values larger than a byte**

Many Packet Serial commands require values larger than a byte can hold. In order to send or receive those values they need to be broken up into 2 or more bytes. There are two ways this can be done, high byte first or low byte first. Roboclaw expects the high byte first. All command arguments and values are either single bytes, words (2 bytes) or longs (4 bytes). All arguments and values are integers (signed or unsigned). No floating point values (numbers with decimal places) are used in Packet Serial commands.

To convert a 32bit value into 4 bytes you just need to shift the bits around:

```
unsigned char byte3 = MyLongValue>>24; //High byte
unsigned char byte2 = MyLongValue>>16;
unsigned char byte1 = MyLongValue>>8;
unsigned char byte0 = MyLongValue; //Low byte
```

The same applies to 16bit values:

```
unsigned char byte1 = MyWordValue>>8; //High byte<br>unsigned char byte0 = MyWordValue; //Low byte
unsigned char byte0 = \text{MyWordValue};
```

The oposite can also be done. Convert several bytes into a 16bit or 32bit value:

```
unsigned long MyLongValue = byte3 << 24 | byte2<<16 | byte1 << 8 | byte0;
unsigned int MyWordValue = byte1<<8 | byte0;
```

Packet Serial commands, when a value must be broken into multiple bytes or combined from multple bytes it will be indicated either by (2 bytes) or (4 bytes).

Image /page/60/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **Packet Serial Wiring**

In packet serial mode the RoboClaw can transmit and receive serial data. A microcontroller with a UART is recommended. The UART will buffer the data received from RoboClaw. When a request for data is made to RoboClaw the return data will have at least a 1ms delay after the command is received if the baud rate is set at or below 38400. This will allow slower processors and processors without UARTs to communicate with RoboClaw.

The diagram below shows the main battery as the only power source. The 5VDC shown connected is only required if your MCU needs a power source. This is the BEC feature of RoboClaw. If the MCU has its own power source do not connect the 5VDC.

Image /page/60/Figure/6 description: The image shows a circuit diagram with several components. On the left side, there is a block labeled "MCU" with connections for "UART TX", "UART RX", "5VDC", and "GROUND". These connections are linked to a block labeled "RoboClaw" with corresponding labels "S1 Signal", "S2 Signal", "5VDC", and "GROUND". The "RoboClaw" block also has connections labeled "M1A", "M1B", "Positive +", "Negative -", "M2B", and "M2A". "M1A" and "M1B" are connected to "Motor 1", while "M2B" and "M2A" are connected to "Motor 2". The "Positive +" connection from "RoboClaw" is connected to a switch labeled "SW1", which is connected to a diode labeled "D1". The switch and diode are connected to the positive terminal of a "Battery". The "Negative -" connection from "RoboClaw" is connected to the negative terminal of the "Battery".

Image /page/61/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **Multi-Unit Packet Serial Wiring**

In packet serial mode up to eight Roboclaw units can be controlled from a single serial port. The wiring diagram below illustrates how this is done. Each Roboclaw must have multi-unit mode enabled and have a unique packet serial address set. This can be configured using Motion Studio. Wire the S1 and S2 pins directly to the MCU TX and RX pins. Install a pull-up resistor (R1) on the MCU RX pin. A 1K to 4.7K resistor value is recommended. For model specific pinout information please refer to the data sheet for the model being used.

Image /page/61/Figure/4 description: The image shows a schematic diagram of a microcontroller (MCU) connected to three RoboClaw motor controllers (RoboClaw 1, RoboClaw 2, and RoboClaw 3). The MCU has four connections: UART TX, UART RX, 5VDC, and GROUND. The UART TX line is connected to the S1 Signal line of each RoboClaw through a resistor labeled R1. The UART RX line is connected to the S2 Signal line of each RoboClaw. The 5VDC line is connected to the 5VDC line of each RoboClaw. The GROUND line is connected to the GROUND line of each RoboClaw.

Image /page/62/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

## **Commands 0 - 7 Compatibility Commands**

The following commands are used in packet serial mode. The command syntax is the same for commands 0 thru 7:

```
Send: Address, Command, ByteValue, CRC16
Receive: [0xFF]
```

| <b>Command</b> | <b>Description</b>                |
|----------------|-----------------------------------|
| 0              | Drive Forward Motor 1             |
| 1              | Drive Backwards Motor 1           |
| 2              | Set Main Voltage Minimum          |
| 3              | Set Main Voltage Maximum          |
| 4              | Drive Forward Motor 2             |
| 5              | Drive Backwards Motor 2           |
| 6              | Drive Motor 1 (7 Bit)             |
| 7              | Drive Motor 2 (7 Bit)             |
| 8              | Drive Forward Mixed Mode          |
| 9              | Drive Backwards Mixed Mode        |
| 10             | Turn Right Mixed Mode             |
| 11             | Turn Left Mixed Mode              |
| 12             | Drive Forward or Backward (7 bit) |
| 13             | Turn Left or Right (7 Bit)        |

#### **0 - Drive Forward M1**

Drive motor 1 forward. Valid data range is 0 - 127. A value of 127 = full speed forward, 64 = about half speed forward and  $0 = \text{full stop.}$ 

```
Send: [Address, 0, Value, CRC(2 bytes)]
Receive: [0xFF]
```

#### **1 - Drive Backwards M1**

Drive motor 1 backwards. Valid data range is  $0 - 127$ . A value of 127 full speed backwards, 64 = about half speed backward and  $0 =$  full stop.

```
Send: [Address, 1, Value, CRC(2 bytes)]
Receive: [0xFF]
```

#### **2 - Set Minimum Main Voltage (Command 57 Preferred)**

Sets main battery (B- / B+) minimum voltage level. If the battery voltages drops below the set voltage level RoboClaw will stop driving the motors. The voltage is set in .2 volt increments. A value of 0 sets the minimum value allowed which is 6V. The valid data range is  $0 - 140$  (6V -34V). The formula for calculating the voltage is: (Desired Volts -  $6$ ) x 5 = Value. Examples of valid values are  $6V = 0$ ,  $8V = 10$  and  $11V = 25$ .

```
Send: [Address, 2, Value, CRC(2 bytes)]
Receive: [0xFF]
```

Image /page/63/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **RoboClaw Series Brushed DC Motor Controllers**

#### **3 - Set Maximum Main Voltage (Command 57 Preferred)**

Sets main battery (B- / B+) maximum voltage level. The valid data range is 30 - 175 (6V - 34V). During regenerative breaking a back voltage is applied to charge the battery. When using a power supply, by setting the maximum voltage level, RoboClaw will, before exceeding it, go into hard braking mode until the voltage drops below the maximum value set. This will prevent overvoltage conditions when using power supplies. The formula for calculating the voltage is: Desired Volts  $x 5.12 =$  Value. Examples of valid values are  $12V = 62$ ,  $16V = 82$  and  $24V = 123$ .

```
Send: [Address, 3, Value, CRC(2 bytes)]
Receive: [0xFF]
```

#### **4 - Drive Forward M2**

Drive motor 2 forward. Valid data range is  $0 - 127$ . A value of 127 full speed forward,  $64 =$  about half speed forward and  $0 =$  full stop.

```
Send: [Address, 4, Value, CRC(2 bytes)]
Receive: [0xFF]
```

#### **5 - Drive Backwards M2**

Drive motor 2 backwards. Valid data range is  $0 - 127$ . A value of 127 full speed backwards, 64 = about half speed backward and  $0 =$  full stop.

```
Send: [Address, 5, Value, CRC(2 bytes)]
Receive: [0xFF]
```

## **6 - Drive M1 (7 Bit)**

Drive motor 1 forward or reverse. Valid data range is  $0 - 127$ . A value of  $0 =$  full speed reverse,  $64$  = stop and  $127$  = full speed forward.

```
Send: [Address, 6, Value, CRC(2 bytes)]
Receive: [0xFF]
```

#### **7 - Drive M2 (7 Bit)**

Drive motor 2 forward or reverse. Valid data range is  $0 - 127$ . A value of  $0 =$  full speed reverse,  $64$  = stop and  $127$  = full speed forward.

```
Send: [Address, 7, Value, CRC(2 bytes)]
Receive: [0xFF]
```

Image /page/64/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

#### **Commands 8 - 13 Mixed Mode Compatibility Commands**

The following commands are mix mode commands used to control speed and turn for differential steering. Before a command is executed, both valid drive and turn data packets are required Once RoboClaw begins to operate the motors turn and speed can be updated independently.

#### **8 - Drive Forward**

Drive forward in mix mode. Valid data range is  $0 - 127$ . A value of  $0 =$  full stop and  $127 =$  full forward.

```
Send: [Address, 8, Value, CRC(2 bytes)]
Receive: [0xFF]
```

#### **9 - Drive Backwards**

Drive backwards in mix mode. Valid data range is  $0 - 127$ . A value of  $0 =$  full stop and  $127 =$  full reverse.

Send: [Address, 9, Value, CRC(2 bytes)] Receive: [0xFF]

#### **10 - Turn right**

Turn right in mix mode. Valid data range is  $0 - 127$ . A value of  $0 = stop$  turn and  $127 = full$ speed turn.

Send: [Address, 10, Value, CRC(2 bytes)] Receive: [0xFF]

#### **11 - Turn left**

Turn left in mix mode. Valid data range is  $0 - 127$ . A value of  $0 =$  stop turn and  $127 =$  full speed turn.

Send: [Address, 11, Value, CRC(2 bytes)] Receive: [0xFF]

#### **12 - Drive Forward or Backward (7 Bit)**

Drive forward or backwards. Valid data range is  $0 - 127$ . A value of  $0 =$  full backward, 64 = stop and  $127 =$  full forward.

```
Send: [Address, 12, Value, CRC(2 bytes)]
Receive: [0xFF]
```

#### **13 - Turn Left or Right (7 Bit)**

Turn left or right. Valid data range is  $0 - 127$ . A value of  $0 =$  full left,  $0 =$  stop turn and  $127 =$  full right.

Send: [Address, 13, Value, CRC(2 bytes)] Receive: [0xFF]

Image /page/65/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, resembling the letter 'B'. To the right of the circle is the word "BASICMICRO" in a bold, sans-serif font.

# **Advanced Packet Serial**

## **Commands**

The following commands are used to read RoboClaw status information, version information and to set or read configuration values. All commands sent to RoboClaw need to be signed with a CRC16 (Cyclic Redundancy Check of 2 bytes) to validate each packet it received. This is more complex than a simple checksum but prevents errors that could otherwise cause unexpected actions to execute on the Roboclaw. See Packet Serial section of this manual for an explanation on how to create the CRC16 values.

| <b>Command</b> | <b>Description</b>                         |
|----------------|--------------------------------------------|
| 14             | Set Serial Timeout                         |
| 15             | Read Serial Timeout                        |
| 21             | Read Firmware Version                      |
| 24             | Read Main Battery Voltage                  |
| 25             | Read Logic Battery Voltage                 |
| 26             | Set Minimum Logic Voltage Level            |
| 27             | Set Maximum Logic Voltage Level            |
| 48             | Read Motor PWMs                            |
| 49             | Read Motor Currents                        |
| 57             | Set Main Battery Voltages                  |
| 58             | Set Logic Battery Voltages                 |
| 59             | Read Main Battery Voltage Settings         |
| 60             | Read Logic Battery Voltage Settings        |
| 68             | Set default duty cycle acceleration for M1 |
| 69             | Set default duty cycle acceleration for M2 |
| 70             | Set Default Speed for M1                   |
| 71             | Set Default Speed for M2                   |
| 72             | Read Default Speed Settings                |
| 74             | Set S3,S4 and S5 Modes                     |
| 75             | Read S3,S4 and S5 Modes                    |
| 76             | Set DeadBand for RC/Analog controls        |
| 77             | Read DeadBand for RC/Analog controls       |
| 80             | Restore Defaults                           |
| 81             | Read Default Duty Cycle Accelerations      |
| 82             | Read Temperature                           |
| 83             | Read Temperature 2                         |
| 90             | Read Status                                |
| 91             | Read Encoder Modes                         |
| 92             | Set Motor 1 Encoder Mode                   |
| 93             | Set Motor 2 Encoder Mode                   |
| 94             | Write Settings to EEPROM                   |
| 95             | Read Settings from EEPROM                  |

Image /page/66/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three white horizontal lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

| Command | Description                             |
|---------|-----------------------------------------|
| 98      | Set Standard Config Settings            |
| 99      | Read Standard Config Settings           |
| 100     | Set CTRL Modes                          |
| 101     | Read CTRL Modes                         |
| 102     | Set CTRL1                               |
| 103     | Set CTRL2                               |
| 104     | Read CTRLs                              |
| 105     | Set Auto Home Duty/Speed and Timeout M1 |
| 106     | Set Auto Home Duty/Speed and Timeout M2 |
| 107     | Read Auto Home Settings                 |
| 109     | Set Speed Error Limits                  |
| 110     | Read Speed Error Limits                 |
| 112     | Set Position Error Limits               |
| 113     | Read Position Error Limits              |
| 115     | Set Battery Voltage Offsets             |
| 116     | Read Battery Voltage Offsets            |
| 117     | Set Current Blanking Percentages        |
| 118     | Read Current Blanking Percentages       |
| 133     | Set M1 Maximum Current                  |
| 134     | Set M2 Maximum Current                  |
| 135     | Read M1 Maximum Current                 |
| 136     | Read M2 Maximum Current                 |
| 148     | Set PWM Mode                            |
| 149     | Read PWM Mode                           |
| 252     | Read User EEPROM Memory Location        |
| 253     | Write User EEPROM Memory Location       |

# **14 - Set Serial Timeout**

Sets the serial communication timeout in 100ms increments. When serial bytes are received in the time specified both motors will stop automatically. Range is 0 to 25.5 seconds (0 to 255 in 100ms increments).

```
Send: [Address, 14, Value, CRC (2 byes)]
Receive: [0xFF]
```

# **15 - Read Serial Timeout**

Read the current serial timeout setting. Range is 0 to 255.

```
Send: [Address, 15]
Receive: [Value, CRC (2 bytes)]
```

Image /page/67/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside it, followed by the word "BASICMICRO" in black, sans-serif font.

## **21 - Read Firmware Version**

Read RoboClaw firmware version. Returns up to 48 bytes(depending on the Roboclaw model) and is terminated by a line feed character and a null character.

```
Send: [Address, 21]
Receive: ["RoboClaw 10.2A v4.1.11",10,0, CRC(2 bytes)]
```

The command will return up to 48 bytes. The return string includes the product name and firmware version. The return string is terminated with a line feed (10) and null (0) character.

### **24 - Read Main Battery Voltage Level**

Read the main battery voltage level connected to B+ and B- terminals. The voltage is returned in 10ths of a volt(eq  $300 = 30v$ ).

```
Send: [Address, 24]
Receive: [Value(2 bytes), CRC(2 bytes)]
```

## **25 - Read Logic Battery Voltage Level**

Read a logic battery voltage level connected to LB+ and LB- terminals. The voltage is returned in 10ths of a volt(eq  $50 = 5v$ ).

```
Send: [Address, 25]
Receive: [Value.Byte1, Value.Byte0, CRC(2 bytes)]
```

# **26 - Set Minimum Logic Voltage Level**

**Note: This command is included for backwards compatibility. We recommend you use command 58 instead.**

Sets logic input (LB- / LB+) minimum voltage level. RoboClaw will shut down with an error if the voltage is below this level. The voltage is set in .2 volt increments. A value of 0 sets the minimum value allowed which is 6V. The valid data range is 0 - 140 (6V - 34V). The formula for calculating the voltage is: (Desired Volts - 6)  $x 5 =$  Value. Examples of valid values are 6V = 0,  $8V = 10$  and  $11V = 25$ .

```
Send: [Address, 26, Value, CRC(2 bytes)]
Receive: [0xFF]
```

# **27 - Set Maximum Logic Voltage Level**

**Note: This command is included for backwards compatibility. We recommend you use command 58 instead.**

Sets logic input (LB- / LB+) maximum voltage level. The valid data range is 30 - 175 (6V - 34V). RoboClaw will shutdown with an error if the voltage is above this level. The formula for calculating the voltage is: Desired Volts  $x$  5.12 = Value. Examples of valid values are 12V = 62,  $16V = 82$  and  $24V = 123$ .

```
Send: [Address, 27, Value, CRC(2 bytes)]
Receive: [0xFF]
```

Image /page/68/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

## **48 - Read Motor PWM values**

Read the current PWM output values for the motor channels. The values returned are +/-32767. The duty cycle percent is calculated by dividing the Value by 327.67.

```
Send: [Address, 48]
Receive: [M1 PWM(2 bytes), M2 PWM(2 bytes), CRC(2 bytes)]
```

#### **49 - Read Motor Currents**

Read the current draw from each motor in 10ma increments. The amps value is calculated by dividing the value by 100.

```
Send: [Address, 49]
Receive: [M1 Current(2 bytes), M2 Currrent(2 bytes), CRC(2 bytes)]
```

#### **57 - Set Main Battery Voltages**

Set the Main Battery Voltage cutoffs, Min and Max. Min and Max voltages are in 10th of a volt increments. Multiply the voltage to set by 10.

```
Send: [Address, 57, Min(2 bytes), Max(2bytes, CRC(2 bytes)]
Receive: [0xFF]
```

#### **58 - Set Logic Battery Voltages**

Set the Logic Battery Voltages cutoffs, Min and Max. Min and Max voltages are in 10th of a volt increments. Multiply the voltage to set by 10.

```
Send: [Address, 58, Min(2 bytes), Max(2bytes, CRC(2 bytes)]
Receive: [0xFF]
```

## **59 - Read Main Battery Voltage Settings**

Read the Main Battery Voltage Settings. The voltage is calculated by dividing the value by 10

```
Send: [Address, 59]
Receive: [Min(2 bytes), Max(2 bytes), CRC(2 bytes)]
```

## **60 - Read Logic Battery Voltage Settings**

Read the Logic Battery Voltage Settings. The voltage is calculated by dividing the value by 10

```
Send: [Address, 60]
Receive: [Min(2 bytes), Max(2 bytes), CRC(2 bytes)]
```

#### **68 - Set M1 Default Duty Acceleration**

Set the default acceleration for M1 when using duty cycle commands(Cmds 32,33 and 34) or when using Standard Serial, RC and Analog PWM modes.

```
Send: [Address, 68, Accel(4 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

Image /page/69/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **69 - Set M2 Default Duty Acceleration**

Set the default acceleration for M2 when using duty cycle commands(Cmds 32,33 and 34) or when using Standard Serial, RC and Analog PWM modes.

```
Send: [Address, 69, Accel(4 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

# **70 - Set Motor1 Default Speed**

Set M1 default speed for use with M1 position command and RC or analog modes when position control is enabled. This sets the percentage of the maximum speed set by QPSS as the default speed. The range is 0 to 32767.

```
Send: [Address, 70, Value(2 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

# **71 - Set Motor 2 Default Speed**

Set M2 default speed for use with M2 postion command and RC or analog modes when position control is enabled. This sets the percentage of the maximum speed set by QPSS as the default speed. The range is 0 to 32767.

```
Send: [Address, 71, Value(2 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

# **72 - Read Default Speed Settings**

Read current default speeds for M1 and M2.

```
Send: [Address, 72]
Receive: [M1Speed(2 bytes), M2Speed(2 bytes), CRC(2 bytes)]
```

Image /page/70/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with a white "B" inside it, followed by the word "BASICMICRO" in black, sans-serif font.

## **74 - Set S3, S4 and S5 Modes**

Set modes for S3,S4 and S5.

```
Send: [Address, 74, S3mode, S4mode, S5mode, CRC(2 bytes)]
Receive: [0xFF]
```

| Mode | S3mode           | S4mode                 | S5mode                |
|------|------------------|------------------------|-----------------------|
| 0x00 | Default          | Disabled               | Disabled              |
| 0x01 | E-Stop           | E-Stop                 | E-Stop                |
| 0x81 | E-Stop(Latching) | E-Stop(Latching)       | E-Stop(Latching)      |
| 0x14 | Voltage Clamp    | Voltage Clamp          | Voltage Clamp         |
| 0x24 | RS485 Direction  |                        |                       |
| 0x84 | Encoder toggle   |                        |                       |
| 0x04 |                  | Brake                  | Brake                 |
| 0xE2 |                  | Home(Auto)             |                       |
| 0x62 |                  | Home(User)             | Home(User)            |
| 0xF2 |                  | Home(Auto)/ Limit(Fwd) | Home(Auto)/Limit(Fwd) |
| 0x72 |                  | Home(User)/ Limit(Fwd) | Home(User)/Limit(Fwd) |
| 0x12 |                  | Limit(Fwd)             | Limit(Fwd)            |
| 0x22 |                  | Limit(Rev)             | Limit(Rev)            |
| 0x32 |                  | Limit(Both)            | Limit(Both)           |

# **Mode Description**

Disabled: pin is inactive.

Default: Flip switch if in RC/Analog mode or E-Stop(latching) in Serial modes. E-Stop(Latching): causes the Roboclaw to shutdown until the unit is power cycled. E-Stop: Holds the Roboclaw in shutdown until the E-Stop signal is cleared. Voltage Clamp: Sets the signal pin as an output to drive an external voltage clamp circuit Home(M1 & M2): will trigger the specific motor to stop and the encoder count to reset to 0.

## **75 - Get S3, S4 and S5 Modes**

Read mode settings for S3,S4 and S5. See command 74 for mode descriptions

```
Send: [Address, 75]
Receive: [S3mode, S4mode, S5mode, CRC(2 bytes)]
```

# **76 - Set DeadBand for RC/Analog controls**

Set RC/Analog mode control deadband percentage in 10ths of a percent. Default value is 25(2.5%). Minimum value is 0(no DeadBand), Maximum value is 250(25%).

```
Send: [Address, 76, Reverse, Forward, CRC(2 bytes)]
Receive: [0xFF]
```

Image /page/71/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **77 - Read DeadBand for RC/Analog controls**

Read DeadBand settings in 10ths of a percent.

```
Send: [Address, 77]
Receive: [Reverse, SForward, CRC(2 bytes)]
```

## **80 - Restore Defaults**

Reset Settings to factory defaults.

Send: [Address, 80] Receive: [0xFF]

### **81 - Read Default Duty Acceleration Settings**

Read M1 and M2 Duty Cycle Acceleration Settings.

```
Send: [Address, 81]
Receive: [M1Accel(4 bytes), M2Accel(4 bytes), CRC(2 bytes)]
```

### **82 - Read Temperature**

Read the board temperature. Value returned is in 10ths of degrees.

```
Send: [Address, 82]
Receive: [Temperature(2 bytes), CRC(2 bytes)]
```

# **83 - Read Temperature 2**

Read the second board temperature(only on supported units). Value returned is in 10ths of degrees.

```
Send: [Address, 83]
Receive: [Temperature(2 bytes), CRC(2 bytes)]
```

Image /page/72/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

## **90 - Read Status**

Read the current unit status.

Send: [Address, 90] Receive: [Status, CRC(2 bytes)]

| <b>Function</b>              | <b>Status Bit Mask</b> |
|------------------------------|------------------------|
| Normal                       | 0x000000               |
| E-Stop                       | 0x000001               |
| Temperature Error            | 0x000002               |
| Temperature 2 Error          | 0x000004               |
| Main Voltage High Error      | 0x000008               |
| Logic Voltage High Error     | 0x000010               |
| Logic Voltage Low Error      | 0x000020               |
| M1 Driver Fault Error        | 0x000040               |
| M2 Driver Fault Error        | 0x000080               |
| M1 Speed Error               | 0x000100               |
| M2 Speed Error               | 0x000200               |
| M1 Position Error            | 0x000400               |
| M2 Position Error            | 0x000800               |
| M1 Current Error             | 0x001000               |
| M2 Current Error             | 0x002000               |
| M1 Over Current Warning      | 0x010000               |
| M2 Over Current Warning      | 0x020000               |
| Main Voltage High Warning    | 0x040000               |
| Main Voltage Low Warning     | 0x080000               |
| Temperature Warning          | 0x100000               |
| Temperature 2 Warning        | 0x200000               |
| S4 Signal Triggered          | 0x400000               |
| S5 Signal Triggered          | 0x800000               |
| Speed Error Limit Warning    | 0x01000000             |
| Position Error Limit Warning | 0x02000000             |

# **91 - Read Encoder Mode**

Read the encoder mode for both motors.

Send: [Address, 91] Receive: [Enc1Mode, Enc2Mode, CRC(2 bytes)]

# **Encoder Mode bits**

| Bit 7   | Enable/Disable RC/Analog Encoder support |
|---------|------------------------------------------|
| Bit 6   | Reverse Encoder Relative Direction       |
| Bit 5   | Reverse Motor Relative Direction         |
| Bit 4-1 | N/A                                      |
| Bit 0   | Quadrature(0)/Absolute(1)                |

Image /page/73/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

### **92 - Set Motor 1 Encoder Mode**

Set the Encoder Mode for motor 1. See command 91.

```
Send: [Address, 92, Mode, CRC(2 bytes)]
Receive: [0xFF]
```

#### **93 - Set Motor 2 Encoder Mode**

Set the Encoder Mode for motor 2. See command 91.

```
Send: [Address, 93, Mode, CRC(2 bytes)]
Receive: [0xFF]
```

### **94 - Write Settings to EEPROM**

Writes all settings to non-volatile memory. Values will be loaded after each power up.

Send: [Address, 94] Receive: [0xFF]

# **95 - Read Settings from EEPROM**

Read all settings from non-volatile memory.

Send: [Address, 95] Receive: [Enc1Mode, Enc2Mode, CRC(2 bytes)]

Image /page/74/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside it, followed by the word "BASICMICRO" in black, sans-serif font.

# **98 - Set Standard Config Settings**

# Set config bits for standard settings.

```
Send: [Address, 98, Config(2 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

| Function            | Config Bit Mask |
|---------------------|-----------------|
| RC Mode             | 0x0000          |
| Analog Mode         | 0x0001          |
| Simple Serial Mode  | 0x0002          |
| Packet Serial Mode  | 0x0003          |
| Battery Mode Off    | 0x0000          |
| Battery Mode Auto   | 0x0004          |
| Battery Mode 2 Cell | 0x0008          |
| Battery Mode 3 Cell | 0x000C          |
| Battery Mode 4 Cell | 0x0010          |
| Battery Mode 5 Cell | 0x0014          |
| Battery Mode 6 Cell | 0x0018          |
| Battery Mode 7 Cell | 0x001C          |
| Mixing              | 0x0020          |
| Exponential         | 0x0040          |
| MCU                 | 0x0080          |
| BaudRate 2400       | 0x0000          |
| BaudRate 9600       | 0x0020          |
| BaudRate 19200      | 0x0040          |
| BaudRate 38400      | 0x0060          |
| BaudRate 57600      | 0x0080          |
| BaudRate 115200     | 0x00A0          |
| BaudRate 230400     | 0x00C0          |
| BaudRate 460800     | 0x00E0          |
| FlipSwitch          | 0x0100          |
| Packet Address 0x80 | 0x0000          |
| Packet Address 0x81 | 0x0100          |
| Packet Address 0x82 | 0x0200          |
| Packet Address 0x83 | 0x0300          |
| Packet Address 0x84 | 0x0400          |
| Packet Address 0x85 | 0x0500          |
| Packet Address 0x86 | 0x0600          |
| Packet Address 0x87 | 0x0700          |
| Slave Mode          | 0x0800          |
| Relay Mode          | 0x1000          |
| Swap Encoders       | 0x2000          |
| Swap Buttons        | 0x4000          |
| Multi-Unit Mode     | 0x8000          |

Image /page/75/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

## **99 - Read Standard Config Settings**

Read config bits for standard settings See Command 98.

```
Send: [Address, 99]
Receive: [Config(2 bytes), CRC(2 bytes)]
```

## **100 - Set CTRL Modes**

Set CTRL modes of CTRL1 and CTRL2 output pins(available on select models).

Send: [Address, 20, CRC(2 bytes)] Receive: [0xFF]

On select models of Roboclaw, two Open drain, high current output drivers are available, CTRL1 and CTRL2.

| <b>Mode</b> | <b>Function</b> |
|-------------|-----------------|
| 0           | Disable         |
| 1           | User            |
| 2           | Voltage Clamp   |
| 3           | Brake           |

**User Mode** - The output level can be controlled by setting a value from  $0(0\%)$  to 65535(100%). A variable frequency PWM is generated at the specified percentage.

**Voltage Clamp Mode** - The CTRL output will activate when an over voltage is detected and released when the overvoltage disipates. Adding an external load dump resistor from the CTRL pin to B+ will allow the Roboclaw to disipate over voltage energy automatically(up to the 3amp limit of the CTRL pin).

**Brake Mode -** The CTRL pin can be used to activate an external brake(CTRL1 for Motor 1 brake and CTRL2 for Motor 2 brake). The signal will activate when the motor is stopped(eg 0 PWM). Note acceleration/default acceleration settings should be set appropriately to allow the motor to slow down before the brake is activated.

## **101 - Read CTRL Modes**

Read CTRL modes of CTRL1 and CTRL2 output pins(available on select models).

```
Send: [Address, 101]
Receive: [CTRL1Mode(1 bytes), CTRL2Mode(1 bytes), CRC(2 bytes)]
```

Reads CTRL1 and CTRL2 mode setting. See 100 - Set CTRL Modes for valid values.

# **102 - Set CTRL1**

Set CTRL1 output value(available on select models)

```
Send: [Address, 102, Value(2 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

Set the output state value of CTRL1. See 100 - Set CTRL Modes for valid values.

Image /page/76/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

## **103 - Set CTRL2**

Set CTRL2 output value(available on select models)

```
Send: [Address, 103, Value(2 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

Set the output state value of CTRL2. See 100 - Set CTRL Modes for valid values.

## **104 - Read CTRL Settings**

Read CTRL1 and CTRL2 output values(available on select models)

```
Send: [Address, 104]
Receive: [CTRL1(2 bytes), CTRL2(2 bytes), CRC(2 bytes)]
```

Reads currently set values for CTRL Settings. See 100 - Set CTRL Modes for valid values.

### **105 - Set Auto Homing Duty/Speed and Timeout for M1**

Sets the percentage of duty or max speed and the timeout value for automatic homing of motor 1. If the motor is set up for velocity or position control the percentage of maximum speed is used, otherwise percent duty is used. The range for duty/speed is 0 to 32767. The timeout value is 32 bits and is set in increments of 1/300 of a second. As an example, a timeout value of 10 seconds would be set as 3000.

```
Send: [Address, 105, Percentage(2 bytes), Timeout(4 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

### **106 - Set Auto Homing Duty/Speed and Timeout for M2**

Sets the percentage of duty or max speed and the timeout value for automatic homing of motor 2. If the motor is set up for velocity or position control the percentage of maximum speed is used, otherwise percent duty is used. The range for duty/speed is 0 to 32767. The timeout value is 32 bits and is set in increments of 1/300 of a second. As an example, a timeout value of 10 seconds would be set as 3000.

Send: [Address, 106, Percentage(2 bytes), Timeout(4 bytes), CRC(2 bytes)] Receive: [0xFF]

## **107 - Read Auto Homing Duty/Speed and Timeout Settings**

Read the current auto homing duty/speed and timeout settings.

```
Send: [Address, 107]
Receiver: [Percentage(2 bytes), Timeout(4 bytes), CRC(2 bytes)]
```

### **109 - Set Speed Error Limits**

Set motor speed error limits in encoder counts per second.

```
Send: [Address, 109, M1Limit(4 bytes), M2Limit(4 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

Image /page/77/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, with a stylized font.

## **110 - Read Speed Error Limits**

Read the current speed error limit values.

```
Send: [Address, 110]
Receive: [M1Limit(4 bytes), M2Limit(4 bytes), CRC(2 bytes)]
```

## **112 - Set Position Error Limits**

Set motor position error limits in encoder counts.

```
Send: [Address, 112, M1Limit(4 bytes), M2Limit(4 byes), CRC(2 bytes)]
Receive: [0xFF]
```

## **113 - Read Position Error Limits**

Read the current motor position error limits.

```
Send: [Address, 113]
Receive: [M1Limit(4 bytes), M2Limit(4 bytes), CRC(2 bytes)]
```

### **115 - Set Battery Voltage Offsets**

Set the main and logic battery offsets to correct for differences in voltage readings. Range of values is +/- 1V in .1V increments with a range of -10 to 10.

```
Send: [Address, 115, MainBatteryOffset, LogicBatteryOffset, CRC(2 bytes)]
Receive: [0xFF]
```

### **116 - Read Battery Voltage Offsets**

Read current voltage offset values.

```
Send: [Address, 116]
Receive: [MainBatteryOffset, LogicBatteryOffset, CRC(2 bytes)]
```

### **117 - Set Current Blanking Percentage**

Sets the percentage of PWM duty for which current readings will be blanked. This setting is used to prevent noise from low PWM duty from causing incorrect current readings. The range is 0 to 6554 (0 to 20%).

```
Send: [Address, 117, M1Blanking(2 bytes), M2Blanking(2 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

### **118 - Read Current Blanking Percentage**

Read the current blanking percentages.

```
Send: [Address, 118]
Receive: [M1Blanking(2 bytes), M2Blanking(2 bytes), CRC(2 bytes)]
```

Image /page/78/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with a white "B" inside it, followed by the word "BASICMICRO" in black, sans-serif font.

#### **133 - Set M1 Max Current Limit**

Set Motor 1 Maximum Current Limit. Current value is in 10ma units. To calculate multiply current limit by 100.

```
Send: [Address, 134, MaxCurrent(4 bytes), 0, 0, 0, 0, CRC(2 bytes)]
Receive: [0xFF]
```

#### **134 - Set M2 Max Current Limit**

Set Motor 2 Maximum Current Limit. Current value is in 10ma units. To calculate multiply current limit by 100.

```
Send: [Address, 134, MaxCurrent(4 bytes), 0, 0, 0, 0, CRC(2 bytes)]
Receive: [0xFF]
```

# **135 - Read M1 Max Current Limit**

Read Motor 1 Maximum Current Limit. Current value is in 10ma units. To calculate divide value by 100. MinCurrent is always 0.

```
Send: [Address, 135]
Receive: [MaxCurrent(4 bytes), MinCurrent(4 bytes), CRC(2 bytes)]
```

#### **136 - Read M2 Max Current Limit**

Read Motor 2 Maximum Current Limit. Current value is in 10ma units. To calculate divide value by 100. MinCurrent is always 0.

```
Send: [Address, 136]
Receive: [MaxCurrent(4 bytes), MinCurrent(4 bytes), CRC(2 bytes)]
```

#### **148 - Set PWM Mode**

Set PWM Drive mode. Locked Antiphase(0) or Sign Magnitude(1).

```
Send: [Address, 148, Mode, CRC(2 bytes)]
Receive: [0xFF]
```

#### **149 - Read PWM Mode**

Read PWM Drive mode. See Command 148.

```
Send: [Address, 149]
Receive: [PWMMode, CRC(2 bytes)]
```

#### **252 - Write User EEPROM Memory Location**

Write a 16 bit value to user EEPROM. The Address range is 0 to 255.

Send: [Address, 252, Memory Address, Value(2 bytes), CRC(2 bytes)] Receive: [0xFF]

Image /page/79/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **253 - Read User EEPROM Memory Location**

Read a 16 bit value from user EEPROM address. Memory address range is 0 to 255.

Send: [Address, 253, Memory Address] Receive: [Value(2 bytes), CRC(2 bytes)]

Image /page/80/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, block letters.

# **Encoders**

## **Closed Loop Modes**

RoboClaw supports a wide range of encoders for close loop modes. Encoders are used in velocity, position or a cascaded velocity with position control mode. This manual mainly deals with Quadrature and Absolute encoders. However additional types of encoders are supported.

## **Encoder Tuning**

All encoders will require tuning to properly function. Ion Studio incorperates an Auto Tune function which can automatically tune the PID and editable fields for manual tuning of the PID. Encoders can also be tunned using Advance Control Commands which can be sent by a MCU or other control devices.

### **Quadrature Encoders Wiring**

RoboClaw is capable of reading two quadrature encoders, one for each motor channel. The main header provides two +5VDC connections with dual A and B input signals for each encoder.

Quadrature encoders are directional. In a simple two motor robot, one motor will spin clock wise (CW) and the other motor will spin counter clock wise (CCW). The A and B inputs for one of the encoders must be reversed to allow both encoders to count up when the robot is moving forward. If both encoder are connected with leading edge pulse to channel A one will count up and the other down. This will cause commands like Mix Drive Forward to not work as expected. All motor and encoder combinations will need to be tuned. For model specific pinout information please refer to the data sheet for the model being used.

Image /page/80/Figure/10 description: This image shows a circuit diagram with several components. On the left side, there is a component labeled "MCU" with connections for UART TX, UART RX, 5VDC, and GROUND. These connections are linked to a component labeled "ROBOCLAW" with corresponding connections for RX0, TX0, +5V, and GROUND. Below the "MCU" and to the left of the "ROBOCLAW", there are two components labeled "Encoder 1" and "Encoder 2". "Encoder 1" has connections for A, B, GND, and +5V, which are linked to "ROBOCLAW" connections EN1 A, EN1 B, GROUND, and 5VDC, respectively. Similarly, "Encoder 2" has connections for A, B, GND, and +5V, which are linked to "ROBOCLAW" connections EN2 B, EN2 A, GROUND, and 5VDC, respectively. On the right side of the "ROBOCLAW", there are two components labeled "Motor 1" and "Motor 2". "Motor 1" is connected to "ROBOCLAW" via M1A and M1B, while "Motor 2" is connected via M2A and M2B. Additionally, there are components labeled R1, D1, and F1, along with a battery. The "ROBOCLAW" has connections for B+ and B-, which are linked to the battery through a switch, resistor R1, diode D1, and fuse F1.

Image /page/81/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside it, followed by the word "BASICMICRO" in black, sans-serif font.

# **Absolute Encoder Wiring**

RoboClaw is capable of reading absolute encoders that output an analog voltage. Like the Analog input modes for controlling the motors, the absolute encoder voltage must be between 0v and 2v. If using standard potentiometers as absolute encoders the 5v from the RoboClaw can be divided down to 2v at the potentiometer by adding a resistor from the 5v line on the RoboClaw to the potentiometer. For a 5k pot R1 / R2 = 7.5k, for a 10k pot R1 / R2 = 15k and for a 20k pot  $R1 / R2 = 30k$ .

The diagram below shows the main battery as the only power source. Make sure the LB jumper is installed. The 5VDC shown connected is only required if your MCU needs a power source. This is the BEC feature of RoboClaw. If the MCU has its own power source do not connect the 5VDC. For model specific pinout information please refer to the data sheet for the model being used.

Image /page/81/Figure/5 description: This image shows a wiring diagram for a RoboClaw motor controller. The diagram includes two potentiometers (Pot 1 and Pot 2), two motors (Motor 1 and Motor 2), a battery, a switch (SW1), and a diode (D1). The RoboClaw is connected to the potentiometers via the EN1 A and EN2 A pins, and to the motors via the M1A, M1B, M2A, and M2B pins. The battery is connected to the RoboClaw via the Positive + and Negative - pins, and the switch and diode are connected in series between the battery and the Positive + pin. The diagram also shows the UART TX, UART RX, 5VDC, and GROUND connections.

Image /page/82/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with a white "B" inside it, followed by the word "BASICMICRO" in black, sans-serif font. The logo is placed between two horizontal black lines.

# **Encoder Tuning**

To control motor speed and or position with an encoder the PID must be calibrated for the specific motor and encoder being used. Using Motion Studio the PID can be tuned manually or by the auto tune fucntion. Once the encoders are tuned the settings can be saved to the onboard eeprom and will be loaded each time the unit powers up.

The Motion Studio window for Velocity Settings will auto tune for velocity. The window for Position Settings can tune a simple PD position controller, a PID position controller or a cascaded Position with Velocity controller(PIV). The cascaded tune will determine both the velocity and position values for the motor. Auto tune functions usually return reasonable values but manual adjustments may be required for optimum performance.

# **Auto Tuning**

Motion Studio provides the option to auto tune velocity and position control. To use the auto tune option make sure the encoder and motor are running in the desired direction and the basic PWM control of the motor works as expected. It is recommend to ensure the motor and encoder combination are functioning properly before using the auto tune feature.

1. Go to the PWM Settings screen in Motion Studio.

2. Slide the motor slider up to start moving the motor forward. Check the encoder is increasing in value. If it is not either reverse the motor wires or the encoder wires. The recheck.

3. To start auto tune click the auto tune button for the motor channel that is will be tuned first. The auto tune function will try to determine the best settings for that motor channel.

Image /page/82/Picture/10 description: The image shows a yellow warning sign with a black border. Inside the triangle is a black exclamation point.

**If the motor or encoder are wired incorrectly, the auto tune function can lock up and the motor controller will become unresponsive. Correct the wiring problem and reset the motor controller to continue.**

Image /page/83/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in a stylized, sans-serif font.

# **Manual Velocity Calibration Procedure**

1. Determine the quadrature pulses per second(QPPS) value for your motor. The simplest method to do this is to run the Motor at 100% duty using Ion Studio and read back the speed value from the encoder attached to the motor. If you are unable to run the motor like this due to physical constraints you will need to estimate the maximum speed in encoder counts the motor can produce.

2. Set the initial P, I and D values in the Velocity control window to 1,0 and 0. Try moving the motor using the slider controls in IonMotion. If the motor does not move it may not be wired correctly or the P value needs to be increased. If the motor immediately runs at max speed when you change the slider position you probably have the motor or encoder wires reversed. The motor is trying to go at the speed specified but the encoder reading is coming back in the opposite direction so the motor increases power until it eventually hits 100% power. Reverse the encoder or motor wires(not both) and test again.

3. Once the motor has some semblance of control you can set a moderate speed. Then start increasing the P value until the speed reading is near the set value. If the motor feels like it is vibrating at higher P values you should reduce the P value to about 2/3rds that value. Move on to the I setting.

4. Start increasing the I setting. You will usually want to increase this value by .1 increments. The I value helps the motor reach the exact speed specified. Too high an I value will also cause the motor to feel rough/vibrate. This is because the motor will over shoot the set speed and then the controller will reduce power to get the speed back down which will also under shoot and this will continue oscillating back and forth form too fast to too slow, causing a vibration in the motor.

5. Once P and I are set reasonably well usually you will leave  $D = 0$ . D is only required if you are unable to get reasonable speed control out of the motor using just P and I. D will help dampen P and I over shoot allowing higher P and I values, but D also increases noise in the calculation which can cause oscillations in the speed as well.

# **Manual Position Calibration Procedure**

1. Position mode requires the Velocity mode QPPS value be set as described above. For simple Position control you can set Velocity P, I and D all to 0.

2. Set the Position I and D settings to 0. Set the P setting to 2000 as a reasonable starting point. To test the motor you must also set the Speed argument to some value. We recommend setting it to the same value as the QPPS setting(eg maximum motor speed). Set the minimum and maximum position values to safe numbers. If your motor has no dead stops this can be +-2 billion. If your motor has specific dead stops(like on a linear actuator) you will need to manually move the motor to its dead stops to determine these numbers. Leave some margin infront of each deadstop. Note that when using quadrature encoders you will need to home your motor on every power up since the quadrature readings are all relative to the starting position unless you set/reset the encoder values.

3. At this point the motor should move in the appropriate direction and stop, not necessarily close to the set position when you move the slider. Increase the P setting until the position is over shooting some each time you change the position slider. Now start increasing the D setting(leave I at 0). Increasing D will add dampening to the movement when getting close to the set position. This will help prevent the over shoot. D will usually be anywhere from 5 to 20 times larger than P but not always. Continue increasing P and D until the motor is working reasonably well. Once it is you have tuned a simple PD system.

Image /page/84/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in a sans-serif font.

4. Once your position control is acting relatively smoothly and coming close to the set position you can think about adjusting the I setting. Adding I will help reach the exact set point specified but in most motor systems there is enough slop in the gears that instead you will end up causing an oscillation around the specified position. This is called hunting. The I setting causes this when there is any slop in the motor/encoder/gear train. You can compensate some for this by adding deadzone. Deadzone is the area around the specified position the controller will consider to be equal to the position specified.

5. One more setting must be adjusted in order to use the I setting. The Imax value sets the maximum wind up allowed for the I setting calculation. Increasing Imax will allow I to affect a larger amount of the movement of the motor but will also allow the system to oscillate if used with a badly tuned I and/or set too high.

Image /page/85/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **Encoder Commands**

The following commands are used with the encoders both quadrature and absolute. The Encoder Commands are used to read the register values for both encoder channels.

| <b>Command</b> | <b>Description</b>                                       |
|----------------|----------------------------------------------------------|
| 16             | Read Encoder Count/Value for M1.                         |
| 17             | Read Encoder Count/Value for M2.                         |
| 18             | Read M1 Speed in Encoder Counts Per Second.              |
| 19             | Read M2 Speed in Encoder Counts Per Second.              |
| 20             | Resets Encoder Registers for M1 and M2(Quadrature only). |
| 22             | Set Encoder 1 Register (Quadrature only).                |
| 23             | Set Encoder 2 Register (Quadrature only).                |
| 30             | Read Current M1 Raw Speed                                |
| 31             | Read Current M2 Raw Speed                                |
| 78             | Read Encoders Counts                                     |
| 79             | Read Raw Motor Speeds                                    |
| 108            | Read Motor Average Speeds                                |
| 111            | Read Speed Errors                                        |
| 114            | Read Position Errors                                     |

# **16 - Read Encoder Count/Value M1**

Read M1 encoder count/position.

```
Send: [Address, 16]
Receive: [Enc1(4 bytes), Status, CRC(2 bytes)]
```

Quadrature encoders have a range of 0 to 4,294,967,295. Absolute encoder values are converted from an analog voltage into a value from 0 to 2047 for the full 2v range.

The status byte tracks counter underflow, direction and overflow. The byte value represents:

- Bit0 Counter Underflow (1= Underflow Occurred, Clear After Reading)
- Bit1 Direction ( $0 =$  Forward,  $1 =$  Backwards)
- Bit2 Counter Overflow (1= Underflow Occurred, Clear After Reading)
- Bit3 Reserved
- Bit4 Reserved
- Bit5 Reserved
- Bit6 Reserved
- Bit7 Reserved

Image /page/86/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **17 - Read Quadrature Encoder Count/Value M2**

Read M2 encoder count/position.

```
Send: [Address, 17]
Receive: [EncCnt(4 bytes), Status, CRC(2 bytes)]
```

Quadrature encoders have a range of 0 to 4,294,967,295. Absolute encoder values are converted from an analog voltage into a value from 0 to 2047 for the full 2v range.

The Status byte tracks counter underflow, direction and overflow. The byte value represents:

Bit0 - Counter Underflow (1= Underflow Occurred, Cleared After Reading)

- Bit1 Direction ( $0 =$  Forward,  $1 =$  Backwards)
- Bit2 Counter Overflow (1= Underflow Occurred, Cleared After Reading)
- Bit3 Reserved
- Bit4 Reserved
- Bit5 Reserved
- Bit6 Reserved
- Bit7 Reserved

### **18 - Read Encoder Speed M1**

Read M1 counter speed. Returned value is in pulses per second. RoboClaw keeps track of how many pulses received per second for both encoder channels.

Send: [Address, 18] Receive: [Speed(4 bytes), Status, CRC(2 bytes)]

Status indicates the direction  $(0 - forward, 1 - backward)$ .

#### **19 - Read Encoder Speed M2**

Read M2 counter speed. Returned value is in pulses per second. RoboClaw keeps track of how many pulses received per second for both encoder channels.

```
Send: [Address, 19]
Receive: [Speed(4 bytes), Status, CRC(2 bytes)]
```

Status indicates the direction  $(0 - forward, 1 - backward)$ .

#### **20 - Reset Quadrature Encoder Counters**

Will reset both quadrature decoder counters to zero. This command applies to quadrature encoders only.

```
Send: [Address, 20, CRC(2 bytes)]
Receive: [0xFF]
```

Image /page/87/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

#### **22 - Set Quadrature Encoder 1 Value**

Set the value of the Encoder 1 register. Useful when homing motor 1. This command applies to quadrature encoders only.

```
Send: [Address, 22, Value(4 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

#### **23 - Set Quadrature Encoder 2 Value**

Set the value of the Encoder 2 register. Useful when homing motor 2. This command applies to quadrature encoders only.

```
Send: [Address, 23, Value(4 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

#### **30 - Read Raw Speed M1**

Read the pulses counted in that last 300th of a second. This is an unfiltered version of command 18. Command 30 can be used to make a independent PID routine. Value returned is in encoder counts per second.

```
Send: [Address, 30]
Receive: [Speed(4 bytes), Status, CRC(2 bytes)]
```

The Status byte is direction  $(0 - forward, 1 - backward)$ .

#### **31 - Read Raw Speed M2**

Read the pulses counted in that last 300th of a second. This is an unfiltered version of command 19. Command 31 can be used to make a independent PID routine. Value returned is in encoder counts per second.

```
Send: [Address, 31]
Receive: [Speed(4 bytes), Status, CRC(2 bytes)]
```

The Status byte is direction  $(0 - forward, 1 - backward)$ .

## **78 - Read Encoder Counters**

Read M1 and M2 encoder counters. Quadrature encoders have a range of 0 to 4,294,967,295. Absolute encoder values are converted from an analog voltage into a value from 0 to 2047 for the full 2V analog range.

Send: [Address, 78] Receive: [Enc1(4 bytes), Enc2(4 bytes), CRC(2 bytes)]

#### **79 - Read ISpeeds Counters**

Read M1 and M2 instantaneous speeds. Returns the speed in encoder counts per second for the last 300th of a second for both encoder channels.

```
Send: [Address, 79]
Receive: [ISpeed1(4 bytes), ISpeed2(4 bytes), CRC(2 bytes)]
```

Image /page/88/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside it, followed by the word "BASICMICRO" in black, sans-serif font.

# **108 - Read Motor Average Speeds**

Read M1 and M2 average speeds. Return the speed in encoder counts per second for the last second for both encoder channels.

```
Send: [Address, 108]
Receive: [Speed1(4 bytes), Speed2(4 bytes), CRC(2 bytes)]
```

## **111 - Read Speed Errors**

Read current calculated speed error in encoder counts per second.

```
Send: [Address, 111]
Receive; [M1Error(4 bytes), M2Error(4 bytes), CRC(2 bytes)]
```

### **114 - Read Position Errors**

Read current calculated position error in encoder counts.

```
Send: [Address, 114]
Receive: [M1Error(4 bytes), M2Error(4 bytes], CRC(2 bytes)]
```

Image /page/89/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **Advanced Motor Control**

## **Advanced Motor Control Commands**

The following commands are used to control motor speeds, acceleration distance and position using encoders. The PID can also be manually adjusted using Advanced Motor Control Commands.

| <b>Command</b> | <b>Description</b>                                                    |
|----------------|-----------------------------------------------------------------------|
| 28             | Set Velocity PID Constants for M1.                                    |
| 29             | Set Velocity PID Constants for M2.                                    |
| 32             | Drive M1 With Signed Duty Cycle. (Encoders not required)              |
| 33             | Drive M2 With Signed Duty Cycle. (Encoders not required)              |
| 34             | Drive M1 / M2 With Signed Duty Cycle. (Encoders not required)         |
| 35             | Drive M1 With Signed Speed.                                           |
| 36             | Drive M2 With Signed Speed.                                           |
| 37             | Drive M1 / M2 With Signed Speed.                                      |
| 38             | Drive M1 With Signed Speed And Acceleration.                          |
| 39             | Drive M2 With Signed Speed And Acceleration.                          |
| 40             | Drive M1 / M2 With Signed Speed And Acceleration.                     |
| 41             | Drive M1 With Signed Speed And Distance. Buffered.                    |
| 42             | Drive M2 With Signed Speed And Distance. Buffered.                    |
| 43             | Drive M1 / M2 With Signed Speed And Distance. Buffered.               |
| 44             | Drive M1 With Signed Speed, Acceleration and Distance. Buffered.      |
| 45             | Drive M2 With Signed Speed, Acceleration and Distance. Buffered.      |
| 46             | Drive M1 / M2 With Signed Speed, Acceleration And Distance. Buffered. |
| 47             | Read Buffer Length.                                                   |
| 50             | Drive M1 / M2 With Individual Signed Speed and Acceleration           |
| 51             | Drive M1 / M2 With Individual Signed Speed, Accel and Distance        |
| 52             | Drive M1 With Signed Duty and Accel. (Encoders not required)          |
| 53             | Drive M2 With Signed Duty and Accel. (Encoders not required)          |
| 54             | Drive M1 / M2 With Signed Duty and Accel. (Encoders not required)     |
| 55             | Read Motor 1 Velocity PID Constants                                   |
| 56             | Read Motor 2 Velocity PID Constants                                   |
| 61             | Set Position PID Constants for M1.                                    |
| 62             | Set Position PID Constants for M2                                     |
| 63             | Read Motor 1 Position PID Constants                                   |
| 64             | Read Motor 2 Position PID Constants                                   |
| 65             | Drive M1 with Speed, Accel, Deccel and Position                       |
| 66             | Drive M2 with Speed, Accel, Deccel and Position                       |
| 67             | Drive M1 / M2 with Speed, Accel, Deccel and Position                  |
| 119            | Drive M1 with Position.                                               |
| 120            | Drive M2 with Position.                                               |
| 121            | Drive M1/M2 with Position.                                            |
| 122            | Drive M1 with Speed and Position.                                     |
| 123            | Drive M2 with Speed and Position.                                     |
| 124            | Drive M1/M2 with Speed and Position.                                  |

Image /page/90/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

# **28 - Set Velocity PID Constants M1**

Several motor and quadrature combinations can be used with RoboClaw. In some cases the default PID values will need to be tuned for the systems being driven. This gives greater flexibility in what motor and encoder combinations can be used. The RoboClaw PID system consist of four constants starting with QPPS,  $P =$  Proportional, I = Integral and D = Derivative. The defaults values are:

 $OPPS = 44000$  $P = 0 \times 00010000$  $I = 0x00008000$  $D = 0 \times 00004000$ 

QPPS is the speed of the encoder when the motor is at 100% power. P, I, D are the default values used after a reset. Command syntax:

```
Send: [Address, 28, D(4 bytes), P(4 bytes), I(4 bytes), QPPS(4 byte), CRC(2 bytes)]
Receive: [0xFF]
```

### **29 - Set Velocity PID Constants M2**

Several motor and quadrature combinations can be used with RoboClaw. In some cases the default PID values will need to be tuned for the systems being driven. This gives greater flexibility in what motor and encoder combinations can be used. The RoboClaw PID system consist of four constants starting with QPPS,  $P =$  Proportional, I = Integral and D = Derivative. The defaults values are:

 $OPPS = 44000$  $P = 0 \times 00010000$  $I = 0 \times 00008000$  $D = 0 \times 00004000$ 

QPPS is the speed of the encoder when the motor is at 100% power. P, I, D are the default values used after a reset. Command syntax:

```
Send: [Address, 29, D(4 bytes), P(4 bytes), I(4 bytes), QPPS(4 byte), CRC(2 bytes)]Re-
ceive: [0xFF]
```

# **32 - Drive M1 With Signed Duty Cycle**

Drive M1 using a duty cycle value. The duty cycle is used to control the speed of the motor without a quadrature encoder.

Send: [Address, 32, Duty(2 Bytes), CRC(2 bytes)] Receive: [0xFF]

The duty value is signed and the range is  $-32767$  to  $+32767$  (eg.  $+100\%$  duty).

Image /page/91/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside it, followed by the word "BASICMICRO" in black, sans-serif font.

### **33 - Drive M2 With Signed Duty Cycle**

Drive M2 using a duty cycle value. The duty cycle is used to control the speed of the motor without a quadrature encoder. The command syntax:

Send: [Address, 33, Duty(2 Bytes), CRC(2 bytes)] Receive: [0xFF]

The duty value is signed and the range is  $-32768$  to  $+32767$  (eg.  $+100\%$  duty).

# **34 - Drive M1 / M2 With Signed Duty Cycle**

Drive both M1 and M2 using a duty cycle value. The duty cycle is used to control the speed of the motor without a quadrature encoder. The command syntax:

Send: [Address, 34, DutyM1(2 Bytes), DutyM2(2 Bytes), CRC(2 bytes)] Receive: [0xFF]

The duty value is signed and the range is -32768 to  $+32767$  (eg.  $+100\%$  duty).

Image /page/92/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

### **35 - Drive M1 With Signed Speed**

Drive M1 using a speed value. The sign indicates which direction the motor will turn. This command is used to drive the motor by quad pulses per second. Different quadrature encoders will have different rates at which they generate the incoming pulses. The values used will differ from one encoder to another. Once a value is sent the motor will begin to accelerate as fast as possible until the defined rate is reached.

```
Send: [Address, 35, Speed(4 Bytes), CRC(2 bytes)]
Receive: [0xFF]
```

### **36 - Drive M2 With Signed Speed**

Drive M2 with a speed value. The sign indicates which direction the motor will turn. This command is used to drive the motor by quad pulses per second. Different quadrature encoders will have different rates at which they generate the incoming pulses. The values used will differ from one encoder to another. Once a value is sent, the motor will begin to accelerate as fast as possible until the rate defined is reached.

```
Send: [Address, 36, Speed(4 Bytes), CRC(2 bytes)]
Receive: [0xFF]
```

# **37 - Drive M1 / M2 With Signed Speed**

Drive M1 and M2 in the same command using a signed speed value. The sign indicates which direction the motor will turn. This command is used to drive both motors by quad pulses per second. Different quadrature encoders will have different rates at which they generate the incoming pulses. The values used will differ from one encoder to another. Once a value is sent the motor will begin to accelerate as fast as possible until the rate defined is reached.

```
Send: [Address, 37, SpeedM1(4 Bytes), SpeedM2(4 Bytes), CRC(2 bytes)]
Receive: [0xFF]
```

### **38 - Drive M1 With Signed Speed And Acceleration**

Drive M1 with a signed speed and acceleration value. The sign indicates which direction the motor will run. The acceleration values are not signed. This command is used to drive the motor by quad pulses per second and using an acceleration value for ramping. Different quadrature encoders will have different rates at which they generate the incoming pulses. The values used will differ from one encoder to another. Once a value is sent the motor will begin to accelerate incrementally until the rate defined is reached.

```
Send: [Address, 38, Accel(4 Bytes), Speed(4 Bytes), CRC(2 bytes)]
Receive: [0xFF]
```

The acceleration is measured in speed increase per second. An acceleration value of 12,000 QPPS with a speed of 12,000 QPPS would accelerate a motor from 0 to 12,000 QPPS in 1 second. Another example would be an acceleration value of 24,000 QPPS and a speed value of 12,000 QPPS would accelerate the motor to 12,000 QPPS in 0.5 seconds.

Image /page/93/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

### **39 - Drive M2 With Signed Speed And Acceleration**

Drive M2 with a signed speed and acceleration value. The sign indicates which direction the motor will run. The acceleration value is not signed. This command is used to drive the motor by quad pulses per second and using an acceleration value for ramping. Different quadrature encoders will have different rates at which they generate the incoming pulses. The values used will differ from one encoder to another. Once a value is sent the motor will begin to accelerate incrementally until the rate defined is reached.

```
Send: [Address, 39, Accel(4 Bytes), Speed(4 Bytes), CRC(2 bytes)]
Receive: [0xFF]
```

The acceleration is measured in speed increase per second. An acceleration value of 12,000 QPPS with a speed of 12,000 QPPS would accelerate a motor from 0 to 12,000 QPPS in 1 second. Another example would be an acceleration value of 24,000 QPPS and a speed value of 12,000 QPPS would accelerate the motor to 12,000 QPPS in 0.5 seconds.

#### **40 - Drive M1 / M2 With Signed Speed And Acceleration**

Drive M1 and M2 in the same command using one value for acceleration and two signed speed values for each motor. The sign indicates which direction the motor will run. The acceleration value is not signed. The motors are sync during acceleration. This command is used to drive the motor by quad pulses per second and using an acceleration value for ramping. Different quadrature encoders will have different rates at which they generate the incoming pulses. The values used will differ from one encoder to another. Once a value is sent the motor will begin to accelerate incrementally until the rate defined is reached.

Send: [Address, 40, Accel(4 Bytes), SpeedM1(4 Bytes), SpeedM2(4 Bytes), CRC(2 bytes)] Receive: [0xFF]

The acceleration is measured in speed increase per second. An acceleration value of 12,000 QPPS with a speed of 12,000 QPPS would accelerate a motor from 0 to 12,000 QPPS in 1 second. Another example would be an acceleration value of 24,000 QPPS and a speed value of 12,000 QPPS would accelerate the motor to 12,000 QPPS in 0.5 seconds.

#### **41 - Buffered M1 Drive With Signed Speed And Distance**

Drive M1 with a signed speed and distance value. The sign indicates which direction the motor will run. The distance value is not signed. This command is buffered. This command is used to control the top speed and total distance traveled by the motor. Each motor channel M1 and M2 have separate buffers. This command will execute immediately if no other command for that channel is executing, otherwise the command will be buffered in the order it was sent. Any buffered or executing command can be stopped when a new command is issued by setting the Buffer argument. All values used are in quad pulses per second.

Send: [Address, 41, Speed(4 Bytes), Distance(4 Bytes), Buffer, CRC(2 bytes)] Receive: [0xFF]

The Buffer argument can be set to a 1 or 0. If a value of 0 is used the command will be buffered and executed in the order sent. If a value of 1 is used the current running command is stopped, any other commands in the buffer are deleted and the new command is executed.

Image /page/94/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside it, followed by the word "BASICMICRO" in black, sans-serif font.

### **42 - Buffered M2 Drive With Signed Speed And Distance**

Drive M2 with a speed and distance value. The sign indicates which direction the motor will run. The distance value is not signed. This command is buffered. Each motor channel M1 and M2 have separate buffers. This command will execute immediately if no other command for that channel is executing, otherwise the command will be buffered in the order it was sent. Any buffered or executing command can be stopped when a new command is issued by setting the Buffer argument. All values used are in quad pulses per second.

Send: [Address, 42, Speed(4 Bytes), Distance(4 Bytes), Buffer, CRC(2 bytes)] Receive: [0xFF]

The Buffer argument can be set to a 1 or 0. If a value of 0 is used the command will be buffered and executed in the order sent. If a value of 1 is used the current running command is stopped, any other commands in the buffer are deleted and the new command is executed.

#### **43 - Buffered Drive M1 / M2 With Signed Speed And Distance**

Drive M1 and M2 with a speed and distance value. The sign indicates which direction the motor will run. The distance value is not signed. This command is buffered. Each motor channel M1 and M2 have separate buffers. This command will execute immediately if no other command for that channel is executing, otherwise the command will be buffered in the order it was sent. Any buffered or executing command can be stopped when a new command is issued by setting the Buffer argument. All values used are in quad pulses per second.

```
Send: [Address, 43, SpeedM1(4 Bytes), DistanceM1(4 Bytes),
             SpeedM2(4 Bytes), DistanceM2(4 Bytes), Buffer, CRC(2 bytes)]
Receive: [0xFF]
```

The Buffer argument can be set to a 1 or 0. If a value of 0 is used the command will be buffered and executed in the order sent. If a value of 1 is used the current running command is stopped, any other commands in the buffer are deleted and the new command is executed.

#### **44 - Buffered M1 Drive With Signed Speed, Accel And Distance**

Drive M1 with a speed, acceleration and distance value. The sign indicates which direction the motor will run. The acceleration and distance values are not signed. This command is used to control the motors top speed, total distanced traveled and at what incremental acceleration value to use until the top speed is reached. Each motor channel M1 and M2 have separate buffers. This command will execute immediately if no other command for that channel is executing, otherwise the command will be buffered in the order it was sent. Any buffered or executing command can be stopped when a new command is issued by setting the Buffer argument. All values used are in quad pulses per second.

```
Send: [Address, 44, Accel(4 bytes), Speed(4 Bytes), Distance(4 Bytes),
             Buffer, CRC(2 bytes)]
Receive: [0xFF]
```

The Buffer argument can be set to a 1 or 0. If a value of 0 is used the command will be buffered and executed in the order sent. If a value of 1 is used the current running command is stopped, any other commands in the buffer are deleted and the new command is executed.

**BASICMICRO** 

# **RoboClaw Series Brushed DC Motor Controllers**

### **45 - Buffered M2 Drive With Signed Speed, Accel And Distance**

Drive M2 with a speed, acceleration and distance value. The sign indicates which direction the motor will run. The acceleration and distance values are not signed. This command is used to control the motors top speed, total distanced traveled and at what incremental acceleration value to use until the top speed is reached. Each motor channel M1 and M2 have separate buffers. This command will execute immediately if no other command for that channel is executing, otherwise the command will be buffered in the order it was sent. Any buffered or executing command can be stopped when a new command is issued by setting the Buffer argument. All values used are in quad pulses per second.

Send: [Address, 45, Accel(4 bytes), Speed(4 Bytes), Distance(4 Bytes), Buffer, CRC(2 bytes)] Receive: [0xFF]

The Buffer argument can be set to a 1 or 0. If a value of 0 is used the command will be buffered and executed in the order sent. If a value of 1 is used the current running command is stopped, any other commands in the buffer are deleted and the new command is executed.

#### **46 - Buffered Drive M1 / M2 With Signed Speed, Accel And Distance**

Drive M1 and M2 with a speed, acceleration and distance value. The sign indicates which direction the motor will run. The acceleration and distance values are not signed. This command is used to control both motors top speed, total distanced traveled and at what incremental acceleration value to use until the top speed is reached. Each motor channel M1 and M2 have separate buffers. This command will execute immediately if no other command for that channel is executing, otherwise the command will be buffered in the order it was sent. Any buffered or executing command can be stopped when a new command is issued by setting the Buffer argument. All values used are in quad pulses per second.

```
Send: [Address, 46, Accel(4 Bytes), SpeedM1(4 Bytes), DistanceM1(4 Bytes),
      SpeedM2(4 bytes), DistanceM2(4 Bytes), Buffer, CRC(2 bytes)]
Receive: [0xFF]
```

The Buffer argument can be set to a 1 or 0. If a value of 0 is used the command will be buffered and executed in the order sent. If a value of 1 is used the current running command is stopped, any other commands in the buffer are deleted and the new command is executed.

### **47 - Read Buffer Length**

Read both motor M1 and M2 buffer lengths. This command can be used to determine how many commands are waiting to execute.

```
Send: [Address, 47]
Receive: [BufferM1, BufferM2, CRC(2 bytes)]
```

The return values represent how many commands per buffer are waiting to be executed. The maximum buffer size per motor is 64 commands(0x3F). A return value of 0x80(128) indicates the buffer is empty. A return value of 0 indiciates the last command sent is executing. A value of 0x80 indicates the last command buffered has finished.

Image /page/96/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

### **50 - Drive M1 / M2 With Signed Speed And Individual Acceleration**

Drive M1 and M2 in the same command using one value for acceleration and two signed speed values for each motor. The sign indicates which direction the motor will run. The acceleration value is not signed. The motors are sync during acceleration. This command is used to drive the motor by quad pulses per second and using an acceleration value for ramping. Different quadrature encoders will have different rates at which they generate the incoming pulses. The values used will differ from one encoder to another. Once a value is sent the motor will begin to accelerate incrementally until the rate defined is reached.

Send: [Address, 50, AccelM1(4 Bytes), SpeedM1(4 Bytes), AccelM2(4 Bytes), SpeedM2(4 Bytes), CRC(2 bytes)] Receive: [0xFF]

The acceleration is measured in speed increase per second. An acceleration value of 12,000 QPPS with a speed of 12,000 QPPS would accelerate a motor from 0 to 12,000 QPPS in 1 second. Another example would be an acceleration value of 24,000 QPPS and a speed value of 12,000 QPPS would accelerate the motor to 12,000 QPPS in 0.5 seconds.

### **51 - Buffered Drive M1 / M2 With Signed Speed, Individual Accel And Distance**

Drive M1 and M2 with a speed, acceleration and distance value. The sign indicates which direction the motor will run. The acceleration and distance values are not signed. This command is used to control both motors top speed, total distanced traveled and at what incremental acceleration value to use until the top speed is reached. Each motor channel M1 and M2 have separate buffers. This command will execute immediately if no other command for that channel is executing, otherwise the command will be buffered in the order it was sent. Any buffered or executing command can be stopped when a new command is issued by setting the Buffer argument. All values used are in quad pulses per second.

Send: [Address, 51, AccelM1(4 Bytes), SpeedM1(4 Bytes), DistanceM1(4 Bytes), AccelM2(4 Bytes), SpeedM2(4 bytes), DistanceM2(4 Bytes), Buffer, CRC(2 bytes)] Receive: [0xFF]

The Buffer argument can be set to a 1 or 0. If a value of 0 is used the command will be buffered and executed in the order sent. If a value of 1 is used the current running command is stopped, any other commands in the buffer are deleted and the new command is executed.

### **52 - Drive M1 With Signed Duty And Acceleration**

Drive M1 with a signed duty and acceleration value. The sign indicates which direction the motor will run. The acceleration values are not signed. This command is used to drive the motor by PWM and using an acceleration value for ramping. Accel is the rate per second at which the duty changes from the current duty to the specified duty.

Send: [Address, 52, Duty(2 bytes), Accel(2 Bytes), CRC(2 bytes)] Receive: [0xFF]

The duty value is signed and the range is  $-32768$  to  $+32767$  (eg.  $+100\%$  duty). The accel value range is 0 to 655359(eg maximum acceleration rate is -100% to 100% in 100ms).

Image /page/97/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

#### **53 - Drive M2 With Signed Duty And Acceleration**

Drive M1 with a signed duty and acceleration value. The sign indicates which direction the motor will run. The acceleration values are not signed. This command is used to drive the motor by PWM and using an acceleration value for ramping. Accel is the rate at which the duty changes from the current duty to the specified dury.

```
Send: [Address, 53, Duty(2 bytes), Accel(2 Bytes), CRC(2 bytes)]
Receive: [0xFF]
```

The duty value is signed and the range is -32768 to  $+32767$  (eg.  $+100\%$  duty). The accel value range is 0 to 655359 (eg maximum acceleration rate is -100% to 100% in 100ms).

#### **54 - Drive M1 / M2 With Signed Duty And Acceleration**

Drive M1 and M2 in the same command using acceleration and duty values for each motor. The sign indicates which direction the motor will run. The acceleration value is not signed. This command is used to drive the motor by PWM using an acceleration value for ramping. The command syntax:

```
Send: [Address, CMD, DutyM1(2 bytes), AccelM1(4 Bytes), DutyM2(2 bytes), 
      AccelM1(4 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

The duty value is signed and the range is  $-32768$  to  $+32767$  (eg.  $+-100\%$  duty). The accel value range is 0 to 655359 (eg maximum acceleration rate is -100% to 100% in 100ms).

#### **55 - Read Motor 1 Velocity PID and QPPS Settings**

Read the PID and QPPS Settings.

```
Send: [Address, 55]
Receive: [P(4 bytes), I(4 bytes), D(4 bytes), QPPS(4 byte), CRC(2 bytes)]
```

### **56 - Read Motor 2 Velocity PID and QPPS Settings**

Read the PID and QPPS Settings.

```
Send: [Address, 56]
Receive: [P(4 bytes), I(4 bytes), D(4 bytes), QPPS(4 byte), CRC(2 bytes)]
```

#### **61 - Set Motor 1 Position PID Constants**

The RoboClaw Position PID system consist of seven constants starting with  $P =$  Proportional, I= Integral and D= Derivative, MaxI = Maximum Integral windup, Deadzone in encoder counts, MinPos = Minimum Position and MaxPos = Maximum Position. The defaults values are all zero.

```
Send: [Address, 61, D(4 bytes), P(4 bytes), I(4 bytes), MaxI(4 bytes),
      Deadzone(4 bytes), MinPos(4 bytes), MaxPos(4 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

Position constants are used only with the Position commands, 65,66 and 67 or when encoders are enabled in RC/Analog modes.

Image /page/98/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.

#### **62 - Set Motor 2 Position PID Constants**

The RoboClaw Position PID system consist of seven constants starting with  $P =$  Proportional, I= Integral and D= Derivative, MaxI = Maximum Integral windup, Deadzone in encoder counts, MinPos = Minimum Position and MaxPos = Maximum Position. The defaults values are all zero.

```
Send: [Address, 62, D(4 bytes), P(4 bytes), I(4 bytes), MaxI(4 bytes),
      Deadzone(4 bytes), MinPos(4 bytes), MaxPos(4 bytes), CRC(2 bytes)]
Receive: [0xFF]
```

Position constants are used only with the Position commands, 65,66 and 67 or when encoders are enabled in RC/Analog modes.

### **63 - Read Motor 1 Position PID Constants**

Read the Position PID Settings.

```
Send: [Address, 63]
Receive: [P(4 bytes), I(4 bytes), D(4 bytes), MaxI(4 byte), Deadzone(4 byte),
              MinPos(4 byte), MaxPos(4 byte), CRC(2 bytes)]
```

#### **64 - Read Motor 2 Position PID Constants**

Read the Position PID Settings.

```
Send: [Address, 64]
Receive: [P(4 bytes), I(4 bytes), D(4 bytes), MaxI(4 byte), Dedzone(4 byte), MinPos(4 byte), MaxPos(4 byte), CRC(2 bytes)]
```

#### **65 - Buffered Drive M1 with signed Speed, Accel, Deccel and Position**

Move M1 position from the current position to the specified new position and hold the new position. Accel sets the acceleration value and deccel the decceleration value. QSpeed sets the speed in quadrature pulses the motor will run at after acceleration and before decceleration.

Send: [Address, 65, Accel(4 bytes), Speed(4 Bytes), Deccel(4 bytes), Position(4 Bytes), Buffer, CRC(2 bytes)] Receive: [0xFF]

#### **66 - Buffered Drive M2 with signed Speed, Accel, Deccel and Position**

Move M2 position from the current position to the specified new position and hold the new position. Accel sets the acceleration value and deccel the decceleration value. QSpeed sets the speed in quadrature pulses the motor will run at after acceleration and before decceleration.

```
Send: [Address, 66, Accel(4 bytes), Speed(4 Bytes), Deccel(4 bytes),
             Position(4 Bytes), Buffer, CRC(2 bytes)]
Receive: [0xFF]
```

Image /page/99/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in a bold, sans-serif font.

#### **67 - Buffered Drive M1 & M2 with signed Speed, Accel, Deccel and Position**

Move M1 & M2 positions from their current positions to the specified new positions and hold the new positions. Accel sets the acceleration value and deccel the decceleration value. QSpeed sets the speed in quadrature pulses the motor will run at after acceleration and before decceleration.

```
Send: [Address, 67, AccelM1(4 bytes), SpeedM1(4 Bytes), DeccelM1(4 bytes),
             PositionM1(4 Bytes), AccelM2(4 bytes), SpeedM2(4 Bytes), DeccelM2(4 bytes),
                   PositionM2(4 Bytes), Buffer, CRC(2 bytes)]
```

Receive: [0xFF]

#### **119 - Buffered Drive M1 with Position**

Move M1 from the current postion to the specified new postion and hold the new postion. Default accel, decel and speeds are used.

Send: [Address, 119, Position (4 bytes), Buffer, CRC (2 bytes)] Receivr: [0xFF]

#### **120 - Buffered Drive M2 with Position**

Move M2 from the current postion to the specified new position and hold the new position. Default accel, decel and speeds are used.

Send: [Address, 120, Position (4 bytes), Buffer, CRC (2 bytes)] Receive: [0xFF]

#### **121 - Buffered Drive M1/M2 with Position**

Move M1 and M2 from the current position to the new specified position and hold the new position. Default accel, decel and speeds are used.

```
Send: [Address, 121, M1Position (4 bytes), M2Position, (4 bytes), Buffer, CRC (2 bytes)]
Receive; [0xFF]
```

#### **122 - Buffered Drive M1 with Speed and Position**

Move M1 form the current position to the specified new position and hold the new position. Default accel and decel are used.

Send; [Address, 122, Speed (4 bytes), Position (4 bytes), Buffer, CRC (2 bytes)] Receiver: [0xFF]

#### **123 - Buffered Drive M2 with Speed and Position**

Move M2 from the current position to the specified new position and hold the new position. Default accel and decel are used.

Send: [Address, 123, Speed (4 bytes), Position (4 bytes), Buffer, CRC (2 bytes)] Receiver: [0xFF]

#### **124 - Buffered Drive M1/M2 with Speed and Position**

Move M1 and M2 from the current postion to the new specified position and hold the new position. Default accel and decel are used.

Send: [Address, 124, SpeedM1 (4 bytes), PositionM1 (4 bytes), SpeedM2 (4 bytes), PositionM2 (4 bytes), Buffer, CRC (2 bytes)] Receive: [0xFF]

Image /page/100/Picture/0 description: The image shows the logo for BASICMICRO. The logo consists of a red circle with three horizontal white lines inside, followed by the word "BASICMICRO" in black, sans-serif font.