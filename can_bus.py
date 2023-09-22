import time
import can


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

bustype = 'socketcan'
channel = 'can1'
bus = can.interface.Bus(channel=channel, bustype=bustype,bitrate=500000)


def send_fast(counter, torque):
  raw_vip_msg = [0x4e, 0x40, 0x00, 0xaa, 0xc0, 0x00, counter & 0xff, 0x00]
  raw_torque_msg = [0x6e, 0x6e, 0xff & (torque >> 8), 0xff & torque, 0xff & (0x07 | (counter << 6)), 0x44, 0x01, 0x00]

  nissan_crc(raw_vip_msg)
  nissan_crc(raw_torque_msg)

  vip_msg = can.Message(arbitration_id=0x11A, data=raw_vip_msg, is_extended_id=False)
  torque_msg = can.Message(arbitration_id=0x1D4, data=raw_torque_msg, is_extended_id=False)

  bus.send(vip_msg)
  bus.send(torque_msg)

heartbeat_msg = can.Message(arbitration_id=0x50B, data=[0x00, 0x00, 0x06, 0xc0, 0x00, 0x00, 0x00], is_extended_id=False)

torque = 0
counter = 0

t_start = time.time()

while True:
  if time.time() - t_start  > 15.0:
    torque = 1000
  else:
    torque = 0

  for i in range(10):
    if i == 0:
      bus.send(heartbeat_msg)
    send_fast(counter, torque)
    counter += 1
    if counter > 3:
      counter = 0
    time.sleep(0.01)