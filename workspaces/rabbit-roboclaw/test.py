#!/usr/bin/env python3

import sys
import time
import os

# Import your RoboClaw class here
# from your_module import RoboClaw

# For now, I'll assume the class is in the same file or imported
# Replace this with your actual import

def check_port_permissions():
    """Check if user has access to serial ports"""
    
    # Check if running as root
    if os.getuid() == 0:
        print("✓ Running as root - full access to all ports")
        return True
    
    import grp
    
    try:
        dialout_group = grp.getgrnam('dialout')
        user_groups = [grp.getgrgid(gid).gr_name for gid in os.getgroups()]
        
        if 'dialout' in user_groups:
            print("✓ User is in dialout group")
            return True
        else:
            print("✗ User NOT in dialout group")
            print("Run: sudo usermod -a -G dialout $USER")
            print("Then logout and login again")
            return False
    except:
        print("? Could not check dialout group membership")
        return True

def test_jetson_ports():
    """Test available UART ports on Jetson Orin Nano"""
    
    # Jetson Orin Nano specific ports in order of preference
    ports_to_test = [
        '/dev/ttyTHS1',    # Most common UART on pins 8,10
        '/dev/ttyTHS2',    # Alternative UART
        '/dev/ttyAMA0',    # Another UART option
        '/dev/ttyS0',      # Standard serial
        '/dev/ttyS1',      # Standard serial
        '/dev/ttyUSB0',    # USB-UART adapter if connected
        '/dev/ttyUSB1',    # USB-UART adapter if connected
    ]
    
    print("=== TESTING JETSON ORIN NANO UART PORTS ===")
    print(f"Available ports to test: {[p for p in ports_to_test if os.path.exists(p)]}")
    
    for port in ports_to_test:
        if not os.path.exists(port):
            print(f"⚠ {port} - does not exist")
            continue
            
        print(f"\n🔍 Testing {port}...")
        
        # Check permissions
        try:
            stat = os.stat(port)
            print(f"   Permissions: {oct(stat.st_mode)[-3:]}")
        except Exception as e:
            print(f"   ✗ Cannot stat: {e}")
            continue
        
        # Try to open port
        try:
            import serial
            ser = serial.Serial(port, 115200, timeout=0.1)
            print(f"   ✓ Port opens successfully")
            ser.close()
            
            # Test with RoboClaw
            result = test_roboclaw_on_port(port)
            if result:
                return port
                
        except PermissionError:
            if os.getuid() == 0:
                print(f"   ✗ Permission denied even as root - port may be in use")
            else:
                print(f"   ✗ Permission denied - run as root or check dialout group")
        except Exception as e:
            print(f"   ✗ Cannot open: {e}")
    
    return None

def test_roboclaw_on_port(port):
    """Test RoboClaw on specific port"""
    
    # You'll need to replace this with your actual RoboClaw class
    # For now, this is a mock test
    print(f"   🤖 Testing RoboClaw on {port}...")
    
    try:
        # Replace this with your actual RoboClaw initialization
        # rc = RoboClaw(port, baudrate=115200, address=0x80)
        # if not rc.open():
        #     print(f"   ✗ Failed to open RoboClaw connection")
        #     return False
        
        # Test version read
        # version = rc.read_version()
        # if version:
        #     print(f"   ✓ RoboClaw found: {version}")
        #     rc.close()
        #     return True
        # else:
        #     print(f"   ✗ No response from RoboClaw")
        #     rc.close()
        #     return False
        
        # Mock test for now
        print(f"   ⚠ Mock test - replace with actual RoboClaw code")
        return False
        
    except Exception as e:
        print(f"   ✗ RoboClaw test failed: {e}")
        return False

def jetson_uart_setup_guide():
    """Print setup guide for Jetson UART"""
    
    print("\n=== JETSON ORIN NANO UART SETUP GUIDE ===")
    print()
    print("1. Physical connections to 40-pin header:")
    print("   Pin 8  (GPIO14/UART1_TX) -> RoboClaw S1 (RX)")
    print("   Pin 10 (GPIO15/UART1_RX) -> RoboClaw S2 (TX)")
    print("   Pin 6  (GND)             -> RoboClaw GND")
    print()
    print("2. Enable UART if needed:")
    print("   sudo /opt/nvidia/jetson-io/jetson-io.py")
    print("   Select: Configure Jetson 40pin Header")
    print("   Enable: UART1 (/dev/ttyTHS1)")
    print("   Reboot after changes")
    print()
    print("3. Check device tree (current UART status):")
    print("   cat /proc/device-tree/chosen/overlays/name")
    print("   dmesg | grep -i uart")
    print()
    print("4. Set permissions (if not root):")
    print("   sudo usermod -a -G dialout $USER")
    print("   sudo chmod 666 /dev/ttyTHS1  # temporary fix")
    print()

def advanced_diagnostics():
    """Run advanced diagnostics"""
    
    print("\n=== ADVANCED JETSON UART DIAGNOSTICS ===")
    
    # Check device tree
    print("\n📋 Device tree UART status:")
    try:
        with open('/proc/device-tree/chosen/overlays/name', 'r') as f:
            overlays = f.read()
            if 'uart' in overlays.lower():
                print("   ✓ UART overlays found in device tree")
            else:
                print("   ⚠ No UART overlays found - may need to enable")
    except:
        print("   ? Cannot read device tree overlays")
    
    # Check dmesg for UART
    print("\n📋 Kernel UART messages:")
    os.system("dmesg | grep -i uart | tail -5")
    
    # Check GPIO state
    print("\n📋 GPIO pin state (pins 8,10):")
    try:
        # These are the GPIO numbers for pins 8,10 on Jetson Orin Nano
        for gpio_num in [14, 15]:  # GPIO14=Pin8, GPIO15=Pin10
            gpio_path = f"/sys/class/gpio/gpio{gpio_num}"
            if os.path.exists(gpio_path):
                print(f"   GPIO{gpio_num}: exists")
            else:
                print(f"   GPIO{gpio_num}: not exported")
    except:
        pass
    
    # Test loopback if possible
    print("\n📋 Loopback test suggestion:")
    print("   Connect Pin 8 to Pin 10 (TX to RX)")
    print("   Run: sudo python3 -c \"")
    print("   import serial; s=serial.Serial('/dev/ttyTHS1',115200);")
    print("   s.write(b'test'); print(s.read(4))\"")

def main():
    """Main test function"""
    
    print(f"🚀 JETSON ORIN NANO ROBOCLAW TEST (UID: {os.getuid()})")
    print("=" * 50)
    
    # Check basic requirements
    print("\n1️⃣  Checking permissions...")
    if not check_port_permissions():
        print("❌ Fix permissions first!")
        return
    
    # Test ports
    print("\n2️⃣  Testing UART ports...")
    working_port = test_jetson_ports()
    
    if working_port:
        print(f"\n✅ SUCCESS! RoboClaw working on {working_port}")
        
        # Run full test here with your RoboClaw class
        print("\n3️⃣  Running full RoboClaw test...")
        print("   📝 TODO: Add your RoboClaw test code here")
        
    else:
        print("\n❌ No working RoboClaw connection found")
        print("\n🔧 Troubleshooting:")
        jetson_uart_setup_guide()
        
        print("\n🔍 Advanced diagnostics:")
        advanced_diagnostics()
        
        print("\n💡 Common issues:")
        print("   - RoboClaw not powered (connect battery to B+/B-)")
        print("   - Wrong TX/RX connections")
        print("   - UART not enabled in device tree")
        print("   - Wrong baud rate (try 38400, 9600)")
        print("   - Wrong RoboClaw address (try 0x80-0x87)")

if __name__ == "__main__":
    main()