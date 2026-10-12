# Flipdots Display Control Protocols

Transcription of AlfaZeta's protocol sheet. For wiring, DIP switches, power, refresh limits, and how this project uses the protocol, see `docs/hardware.md`.

Notation in this document uses width × height. Panels are 7 pixels tall (height = 7), with widths of 7, 14, or 28.

Flipdots display control protocols   - August 2018

Frame: [0x80 Command Address Data 0x8F]

| Command | Number of Data Bytes | Refresh? | Configuration                                |
|---------|---------------------|----------|-----------------------------------------------|
| 0x82    | 0                   | YES      | Format (0x80, 0x82, 0x8F) <br> refresh of all connected displays |
| 0x83    | 28                  | YES      | 28x7                                          |
| 0x84    | 28                  | NO       | 28x7                                          |
| 0x87    | 7                   | YES      | 7x7                                           |
| 0x92    | 14                  | YES      | 14x7                                          |
| 0x93    | 14                  | NO       | 14x7                                          |


Address – device address , 255 (0xFF) is a broadcast address – all devices are receiving this
transmission

Data – transmitted content of a display; number of data bytes depends on size of a display. One
byte is one strip of dots (7 dots). LSB  is upper dot,  MSB (the 7th) is lower dot. The
most significant byte (8th) is ignored and should be set to zero.


Remarks:
Refresh = YES: DATA bytes are being shown on displays as soon as they are received
Refresh = NO: DATA bytes are being stored in a memory and shown on displays as soon as 0x80 /
0x82 / 0x8F sequence is received. This option helps to synchronize presentation of data. This is not
supported by 7x7 displays.

