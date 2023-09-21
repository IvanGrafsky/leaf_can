def nissan_crc(data):
    data[7] = 0
    crc = 0
    for b in range(8):
      for i in range(7, -1, -1):
        bit = 1 if ((data[b] & (1 << i)) > 0) else 0
        if crc >= 0x80:
          crc = 0xff & (((crc << 1) + bit) ^ 0x85)
        else:
          crc = 0xff & ((crc << 1) + bit)
    data[7] = crc

class LeafInv:
    MOD_OFF = 0,
    MOD_RUN = 1
    MOD_PRECHARGE = 2
    MOD_PCHFAIL = 3
    MOD_CHARGE = 4
    MOD_LAST = 5

    def __init__(self, can_sender):
        self.can_sender = can_sender

        self.Vbatt = 0
        self.VbattSP = 0
        self.counter_1db = 0
        self.counter_1dc = 0
        self.counter_11a_d6 = 0
        self.counter_1d4 = 0
        self.counter_1f2 = 0
        self.counter_55b = 0
        self.OBCpwrSP = 0
        self.OBCpwr = 0
        self.OBCwake = False
        self.PPStat = False
        self.OBCVoltStat = 0
        self.PlugStat = 0

        self.final_torque_request = 0

        self.opmode = self.MOD_OFF
    
    def decode_can(self, id, data):
        if id == 0x1DA: # THIS MSG CONTAINS INV VOLTAGE, MOTOR SPEED AND ERROR STATE
            voltage = (bytes[0] << 2) | (bytes[1] >> 6) # MEASURED VOLTAGE FROM LEAF INVERTER
            parsed_speed = (bytes[4] << 8) | bytes[5]
            speed = (0 if parsed_speed == 0x7fff else parsed_speed) # LEAF MOTOR RPM
            error = (bytes[6] & 0xb0) != 0x00 # INVERTER ERROR STATE
        elif id == 0x55A: # THIS MSG CONTAINS INV TEMP AND MOTOR TEMP
            inv_temp = self.fahrenheit_to_celsius(bytes[2]) # INVERTER TEMP
            motor_temp = self.fahrenheit_to_celsius(bytes[1]) # MOTOR TEMP
        elif id == 0x679: #  THIS MSG FIRES ONCE ON CHARGE PLUG INSERT
            dummyVar = bytes[0]
            self.OBCwake = True # 0x679 is received once when we plug in if pdm is asleep so wake wakey...
        elif id == 0x390: # THIS MSG FROM PDM
            self.OBCVoltStat = (bytes[3] >> 3) & 0x03
            PlugStat = bytes[5] & 0x0F
            if PlugStat == 0x08:
                self.PPStat = True # plug inserted
            if PlugStat == 0x00:
                self.PPStat = False # plug not inserted
    
    @staticmethod
    def fahrenheit_to_celsius(fahrenheit)
        result = ((0xFFFF & fahrenheit) - 32) * 5 / 9
        if result < -128:
            return -128
        if result > 127:
            return 127
        
        return result
    
    def Task10Ms(self):
        bytes = [0] * 8

        # CAN Messaage 0x11A

        # Data taken from a gen1 inFrame where the car is starting to
        # move at about 10% throttle: 4E400055 0000017D

        # All possible gen1 values: 00 01 0D 11 1D 2D 2E 3D 3E 4D 4E
        # MSB nibble: Selected gear (gen1/LeafLogs)
        #   0: some kind of non-gear before driving
        #      0: Park in Gen 2. byte 0 = 0x01 when in park and charging
        #   1: some kind of non-gear after driving
        #   2: R
        #   3: N
        #   4: D
        # LSB nibble: ? (LeafLogs)
        #   0: sometimes at startup, not always never when the
        #      inverted is powered on (0.06%)
        #   1: this is the usual value (55% of the time in LeafLogs)
        #   D: seems to occur for ~90ms when changing gears (0.2%)
        #   E: this also is a usual value, but never occurs with the
        #      non-gears 0 and 1 (44% of the time in LeafLogs)

        #byte 0 determines motor rotation direction
        if self.opmode == self.MOD_CHARGE:
            bytes[0] = 0x01 # Car in park when charging
        if self.opmode != self.MOD_CHARGE:
            bytes[0] = 0x4E
        
        # 0x40 when car is ON, 0x80 when OFF, 0x50 when ECO. Car must be off when charing 0x80
        if self.opmode == self.MOD_CHARGE:
            bytes[1] = 0x80
        if self.opmode != self.MOD_CHARGE:
            bytes[1] = 0x40
        
        # Usually 0x00, sometimes 0x80 (LeafLogs), 0x04 seen by canmsgs
        bytes[2] = 0x00

        # Weird value at D3:4 that goes along with the counter
        # NOTE: Not actually needed, you can just send constant AA C0
        weird_d34_values = [
            [0xaa, 0xc0],
            [0x55, 0x00],
            [0x55, 0x40],
            [0xaa, 0x80],
        ]
        
        bytes[3] = weird_d34_values[self.counter_11a_d6][0] # 0xAA
        bytes[4] = weird_d34_values[self.counter_11a_d6][1] # 0xC0

        # Always 0x00 (LeafLogs, canmsgs)
        bytes[5] = 0x00

        # A 2-bit counter
        bytes[6] = self.counter_11a_d6
        
        self.counter_11a_d6 += 1
        if self.counter_11a_d6 >= 4:
            self.counter_11a_d6 = 0
            
        # Extra CRC
        nissan_crc(bytes) # not sure if this is really working or just making me look like a muppet.
        
        self.can_sender(0x11A, bytes)


        ################################################/
        # CAN Message 0x1D4: Target Motor Torque

        # Data taken from a gen1 inFrame where the car is starting to
        # move at about 10% throttle: F70700E0C74430D4

        # Usually F7, but can have values between 9A...F7 (gen1)
        bytes[0] = 0xF7
        # 2016: 6E
        # # outFrame.data.bytes[0] = 0x6E
        
        # Usually 07, but can have values between 07...70 (gen1)
        bytes[1] = 0x07
        # 2016: 6E
        #outFrame.data.bytes[1] = 0x6E

        # override any torque commands if not in run mode.
        if self.opmode != self.MOD_RUN:
            self.final_torque_request = 0

        # Requested torque (signed 12-bit value + always 0x0 in low nibble)
        if self.final_torque_request >= -2048 and self.final_torque_request <= 2047:
            bytes[2] = (0x80 if (self.final_torque_request < 0) else 0) | ((self.final_torque_request >> 4) & 0x7f)
            bytes[3] = (self.final_torque_request << 4) & 0xf0
        else:
            bytes[2] = 0x00
            bytes[3] = 0x00

        # MSB nibble: Runs through the sequence 0, 4, 8, C
        # LSB nibble: Precharge report (precedes actual precharge
        #             control)
        #   0: Discharging (5%)
        #   2: Precharge not started (1.4%)
        #   3: Precharging (0.4%)
        #   5: Starting discharge (3x10ms) (2.0%)
        #   7: Precharged (93%)
        bytes[4] = 0x07 | (self.counter_1d4 << 6)
        # bytes[4] = 0x02 | (counter_1d4 << 6)
        # Bit 2 is HV status. 0x00 No HV, 0x01 HV On.

        self.counter_1d4 += 1
        if self.counter_1d4 >= 4:
            self.counter_1d4 = 0

        # MSB nibble:
        #   0: 35-40ms at startup when gear is 0, then at shutdown 40ms
        #      after the car has been shut off (6% total)
        #   4: Otherwise (94%)
        # LSB nibble:
        #   0: ~100ms when changing gear, along with 11A D0 b3:0 value
        #      D (0.3%)
        #   2: Reverse gear related (13%)
        #   4: Forward gear related (21%)
        #   6: Occurs always when gear 11A D0 is 01 or 11 (66%)
        #outFrame.data.bytes[5] = 0x44
        #outFrame.data.bytes[5] = 0x46

        # 2016 drive cycle: 06, 46, precharge, 44, drive, 46, discharge, 06
        # 0x46 requires ~25 torque to start
        #outFrame.data.bytes[5] = 0x46
        # 0x44 requires ~8 torque to start
        bytes[5] = 0x44
        #bit 6 is Main contactor status. 0x00 Not on, 0x01 on.

        # MSB nibble:
        #   In a drive cycle, this slowly changes between values (gen1):
        #     leaf_on_off.txt:
        #       5 7 3 2 0 1 3 7
        #     leaf_on_rev_off.txt:
        #       5 7 3 2 0 6
        #     leaf_on_Dx3.txt:
        #       5 7 3 2 0 2 3 2 0 2 3 2 0 2 3 7
        #     leaf_on_stat_DRDRDR.txt:
        #       0 1 3 7
        #     leaf_on_Driveincircle_off.txt:
        #       5 3 2 0 8 B 3 2 0 8 A B 3 2 0 8 A B A 8 0 2 3 7
        #     leaf_on_wotind_off.txt:
        #       3 2 0 8 A B 3 7
        #     leaf_on_wotinr_off.txt:
        #       5 7 3 2 0 8 A B 3 7
        #     leaf_ac_charge.txt:
        #       4 6 E 6
        #   Possibly some kind of control flags, try to figure out
        #   using:
        #     grep 000001D4 leaf_on_wotind_off.txt | cut -d' ' -f10 | uniq | ~/projects/leaf_tools/util/hex_to_ascii_binary.py
        #   2016:
        #     Has different values!
        # LSB nibble:
        #   0: Always (gen1)
        #   1:  (2016)

        # 2016 drive cycle:
        #   E0: to 0.15s
        #   E1: 2 messages
        #   61: to 2.06s (inverter is powered up and precharge
        #                 starts and completes during this)
        #   21: to 13.9s
        #   01: to 17.9s
        #   81: to 19.5s
        #   A1: to 26.8s
        #   21: to 31.0s
        #   01: to 33.9s
        #   81: to 48.8s
        #   A1: to 53.0s
        #   21: to 55.5s
        #   61: 2 messages
        #   60: to 55.9s
        #   E0: to end of capture (discharge starts during this)

        # This value has been chosen at the end of the hardest
        # acceleration in the wide-open-throttle pull, with full-ish
        # torque still being requested, in
        #   LeafLogs/leaf_on_wotind_off.txt
        #outFrame.data.bytes[6] = 0x00

        # This value has been chosen for being seen most of the time
        # when, and before, applying throttle in the wide-open-throttle
        # pull, in
        #   LeafLogs/leaf_on_wotind_off.txt

        if self.opmode != self.MOD_CHARGE:
            bytes[6] = 0x30 # brake applied heavilly.
        if self.opmode == self.MOD_CHARGE:
            bytes[6] = 0xE0 # charging mode
        
        #In Gen 2 byte 6 is Charge status.
        #0x8C Charging interrupted
        #0xE0 Charging

        # Value chosen from a 2016 log
        #outFrame.data.bytes[6] = 0x61

        # Value chosen from a 2016 log
        # 2016-24kWh-ev-on-drive-park-off.pcap #12101 / 15.63s
        # outFrame.data.bytes[6] = 0x01
        #byte 6 brake signal

        # Extra CRC
        nissan_crc(bytes)
        self.can_sender(0x1D4, bytes) # send on can1

        ################################################/
        # CAN Message 0x50B

        # Statistics from 2016 capture:
        #     10 00000000000000
        #     21 000002c0000000
        #    122 000000c0000000
        #    513 000006c0000000

        # Let's just send the most common one all the time
        # FIXME: This is a very sloppy implementation. Thanks. I try:)
        bytes = [0] * 7

        bytes[0] = 0x00
        bytes[1] = 0x00
        bytes[2] = 0x06
        bytes[3] = 0xc0
        bytes[4] = 0x00
        bytes[5] = 0x00
        bytes[6] = 0x00

        # possible problem here as 0x50B is DLC 7....
        self.can_sender(0x50B, bytes)

    def SetTorque(self, torquePercent):
        self.final_torque_request = (torquePercent * 2047) / 100.0
    
    

