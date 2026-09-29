"""Simulator Modbus cho Node 01, 02, 03 (bảng thanh ghi ở spec mục 4.5).

- Cổng serial ảo `sim://<tên>`: pyserial nạp handler protocol_sim của gói này, nên pymodbus mở được như cổng
  thật. Bus mô phỏng có baud rate, parity, đổi địa chỉ bằng FC 06, và các lỗi theo kịch bản.
- `greenhouse sim-tcp`: server pymodbus cho Modbus TCP hoặc RTU over TCP.
"""

import serial

if "greenhouse.sim" not in serial.protocol_handler_packages:
    serial.protocol_handler_packages.append("greenhouse.sim")
